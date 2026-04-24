"""
FastAPI Backend Server
Main application with EventSource streaming for agentic AI reasoning.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
from dotenv import load_dotenv

# Import tools
from app.tools.search_ai_news import create_ai_news_searcher
from app.tools.get_ai_stocks import create_ai_stocks_fetcher
from app.tools.get_weather import create_weather_fetcher
from app.tools.schedule_email import create_email_scheduler
from app.tools.todo_manager import create_todo_manager

# Import agent
from app.agent.agent_loop import create_agent, AgentMessage

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('gandalf_assistant.log')
    ]
)
logger = logging.getLogger(__name__)

# Environment variables
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
BACKEND_HOST = os.getenv('BACKEND_HOST', 'localhost')
BACKEND_PORT = int(os.getenv('BACKEND_PORT', 8000))
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# Validate required environment variables
if not GEMINI_API_KEY:
    logger.error("ERROR: GEMINI_API_KEY not set in .env file")
    sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown logs."""
    logger.info("Gandalf the Organizer starting up...")
    logger.info(f"Server will run on {BACKEND_HOST}:{BACKEND_PORT}")
    logger.info("All systems online. Ready to organize!")
    try:
        yield
    finally:
        logger.info("Gandalf the Organizer shutting down...")

# Initialize FastAPI app
app = FastAPI(
    title="Gandalf the Organizer",
    description="AI Personal Assistant with Agentic Reasoning",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize tools
logger.info("Initializing tools...")
import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)

ai_news_searcher = create_ai_news_searcher(genai)
ai_stocks_fetcher = create_ai_stocks_fetcher(genai)
weather_fetcher = create_weather_fetcher(genai)
todo_manager = create_todo_manager()

if EMAIL_SENDER and EMAIL_PASSWORD:
    email_scheduler = create_email_scheduler(EMAIL_SENDER, EMAIL_PASSWORD)
else:
    logger.warning("WARNING: Email configuration not set. Email scheduling disabled.")
    email_scheduler = None

logger.info("Tools initialized successfully")

# Tools dictionary for agent
tools_dict = {
    "search_ai_news": ai_news_searcher.search_ai_news,
    "get_ai_stocks": ai_stocks_fetcher.get_top_ai_stocks,
    "get_weather": weather_fetcher.get_weather,
    "add_todo": todo_manager.add_todo,
    "get_todos": todo_manager.get_todos,
}

# Initialize agent
logger.info("Initializing Gemini Agent...")
agent = create_agent(GEMINI_API_KEY, tools_dict)
logger.info("Agent initialized successfully")


# ============================================================================
# Request Models
# ============================================================================

class AgentRunRequest(BaseModel):
    """Request model for running the agent."""
    task: str
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    email: Optional[str] = None
    max_iterations: Optional[int] = 10


class TodoRequest(BaseModel):
    """Request model for adding a to-do."""
    title: str
    description: str
    due_date: str
    importance: Optional[str] = "medium"


class EventRequest(BaseModel):
    """Request model for scheduling an event."""
    event_title: str
    event_time: str
    event_description: str
    recipient_email: str
    reminder_minutes_before: Optional[int] = 15


def build_agent_stream_response(task: str, city: Optional[str], latitude: Optional[float], longitude: Optional[float], email: Optional[str], max_iterations: Optional[int]):
    """Build a streaming SSE response for the agent loop."""
    logger.info(f"Received agent request: {task}")

    async def event_generator():
        """Generate SSE events for agent reasoning."""
        try:
            user_context = {}
            if city:
                user_context["city"] = city
            if latitude is not None:
                user_context["latitude"] = latitude
            if longitude is not None:
                user_context["longitude"] = longitude
            if email:
                user_context["email"] = email

            last_message = None

            async for message in agent.run_agent_loop(
                task=task,
                user_context=user_context,
                max_iterations=max_iterations or 10
            ):
                last_message = message
                message_dict = message.to_dict()
                logger.info(f"[{message.type.upper()}] {message.content}")
                yield f"data: {json.dumps(message_dict)}\n\n"

            completion_msg = {
                "type": "completed",
                "content": "Agent reasoning completed",
                "timestamp": last_message.timestamp if last_message else None,
            }
            yield f"data: {json.dumps(completion_msg)}\n\n"

        except Exception as e:
            logger.error(f"Agent error: {str(e)}")
            error_msg = {
                "type": "error",
                "content": f"Agent error: {str(e)}"
            }
            yield f"data: {json.dumps(error_msg)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Gandalf the Organizer",
        "version": "1.0.0"
    }


@app.get("/config")
async def get_config():
    """Get server configuration."""
    return {
        "host": BACKEND_HOST,
        "port": BACKEND_PORT,
        "debug": DEBUG,
        "features": {
            "ai_news": True,
            "ai_stocks": True,
            "weather": False,
            "todos": True,
            "email_scheduling": email_scheduler is not None
        }
    }


# ============================================================================
# Agent Loop Endpoint (Streaming)
# ============================================================================

@app.get("/api/agent/run")
async def run_agent_get(
    task: str = Query(...),
    city: Optional[str] = Query(None),
    latitude: Optional[str] = Query(None),
    longitude: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    max_iterations: Optional[int] = Query(10),
):
    """
    Run the agent loop with streaming response via GET for EventSource.
    Empty strings for latitude/longitude are treated as None to avoid 422 errors.
    """
    def _parse_optional_float(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw or raw.lower() in {"none", "null", "undefined", "nan"}:
            return None
        try:
            return float(raw)
        except ValueError:
            logger.warning("Invalid coordinate value received: %s", value)
            return None

    lat = _parse_optional_float(latitude)
    lon = _parse_optional_float(longitude)
    return build_agent_stream_response(task, city, lat, lon, email, max_iterations)


@app.post("/api/agent/run")
async def run_agent(request: AgentRunRequest):
    """Run the agent loop with streaming response via POST."""
    return build_agent_stream_response(
        request.task,
        request.city,
        request.latitude,
        request.longitude,
        request.email,
        request.max_iterations,
    )


# ============================================================================
# To-Do Endpoints
# ============================================================================

@app.get("/api/todos")
async def get_todos():
    """Get all to-do items."""
    logger.info("Fetching all to-dos")
    try:
        result = await todo_manager.get_todos()
        return result
    except Exception as e:
        logger.error(f"Error fetching to-dos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/todos")
async def add_todo(request: TodoRequest):
    """Add a new to-do item."""
    logger.info(f"Adding to-do: {request.title}")
    try:
        result = await todo_manager.add_todo(
            request.title,
            request.description,
            request.due_date,
            request.importance
        )
        return result
    except Exception as e:
        logger.error(f"Error adding to-do: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/todos/{todo_id}")
async def update_todo(todo_id: int, update_data: Dict[str, Any]):
    """Update a to-do item."""
    logger.info(f"Updating to-do: {todo_id}")
    try:
        result = await todo_manager.update_todo(todo_id, **update_data)
        return result
    except Exception as e:
        logger.error(f"Error updating to-do: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/todos/{todo_id}")
async def delete_todo(todo_id: int):
    """Delete a to-do item."""
    logger.info(f"Deleting to-do: {todo_id}")
    try:
        result = await todo_manager.delete_todo(todo_id)
        return result
    except Exception as e:
        logger.error(f"Error deleting to-do: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/todos/{todo_id}/complete")
async def complete_todo(todo_id: int):
    """Mark a to-do as complete."""
    logger.info(f"Completing to-do: {todo_id}")
    try:
        result = await todo_manager.complete_todo(todo_id)
        return result
    except Exception as e:
        logger.error(f"Error completing to-do: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Event Scheduling Endpoint
# ============================================================================

@app.post("/api/events/schedule")
async def schedule_event(request: EventRequest):
    """Schedule an event with email reminder."""
    logger.info(f"Scheduling event: {request.event_title}")
    
    if not email_scheduler:
        raise HTTPException(status_code=501, detail="Email scheduling not configured")
    
    try:
        result = await email_scheduler.schedule_event_reminder(
            request.event_title,
            request.event_time,
            request.event_description,
            request.recipient_email,
            request.reminder_minutes_before
        )
        return result
    except Exception as e:
        logger.error(f"Error scheduling event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/scheduled")
async def get_scheduled_events():
    """Get all scheduled events."""
    logger.info("Fetching scheduled events")
    
    if not email_scheduler:
        return {"events": [], "message": "Email scheduling not configured"}
    
    try:
        result = await email_scheduler.get_scheduled_events()
        return result
    except Exception as e:
        logger.error(f"Error fetching scheduled events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {str(exc)}")
    return {
        "status": "error",
        "message": str(exc)
    }


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting FastAPI server on {BACKEND_HOST}:{BACKEND_PORT}")
    
    uvicorn.run(
        "main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        reload=DEBUG,
        log_level="info"
    )
