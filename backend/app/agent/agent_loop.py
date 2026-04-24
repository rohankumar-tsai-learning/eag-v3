"""
Agent Loop - LLM-Driven Tool Selection
Core agentic reasoning system using Gemini API.
Handles LLM-driven tool calling, reasoning, and response streaming.
NO hardcoded pipelines - all tool selection driven by LLM.
"""

import logging
import json
import asyncio
import re
import math
import time
from typing import Optional, Dict, Any, AsyncGenerator, List, Callable
from datetime import datetime
import google.generativeai as genai

logger = logging.getLogger(__name__)


class AgentMessage:
    """Represents a message in the agent loop."""
    
    def __init__(self, message_type: str, content: str, metadata: Optional[Dict] = None):
        self.type = message_type  # thought, tool_call, observation, answer
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            "type": self.type,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


class GeminiAgent:
    """
    Agentic AI system using Gemini 3.1 Flash.
    Implements proper multi-step tool calling and reasoning loops.
    All tool selection is driven by LLM decisions.
    """
    
    def __init__(self, api_key: str, tools: Dict[str, Callable]):
        self.api_key = api_key
        self.tools = tools
        self.reasoning_history = []
        self._llm_request_lock = asyncio.Lock()
        self._llm_min_interval_seconds = 10.0
        self._last_llm_request_started_at = 0.0
        self._next_module_tool_allowed_at = 0.0
        
        # Configure Gemini
        genai.configure(api_key=api_key)
        
        # Create tool definitions for Gemini
        self.tool_definitions = self._create_tool_definitions()

        # Resolve an account-compatible model set at runtime.
        self.model_candidates = self._resolve_model_candidates()
        self.model_name = self.model_candidates[0]
        self.fallback_models = self.model_candidates[1:]
        
        # Initialize model. Tool orchestration is handled in the loop so this
        # stays compatible with older google-generativeai SDK versions.
        self.model = genai.GenerativeModel(self.model_name)

    def _resolve_model_candidates(self) -> List[str]:
        """Return the fixed Gemini 3.1 Flash Lite model list (preview name first)."""
        candidates = [
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-flash-lite",
        ]
        logger.info(f"Using Gemini 3.1 Flash Lite models: {candidates}")
        return candidates

    def _is_quota_error(self, error_message: str) -> bool:
        """Detect quota/rate-limit errors from provider responses."""
        msg = error_message.lower()
        return "429" in msg or "quota" in msg or "rate limit" in msg
    
    def _create_tool_definitions(self) -> List[Any]:
        """Create Gemini-compatible tool definitions."""
        tools_list = []
        
        # Define each tool that Gemini can call
        tool_configs = {
            "search_ai_news": {
                "description": "Search for latest AI news and research updates",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for AI news"},
                        "limit": {"type": "integer", "description": "Number of results (default 5)"}
                    },
                    "required": ["query"]
                }
            },
            "get_ai_stocks": {
                "description": "Get top AI stocks to invest in globally",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of stocks to return (max 10)"}
                    }
                }
            },
            "get_weather": {
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "Location string (city name)"},
                        "city": {"type": "string", "description": "City name"},
                        "country": {"type": "string", "description": "Country name (default: USA)"},
                        "latitude": {"type": "number", "description": "Latitude coordinate"},
                        "longitude": {"type": "number", "description": "Longitude coordinate"}
                    },
                    "required": []
                }
            },
            "get_todos": {
                "description": "Get all to-do items",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            "add_todo": {
                "description": "Add a new to-do item",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Task title"},
                        "description": {"type": "string", "description": "Task description (max 200 words)"},
                        "due_date": {"type": "string", "description": "Due date in ISO format"},
                        "importance": {"type": "string", "description": "Importance level: low, medium, high"}
                    },
                    "required": ["title", "description", "due_date"]
                }
            }
        }
        
        # Create tool objects
        for tool_name, config in tool_configs.items():
            if tool_name in self.tools:
                tool = {
                    "function_declarations": [{
                        "name": tool_name,
                        "description": config["description"],
                        "parameters": config["parameters"]
                    }]
                }
                tools_list.append(tool)
        
        return tools_list

    async def run_agent_loop(
        self,
        task: str,
        user_context: Optional[Dict] = None,
        max_iterations: int = 10
    ) -> AsyncGenerator[AgentMessage, None]:
        """
        Run the agent loop with LLM-driven tool selection.
        
        No hardcoded pipelines - LLM decides which tools to call.
        After each tool call, emits grouped payloads with:
        - weather/stocks: data + LLM summary
        - news: data only (no summarization)
        
        Args:
            task: The task/prompt for the agent
            user_context: Optional user context (city, email, etc.)
            max_iterations: Max reasoning iterations
            
        Yields:
            AgentMessage objects for each step
        """
        logger.info(f"Starting Agent Loop - Task: {task}")
        logger.info(f"Max iterations: {max_iterations}")
        
        # Store user_context for use in _execute_tool
        self._user_context = user_context or {}
        
        self.reasoning_history = []
        tool_history: List[Dict[str, Any]] = []
        called_tools: Dict[str, bool] = {
            "get_weather": False,
            "get_ai_stocks": False,
            "search_ai_news": False,
        }
        
        yield AgentMessage(
            "thought",
            f"Analyzing task: {task}",
            {"step": 1, "action": "initial_analysis"}
        )
        
        try:
            system_message = self._build_system_prompt(task, user_context)
            logger.info(f"User Query: {task}")
            
            iteration = 0
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"\nITERATION {iteration} of {max_iterations}")
                
                yield AgentMessage(
                    "thought",
                    f"Step {iteration}: Reasoning with Gemini...",
                    {"iteration": iteration, "action": "reasoning"}
                )

                prompt = self._build_iteration_prompt(system_message, task, tool_history)

                try:
                    async with self._llm_request_lock:
                        self._last_llm_request_started_at = time.monotonic()
                        response = self.model.generate_content(
                            prompt,
                            generation_config=genai.types.GenerationConfig(
                                max_output_tokens=1024,
                                temperature=0.2
                            )
                        )
                    response_text = response.text if getattr(response, "text", None) else ""
                    logger.info(f"LLM Response: {response_text[:100] if response_text else 'No text'}...")
                except Exception as e:
                    if self._is_quota_error(str(e)):
                        if tool_history:
                            fallback_answer = (
                                "I hit API quota limits while finalizing the response, "
                                "but I already retrieved partial tool results for this run."
                            )
                            logger.warning("Quota hit after partial tool results. Returning partial-answer fallback.")
                            yield AgentMessage(
                                "answer",
                                fallback_answer,
                                {
                                    "iteration": iteration,
                                    "action": "quota_partial_fallback",
                                    "partial_tool_results": True,
                                }
                            )
                            return

                        logger.error(f"LLM Quota Error: {str(e)}")
                        yield AgentMessage(
                            "error",
                            "LLM Error: API quota/rate limit reached. Please retry later or increase quota.",
                            {"iteration": iteration, "action": "quota_error"}
                        )
                        break

                    logger.error(f"LLM Error: {str(e)}")
                    yield AgentMessage(
                        "error",
                        f"LLM Error: {str(e)}",
                        {"iteration": iteration}
                    )
                    break

                parsed_response = self._parse_model_response(response_text)
                if parsed_response.get("thought"):
                    yield AgentMessage(
                        "thought",
                        parsed_response["thought"],
                        {"iteration": iteration, "action": "model_reasoning"}
                    )

                tool_calls = parsed_response.get("tool_calls", [])

                if not tool_calls:
                    # No tool calls needed, move to next iteration
                    continue

                for tool_call in tool_calls:
                    tool_name = tool_call["tool"]
                    tool_args = tool_call["args"]

                    # Cooldown applies only between summarized module tool cycles.
                    if self._get_module_name(tool_name):
                        now = time.monotonic()
                        remaining = self._next_module_tool_allowed_at - now
                        if remaining > 0:
                            rounded_wait = math.ceil(remaining)
                            logger.info(
                                "Module cooldown active. Waiting %ss before next module tool.",
                                rounded_wait,
                            )
                            yield AgentMessage(
                                "thought",
                                f"Module cooldown active. Next tool call in {rounded_wait} seconds.",
                                {
                                    "action": "module_cooldown_wait",
                                    "wait_seconds": rounded_wait,
                                },
                            )
                            await asyncio.sleep(remaining)

                    yield AgentMessage(
                        "tool_call",
                        f"Calling: {tool_name}({json.dumps(tool_args)})",
                        {"iteration": iteration, "tool": tool_name, "args": tool_args}
                    )

                    logger.info(f"Tool Call #{iteration}: {tool_name}")
                    logger.info(f"   Args: {json.dumps(tool_args)}")

                    try:
                        result = await self._execute_tool(tool_name, tool_args)
                        called_tools[tool_name] = True
                        
                        tool_history.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "status": "success",
                            "result": result,
                        })

                        yield AgentMessage(
                            "observation",
                            f"Tool Result from {tool_name}: {json.dumps(result)[:200]}...",
                            {
                                "iteration": iteration,
                                "tool": tool_name,
                                "status": "success",
                                "result": result
                            }
                        )

                        # Handle grouped payload for module tools (weather, stocks, news)
                        module_name = self._get_module_name(tool_name)
                        if module_name:
                            summary = None
                            
                            # For weather and stocks: generate LLM summary
                            if module_name in ["weather", "stocks"]:
                                # Summarize tool response for weather/stocks only.
                                async for countdown_msg in self._call_llm_summarize_with_countdown(
                                    module_name=module_name,
                                    task=task,
                                    tool_result=result
                                ):
                                    if isinstance(countdown_msg, AgentMessage):
                                        yield countdown_msg
                                    else:
                                        summary = countdown_msg

                                # Start cooldown only after summarized module payload is produced.
                                self._next_module_tool_allowed_at = time.monotonic() + self._llm_min_interval_seconds
                                logger.info(
                                    "Starting module cooldown for %ss after %s summarization.",
                                    int(self._llm_min_interval_seconds),
                                    module_name,
                                )
                            # For news: no summarization needed
                            
                            yield AgentMessage(
                                "observation",
                                f"Grouped payload for {module_name}",
                                {
                                    "iteration": iteration,
                                    "tool": tool_name,
                                    "status": "success",
                                    "module_group": {
                                        "module": module_name,
                                        "status": "success",
                                        "payload": {
                                            "data": result,
                                            "summary": summary,
                                        }
                                    }
                                }
                            )

                        logger.info(f"Tool executed successfully: {tool_name}")
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"Tool execution failed: {tool_name} - {error_msg}")
                        tool_history.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "status": "error",
                            "error": error_msg,
                        })

                        yield AgentMessage(
                            "observation",
                            f"Tool Error: {error_msg}",
                            {
                                "iteration": iteration,
                                "tool": tool_name,
                                "status": "error",
                                "error": error_msg
                            }
                        )

                logger.info(f"Tool calls made. Moving to iteration {iteration + 1}...")

            logger.warning(f"Max iterations reached: {max_iterations}")
        
        except Exception as e:
            logger.error(f"Agent loop error: {str(e)}")
            yield AgentMessage(
                "error",
                f"Agent Error: {str(e)}",
                {"error": str(e)}
            )

    async def _call_llm_summarize_with_countdown(
        self,
        module_name: str,
        task: str,
        tool_result: Dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        """Summarize module data (weather/stocks) and yield summary as final item."""
        summary_prompt = (
            f"You are Gandalf the Organizer. Summarize this data in 2-3 concise sentences. "
            f"Focus on actionable highlights for the user.\n\n"
            f"Module: {module_name}\n"
            f"User Task: {task}\n"
            f"Data:\n{json.dumps(tool_result, indent=2)}\n"
        )

        try:
            async with self._llm_request_lock:
                self._last_llm_request_started_at = time.monotonic()
                response = self.model.generate_content(
                    summary_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=240,
                        temperature=0.2,
                    ),
                )

            summary = response.text.strip() if getattr(response, "text", None) else "Summary unavailable."
            if not summary:
                summary = "Summary unavailable."

            logger.info("LLM summary generated for %s", module_name)
            yield summary
        except Exception as e:
            logger.error("Failed to summarize %s: %s", module_name, str(e))
            yield None
    
    def _get_module_name(self, tool_name: str) -> Optional[str]:
        """Map tool name to module name."""
        mapping = {
            "get_weather": "weather",
            "get_ai_stocks": "stocks",
            "search_ai_news": "news",
        }
        return mapping.get(tool_name)
    
    def _build_system_prompt(self, task: str, user_context: Optional[Dict]) -> str:
        """Build the system prompt with tool information."""
        tools_info = "\n".join([
            f"- {name}: {self._get_tool_description(name)}"
            for name in self.tools.keys()
        ])
        
        context_str = ""
        location_note = ""
        if user_context:
            context_str = f"\n\nUser Context: {json.dumps(user_context, indent=2)}"
            if user_context.get("latitude") is not None or user_context.get("longitude") is not None:
                location_note = "\nIMPORTANT: Use the user's latitude/longitude from context for weather calls."
            elif user_context.get("city"):
                location_note = "\nIMPORTANT: Use the user's city from context for weather calls."
        
        system_prompt = f"""You are Gandalf the Organizer, an AI Personal Assistant powered by Gemini.

Your role is to help users with:
1. Task management (To-Do lists)
2. AI news and research updates
3. Stock market information (AI-focused investments)
4. Weather information
5. Event scheduling

Available Tools:
{tools_info}

When responding:
    {location_note}

{context_str}

Task: {task}
"""
        return system_prompt

    def _build_iteration_prompt(self, system_message: str, task: str, tool_history: List[Dict[str, Any]]) -> str:
        """Build a version-safe prompt that asks Gemini to emit JSON tool plans."""
        tool_history_str = json.dumps(tool_history, indent=2) if tool_history else "[]"

        return f"""{system_message}

You must manage tools using a strict JSON protocol.

Return exactly one JSON object with this schema:
{{
  "thought": "short reasoning about what to do next",
  "tool_calls": [
    {{"tool": "tool_name", "args": {{"arg1": "value"}}}}
  ],
  "final_answer": "final user-facing answer or empty string if more tool calls are needed"
}}

Rules:
- Return valid JSON only. No markdown fences.
- If you need more information, put one or more entries in tool_calls and set final_answer to an empty string.
- If you have enough information, set tool_calls to [] and provide final_answer.
- Only use these tool names: {', '.join(self.tools.keys())}
- Tool args must be valid JSON objects.
- Use prior tool results to decide the next step.

User task:
{task}

Prior tool observations:
{tool_history_str}
"""

    def _parse_model_response(self, response_text: str) -> Dict[str, Any]:
        """Parse the model JSON protocol with graceful fallback to final text."""
        parsed_json = self._extract_json_object(response_text)

        if not parsed_json:
            return {
                "thought": "Model returned plain text instead of structured JSON.",
                "tool_calls": [],
                "final_answer": response_text.strip(),
            }

        tool_calls = []
        raw_tool_calls = parsed_json.get("tool_calls") or []
        if isinstance(raw_tool_calls, list):
            for raw_tool_call in raw_tool_calls:
                if not isinstance(raw_tool_call, dict):
                    continue

                tool_name = raw_tool_call.get("tool") or raw_tool_call.get("name")
                tool_args = raw_tool_call.get("args") or {}
                if tool_name in self.tools and isinstance(tool_args, dict):
                    tool_calls.append({"tool": tool_name, "args": tool_args})

        final_answer = parsed_json.get("final_answer")
        if final_answer is None:
            final_answer = parsed_json.get("answer", "")

        return {
            "thought": str(parsed_json.get("thought", "")).strip(),
            "tool_calls": tool_calls,
            "final_answer": str(final_answer).strip() if final_answer else "",
        }

    def _extract_json_object(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Extract a JSON object from a model response, including fenced output."""
        candidate = response_text.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
        if fence_match:
            candidate = fence_match.group(1)

        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        try:
            parsed = json.loads(candidate[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    
    def _get_tool_description(self, tool_name: str) -> str:
        """Get description for a tool."""
        descriptions = {
            "search_ai_news": "Search for latest AI news and research",
            "get_ai_stocks": "Get top AI stocks to invest in globally",
            "get_weather": "Get weather information for a location",
            "add_todo": "Add a new to-do item",
            "get_todos": "Retrieve all to-do items",
            "schedule_event": "Schedule an event with email reminder",
            "get_scheduled_events": "Get all scheduled events"
        }
        return descriptions.get(tool_name, "Tool function")
    
    async def _execute_tool(self, tool_name: str, tool_args: Dict) -> Dict[str, Any]:
        """Execute a tool and return result."""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Normalize weather tool args from model output to avoid keyword mismatches.
        if tool_name == "get_weather":
            normalized_args = dict(tool_args or {})
            if "location" in normalized_args and "city" not in normalized_args:
                normalized_args["city"] = normalized_args["location"]

            lat = normalized_args.get("latitude")
            lon = normalized_args.get("longitude")
            requested_city = normalized_args.get("city")
            if isinstance(requested_city, str):
                requested_city = requested_city.strip()
            else:
                requested_city = None

            generic_city_values = {"current", "current location", "location", "here", "my location"}
            if requested_city and requested_city.lower() in generic_city_values:
                requested_city = None
                normalized_args.pop("city", None)
            
            # Use user context coordinates if not in tool args
            if (lat is None or lon is None) and hasattr(self, '_user_context'):
                context_lat = self._user_context.get("latitude")
                context_lon = self._user_context.get("longitude")
                if context_lat is not None and context_lon is not None:
                    lat = context_lat
                    lon = context_lon
                if not requested_city:
                    context_city = self._user_context.get("city")
                    if isinstance(context_city, str) and context_city.strip():
                        requested_city = context_city.strip()

            # If we resolved a city fallback, persist it into tool args path.
            if requested_city:
                normalized_args["city"] = requested_city
            
            if lat is not None and lon is not None:
                city_label = requested_city

                weather_tool = self.tools[tool_name].__self__
                return await weather_tool.get_weather_by_coordinates(
                    float(lat),
                    float(lon),
                    city_label,
                )

            allowed_weather_args = {"city", "country"}
            tool_args = {k: v for k, v in normalized_args.items() if k in allowed_weather_args}
        
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
        
        tool_func = self.tools[tool_name]
        
        # Call the tool (async or sync)
        try:
            if asyncio.iscoroutinefunction(tool_func):
                result = await tool_func(**tool_args)
            else:
                result = tool_func(**tool_args)
            
            logger.info(f"Tool result: {json.dumps(result)[:200]}...")
            return result
            
        except Exception as e:
            logger.error(f"Tool execution error: {str(e)}")
            raise
    
    async def get_reasoning_history(self) -> List[Dict]:
        """Get the reasoning history."""
        return [msg.to_dict() for msg in self.reasoning_history]


def create_agent(api_key: str, tools: Dict[str, Callable]) -> GeminiAgent:
    """Factory function to create a GeminiAgent instance."""
    return GeminiAgent(api_key, tools)
