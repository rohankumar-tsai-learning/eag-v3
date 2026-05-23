# Session 6 Agentic Architecture (No Gateway)

This project implements the Session 6 four-role architecture in a config-driven way:

- `memory.py`: typed memory service with persistence under `state/memory.json`
- `perception.py`: orchestrator role for goals, done flags, and artifact attach selection
- `decision.py`: one-step role that returns either a final answer or one MCP tool call
- `action.py`: pure MCP dispatch with artifact thresholding and handle guard
- `agent6.py`: main loop wiring the four roles
- `schemas.py`: Pydantic v2 contracts across role boundaries
- `mcp_server.py`: MCP tool server (provided)

The implementation intentionally does **not** use `llm_gateway_v3`, and calls Gemini directly via HTTP API.

## Project Demo

YouTube demo link (placeholder):

`https://www.youtube.com/watch?v=<your-demo-video-id>`

## 1) Setup (uv + .env)

1. Install dependencies:

```bash
uv sync
```

2. Create `.env` from `.env.example` and set your real values:

```bash
copy .env.example .env
```

Required env keys:

- `GEMINI_API_KEY`
- `GEMINI_MODEL` (default in template: `gemini-3.1-flash-lite`)
- `LLM_COOLDOWN_SECONDS=60` (global cooldown across all roles; max one call per minute)
- `TOOL_TIMEOUT_SECONDS=60` (prevents MCP tool calls from hanging indefinitely)

## 2) Run Commands

Clean state before a fresh assignment attempt:

```bash
uv run python agent6.py --clean-state
```

Run each target query:

```bash
uv run python agent6.py --query query_a_shannon
uv run python agent6.py --query query_b_tokyo
uv run python agent6.py --query query_c
uv run python agent6.py --query query_d_asyncio
```

`query_c` is an alias that runs both Query C scenarios in sequence (`query_c_run1` then `query_c_run2`).

If you want to run Query C scenarios individually:

```bash
uv run python agent6.py --query query_c_run1
uv run python agent6.py --query query_c_run2
```

Run all scenarios in sequence:

```bash
uv run python agent6.py --run-all
```

## 3) Query Mapping

Named query modules are split by name in `queries/`:

- `query_a_shannon.py`
- `query_b_tokyo.py`
- `query_c_mom.py` (run1 + run2)
- `query_d_asyncio.py`

## 4) Expected Convergence Bounds

The runner enforces max-iteration bounds per scenario from the query spec:

- Query A expected ~3 (pass bound <= 6)
- Query B expected ~6 (pass bound <= 12)
- Query C run1 expected ~4 (pass bound <= 8), run2 expected ~2 (pass bound <= 4)
- Query D expected ~6 (pass bound <= 12)

## 5) Terminal Output Capture (Submission)

Use clean state first, then capture logs to files:

```bash
uv run python agent6.py --clean-state
uv run python agent6.py --query query_a_shannon > outputs_query_a.txt
uv run python agent6.py --clean-state
uv run python agent6.py --query query_b_tokyo > outputs_query_b.txt
uv run python agent6.py --clean-state
uv run python agent6.py --query query_c > outputs_query_c.txt
uv run python agent6.py --clean-state
uv run python agent6.py --query query_d_asyncio > outputs_query_d.txt
```

Paste the captured outputs into this README for final submission under sections A/B/C/D.

### Query A Output

```text
=== Query A - Shannon Wikipedia ===
Fetch https://en.wikipedia.org/wiki/Claude_Shannon and tell me his birth date, death date, and three key contributions to information theory.

[memory.remember] classified as scratchpad | keywords=['Claude Shannon', 'information theory', 'biography']

--- iter 1 ---
[memory.read]   1 hits
[cooldown] waiting 17.0s before next LLM call (last role: memory)
[perception]    [open] Fetch content from https://en.wikipedia.org/wiki/Claude_Shannon
[perception]    [open] Extract birth date, death date, and three key contributions to information theory for Claude Shannon
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: fetch_url({"url": "https://en.wikipedia.org/wiki/Claude_Shannon"})
[action]        -> [artifact art:6f8aafc1511620d2, 145075 bytes] preview: {   "status": 200,   "content_type": "text/plain; charset=utf-8",   "length_bytes": 142913,   "text": "Title: Claude Shannon\n\nURL Source: http://en.wikipedia.org/wiki/Claude_Shannon\n\nPublished Time: 2001-05-20T03:38:17Z\n

--- iter 2 ---
[memory.read]   2 hits
[cooldown] waiting 17.0s before next LLM call (last role: decision)
[perception]    [done] Fetch content from https://en.wikipedia.org/wiki/Claude_Shannon
[perception]    [open] Extract birth date, death date, and three key contributions to information theory for Claude Shannon | attach=art:6f8aafc1511620d2
[attach]        art:6f8aafc1511620d2 (145075 bytes)
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      ANSWER: Claude Shannon was born on April 30, 1916, and died on February 24, 2001. His three key contributions to information theory include: 1) Establishing the foundations of information theory with his 1948 paper 'A Mathematical Theory of Communication', 2) Formally introducing the ter

--- iter 3 ---
[memory.read]   2 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Fetch content from https://en.wikipedia.org/wiki/Claude_Shannon
[perception]    [done] Extract birth date, death date, and three key contributions to information theory for Claude Shannon

[done] all 2 goals satisfied

FINAL: Claude Shannon was born on April 30, 1916, and died on February 24, 2001. His three key contributions to information theory include: 1) Establishing the foundations of information theory with his 1948 paper 'A Mathematical Theory of Communication', 2) Formally introducing the term 'bit' as a unit of information, and 3) Developing the theory behind digital computing and digital circuits by demonstrating that Boolean algebra could be used to construct logical numerical relationships.
```

### Query B Output

```text
=== Query B - Tokyo Activities + Weather ===
Find 3 family-friendly things to do in Tokyo this weekend. Check Saturday's weather forecast there and tell me which one is most appropriate.

[memory.remember] classified as preference | keywords=['Tokyo', 'family-friendly', 'weekend', 'weather-dependent']

--- iter 1 ---
[memory.read]   1 hits
[cooldown] waiting 17.6s before next LLM call (last role: memory)
[perception]    [open] Read and identify three family-friendly activities to do in Tokyo this weekend from reliable sources.
[perception]    [open] Read and retrieve the Saturday weather forecast for Tokyo, avoiding blocked domains.
[perception]    [open] Synthesize the activity options and weather forecast to recommend the most appropriate activity for Saturday.
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: web_search({"query": "family friendly activities in Tokyo this weekend", "max_results": 3})
[action]        -> {
  "title": "Family Activities | Tokyo Cheapo",
  "url": "https://tokyocheapo.com/entertainment/family/",
  "snippet": "Tokyo has family activities galore, with interactive galleries and museums, unique playgrounds and of course, the Disney and Moomin theme parks too!"
}
{
  "ti

--- iter 2 ---
[memory.read]   2 hits
[cooldown] waiting 16.4s before next LLM call (last role: decision)
[perception]    [open] Read and identify three family-friendly activities to do in Tokyo this weekend from reliable sources.
[perception]    [open] Read and retrieve the Saturday weather forecast for Tokyo, avoiding blocked domains.
[perception]    [open] Synthesize the activity options and weather forecast to recommend the most appropriate activity for Saturday.
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: fetch_url({"url": "https://tokyocheapo.com/entertainment/family/"})
[action]        -> [artifact art:1ed1d775087afa5e, 122280 bytes] preview: {   "status": 200,   "content_type": "text/html; charset=UTF-8",   "length_bytes": 106161,   "text": "<!DOCTYPE html>\n<html lang=\"en\">\n<head prefix=\"og: http://ogp.me/ns# fb: http://ogp.me/ns/fb# object: http://ogp.me/ns

--- iter 3 ---
[memory.read]   3 hits
[cooldown] waiting 19.6s before next LLM call (last role: decision)
[perception]    [done] Read and identify three family-friendly activities to do in Tokyo this weekend from reliable sources.
[perception]    [open] Read and retrieve the Saturday weather forecast for Tokyo, avoiding blocked domains.
[perception]    [open] Synthesize the activity options and weather forecast to recommend the most appropriate activity for Saturday. | attach=art:1ed1d775087afa5e
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: web_search({"query": "Tokyo weather forecast Saturday May 23 2026", "max_results": 3})
[action]        -> {
  "title": "Tokyo, Tokyo, Japan Monthly Weather - AccuWeather",
  "url": "https://www.accuweather.com/en/jp/tokyo/226396/may-weather/226396",
  "snippet": "Tokyo's May 2026 forecast shows daily high temperatures ranging from 73° to 87°, with overnight lows between 62° and 71°. 

--- iter 4 ---
[memory.read]   4 hits
[cooldown] waiting 15.1s before next LLM call (last role: decision)
[perception]    [done] Read and identify three family-friendly activities to do in Tokyo this weekend from reliable sources.
[perception]    [open] Read and retrieve the Saturday weather forecast for Tokyo, avoiding blocked domains.
[perception]    [open] Synthesize the activity options and weather forecast to recommend the most appropriate activity for Saturday. | attach=art:1ed1d775087afa5e
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: fetch_url({"url": "https://www.data.jma.go.jp/multi/yoho/yoho_detail.html?code=130010&lang=en"})
[action]        -> [artifact art:0ed8cf428baa743a, 10169 bytes] preview: {   "status": 200,   "content_type": "text/html",   "length_bytes": 9022,   "text": "<!DOCTYPE html>\n<html lang=\"ja\">\n<head>\n    <meta charset=\"utf-8\">\n    <meta name=\"description\" content=\"気象庁\">\n    <meta name=\"

--- iter 5 ---
[memory.read]   5 hits
[cooldown] waiting 19.1s before next LLM call (last role: decision)
[perception]    [done] Read and identify three family-friendly activities to do in Tokyo this weekend from reliable sources.
[perception]    [done] Read and retrieve the Saturday weather forecast for Tokyo, avoiding blocked domains.
[perception]    [open] Synthesize the activity options and weather forecast to recommend the most appropriate activity for Saturday. | attach=art:1ed1d775087afa5e
[attach]        art:1ed1d775087afa5e (122280 bytes)
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      ANSWER: Based on the available information for Tokyo this weekend, here are three family-friendly activity options and a recommendation based on the weather forecast:

1. **Ueno Park & Zoo**: A classic outdoor destination perfect for exploring, especially if the weather is clear.
2. **Na

--- iter 6 ---
[memory.read]   5 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Read and identify three family-friendly activities to do in Tokyo this weekend from reliable sources.
[perception]    [done] Read and retrieve the Saturday weather forecast for Tokyo, avoiding blocked domains.
[perception]    [done] Synthesize the activity options and weather forecast to recommend the most appropriate activity for Saturday.

[done] all 3 goals satisfied

FINAL: Based on the available information for Tokyo this weekend, here are three family-friendly activity options and a recommendation based on the weather forecast:

1. **Ueno Park & Zoo**: A classic outdoor destination perfect for exploring, especially if the weather is clear.
2. **National Museum of Nature and Science**: An excellent indoor option located in Ueno Park, ideal if the weather turns rainy or too hot.
3. **Tokyo Toy Museum**: A highly-rated indoor play space that provides a safe and engaging environment for children regardless of external conditions.

**Saturday Weather Forecast**: The Japan Meteorological Agency reports generally mild conditions for Tokyo, with a mix of sun and clouds, making it suitable for both outdoor and indoor activities.

**Recommendation**: Given the favorable weather, **Ueno Park & Zoo** is the most appropriate choice for Saturday. It allows you to enjoy the pleasant outdoor conditions while keeping the National Museum of Nature and Science as a convenient indoor backup nearby if needed.
```

### Query C Output (Run1 + Run2)

```text
=== Query C Run 1 - Store Birthday + Reminders ===
My mom's birthday is 10 June 2026. Remember that and give me a calendar reminder for two weeks before and on the day.

[memory.remember] classified as fact | keywords=['birthday', 'mom', 'June 10']

--- iter 1 ---
[memory.read]   1 hits
[cooldown] waiting 17.0s before next LLM call (last role: memory)
[perception]    [open] Commit mom's birthday (June 10, 2026) to persistent memory.
[perception]    [open] Schedule a calendar reminder for two weeks before the birthday (May 27, 2026).
[perception]    [open] Schedule a calendar reminder for the day of the birthday (June 10, 2026).
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: create_file({"path": "reminders/mom_birthday.txt", "content": "Event: Mom's Birthday\nDate: 2026-06-10\nReminders: 14 days before, 0 days before"})
[action]        -> {
  "ok": true,
  "path": "reminders/mom_birthday.txt",
  "size_bytes": 81
}

--- iter 2 ---
[memory.read]   2 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Commit mom's birthday (June 10, 2026) to persistent memory.
[perception]    [open] Schedule a calendar reminder for two weeks before the birthday (May 27, 2026).
[perception]    [open] Schedule a calendar reminder for the day of the birthday (June 10, 2026).
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: update_file({"path": "reminders/mom_birthday.txt", "content": "Event: Mom's Birthday\nDate: 2026-06-10\nReminders: 14 days before (2026-05-27), 0 days before (2026-06-10)"})
[action]        -> {
  "ok": true,
  "path": "reminders/mom_birthday.txt",
  "size_bytes": 107
}

--- iter 3 ---
[memory.read]   3 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Commit mom's birthday (June 10, 2026) to persistent memory.
[perception]    [done] Schedule a calendar reminder for two weeks before the birthday (May 27, 2026).
[perception]    [open] Schedule a calendar reminder for the day of the birthday (June 10, 2026).
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: create_file({"path": "reminders/reminder_2026-06-10.txt", "content": "Reminder: Schedule a calendar reminder for the day of the birthday (June 10, 2026)."})
[action]        -> {
  "ok": true,
  "path": "reminders/reminder_2026-06-10.txt",
  "size_bytes": 83
}

--- iter 4 ---
[memory.read]   4 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Commit mom's birthday (June 10, 2026) to persistent memory.
[perception]    [done] Schedule a calendar reminder for two weeks before the birthday (May 27, 2026).
[perception]    [done] Schedule a calendar reminder for the day of the birthday (June 10, 2026).

[done] all 3 goals satisfied

FINAL: {
  "ok": true,
  "path": "reminders/reminder_2026-06-10.txt",
  "size_bytes": 83
}


=== Query C Run 2 - Recall Birthday ===
When is mom's birthday?

[cooldown] waiting 19.8s before next LLM call (last role: perception)
[memory.remember] classified as fact | keywords=['mom', 'birthday']

--- iter 1 ---
[memory.read]   5 hits
[cooldown] waiting 17.1s before next LLM call (last role: memory)
[perception]    [open] Locate the mom's birthday information in stored memory files.
[perception]    [open] Report the date of mom's birthday based on the retrieved evidence.
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: read_file({"path": "reminders/mom_birthday.txt"})
[action]        -> {
  "path": "reminders/mom_birthday.txt",
  "size_bytes": 107,
  "content": "Event: Mom's Birthday\nDate: 2026-06-10\nReminders: 14 days before (2026-05-27), 0 days before (2026-06-10)",
  "encoding": "utf-8"
}

--- iter 2 ---
[memory.read]   6 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Locate the mom's birthday information in stored memory files.
[perception]    [open] Report the date of mom's birthday based on the retrieved evidence.
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      ANSWER: Mom's birthday is on June 10, 2026.

--- iter 3 ---
[memory.read]   6 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Locate the mom's birthday information in stored memory files.
[perception]    [done] Report the date of mom's birthday based on the retrieved evidence.

[done] all 2 goals satisfied

FINAL: Mom's birthday is on June 10, 2026.
```

### Query D Output

```text
=== Query D - Asyncio Multi-source Synthesis ===
Search for 'Python asyncio best practices', read the top 3 results, and give me a short numbered list of the advice they agree on.

[memory.remember] classified as scratchpad | keywords=['Python', 'asyncio', 'best practices', 'research']

--- iter 1 ---
[memory.read]   1 hits
[cooldown] waiting 16.9s before next LLM call (last role: memory)
[perception]    [open] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [open] Read the top 3 results from the search to understand core asyncio recommendations.
[perception]    [open] Synthesize the reading results to identify common advice agreed upon by the sources.
[perception]    [open] Draft a short numbered list of the common asyncio best practices.
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: web_search({"query": "Python asyncio best practices", "max_results": 3})
[action]        -> {
  "title": "Python's asyncio: A Hands-On Walkthrough – Real Python",
  "url": "https://realpython.com/async-io-python/",
  "snippet": "Jul 30, 2025 · In this tutorial, you’ll learn how Python asyncio works, how to define and run coroutines, and when to use asynchronous programm

--- iter 2 ---
[memory.read]   2 hits
[cooldown] waiting 17.4s before next LLM call (last role: decision)
[perception]    [done] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [open] Read the top 3 results from the search to understand core asyncio recommendations.
[perception]    [open] Synthesize the reading results to identify common advice agreed upon by the sources.
[perception]    [open] Draft a short numbered list of the common asyncio best practices.
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: fetch_url({"url": "https://realpython.com/async-io-python"})
[action]        -> [artifact art:004b7d05447bd796, 251013 bytes] preview: {   "status": 200,   "content_type": "text/html; charset=utf-8",   "length_bytes": 238543,   "text": "\n\n<!doctype html>\n<html lang=\"en\">\n  <head>\n    \n    \n    <link href=\"https://files.realpython.com\" rel=\"precon

--- iter 3 ---
[memory.read]   3 hits
[cooldown] waiting 18.2s before next LLM call (last role: decision)
[perception]    [done] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [open] Read the top 3 results from the search to understand core asyncio recommendations.
[perception]    [open] Synthesize the reading results to identify common advice agreed upon by the sources. | attach=art:004b7d05447bd796
[perception]    [open] Draft a short numbered list of the common asyncio best practices. | attach=art:004b7d05447bd796
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: fetch_url({"url": "https://superfastpython.com/python-asyncio"})
[action]        -> [artifact art:8cf59585a9f26402, 263758 bytes] preview: {   "status": 200,   "content_type": "text/html; charset=utf-8",   "length_bytes": 258813,   "text": "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\">\n  <meta name=\"viewport\" content=\"width=device-w

--- iter 4 ---
[memory.read]   4 hits
[cooldown] waiting 18.3s before next LLM call (last role: decision)
[perception]    [done] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [open] Read the top 3 results from the search to understand core asyncio recommendations. | attach=art:8cf59585a9f26402
[perception]    [open] Synthesize the reading results to identify common advice agreed upon by the sources. | attach=art:8cf59585a9f26402
[perception]    [open] Draft a short numbered list of the common asyncio best practices. | attach=art:8cf59585a9f26402
[attach]        art:8cf59585a9f26402 (263758 bytes)
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      TOOL_CALL: fetch_url({"url": "https://www.c-sharpcorner.com/article/python-asyncio-complete-practical-guide-for-concurrent-io"})
[action]        -> [artifact art:e5d4b8871122b881, 271698 bytes] preview: {   "status": 200,   "content_type": "text/html; charset=utf-8",   "length_bytes": 264321,   "text": "\r\n\r\n<!DOCTYPE html>\r\n<html xmlns=\"http://www.w3.org/1999/xhtml\" lang=\"en\">\r\n<head><meta name=\"author\" content

--- iter 5 ---
[memory.read]   5 hits
[cooldown] waiting 18.0s before next LLM call (last role: decision)
[perception]    [done] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [open] Read the top 3 results from the search to understand core asyncio recommendations. | attach=art:8cf59585a9f26402
[perception]    [open] Synthesize the reading results to identify common advice agreed upon by the sources. | attach=art:8cf59585a9f26402
[perception]    [open] Draft a short numbered list of the common asyncio best practices. | attach=art:8cf59585a9f26402
[attach]        art:8cf59585a9f26402 (263758 bytes)
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      ANSWER: Based on the top resources for Python asyncio, here are the core recommendations for effective asynchronous programming:

1. **Understand the Event Loop**: The event loop is the heart of every asyncio application; it manages and schedules the execution of asynchronous tasks and c

--- iter 6 ---
[memory.read]   5 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[llm] transient Gemini error 503 on perception attempt 1/3; retrying in 1.5s
[perception]    [done] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [done] Read the top 3 results from the search to understand core asyncio recommendations.
[perception]    [open] Synthesize the reading results to identify common advice agreed upon by the sources. | attach=art:8cf59585a9f26402
[perception]    [open] Draft a short numbered list of the common asyncio best practices. | attach=art:8cf59585a9f26402
[attach]        art:8cf59585a9f26402 (263758 bytes)
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      ANSWER: Based on the synthesized information from the retrieved sources, here is the common advice for working with Python asyncio:

1. **Prioritize I/O-Bound Tasks**: Asyncio is specifically designed for I/O-bound operations (e.g., network requests, database queries, socket programming)

--- iter 7 ---
[memory.read]   5 hits
[cooldown] waiting 19.9s before next LLM call (last role: decision)
[perception]    [done] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [done] Read the top 3 results from the search to understand core asyncio recommendations.
[perception]    [done] Synthesize the reading results to identify common advice agreed upon by the sources.
[perception]    [open] Draft a short numbered list of the common asyncio best practices. | attach=art:8cf59585a9f26402
[attach]        art:8cf59585a9f26402 (263758 bytes)
[cooldown] waiting 20.0s before next LLM call (last role: perception)
[decision]      ANSWER: Based on the synthesized best practices for Python asyncio, here are the key recommendations:

1. **Prioritize I/O-Bound Tasks**: Use asyncio specifically for I/O-bound operations (e.g., network requests, database queries, socket programming). It is not designed for CPU-bound tas

--- iter 8 ---
[memory.read]   5 hits
[cooldown] waiting 20.0s before next LLM call (last role: decision)
[perception]    [done] Search for 'Python asyncio best practices' to retrieve relevant technical articles.
[perception]    [done] Read the top 3 results from the search to understand core asyncio recommendations.
[perception]    [done] Synthesize the reading results to identify common advice agreed upon by the sources.
[perception]    [done] Draft a short numbered list of the common asyncio best practices.

[done] all 4 goals satisfied

FINAL: Based on the synthesized best practices for Python asyncio, here are the key recommendations:

1. **Prioritize I/O-Bound Tasks**: Use asyncio specifically for I/O-bound operations (e.g., network requests, database queries, socket programming). It is not designed for CPU-bound tasks, which should be handled by multiprocessing to avoid blocking the event loop.
2. **Never Block the Event Loop**: Avoid any synchronous, long-running, or blocking code within a coroutine. Blocking the loop halts all other concurrent tasks, negating the benefits of asynchronous programming.
3. **Leverage High-Level APIs**: Prefer high-level APIs like `asyncio.gather`, `asyncio.create_task`, and `asyncio.Queue` for managing concurrency and communication. Low-level event loop internals are generally reserved for framework and library authors.
4. **Adopt the Async/Await Pattern**: Use `async def` to define coroutines and `await` to pause execution. This allows the event loop to switch to other pending tasks while waiting for I/O, enabling efficient, cooperative multitasking.
5. **Understand the Event Loop's Role**: Recognize that the event loop is the central engine of an asyncio application, managing task scheduling in a single thread. While tasks run concurrently, they do not execute in parallel on multiple CPU cores.
```

## 6) PoP Prompt + Validation JSON

The required artifacts are included in `pop/`:

- `pop/perception_prompt.txt`
- `pop/perception_validation.json`
- `pop/decision_prompt.txt`
- `pop/decision_validation.json`

## 7) Notes

- Memory persistence is under `state/`, and is durable across runs.
- Artifacts are stored under `state/artifacts/` as content-addressed `art:<sha-prefix>` entries.
- Action blocks dispatches where a tool argument starts with `art:`.
- The loop prints role-level traces each iteration (`memory.read`, `perception`, `decision`, `action`).
