"""
MCP server for EAGV3 Session 6.

Nine tools, stdio transport:
    web_search, fetch_url, currency_convert,
    read_file, list_dir, create_file, update_file, edit_file

web_search:  Tavily primary, DuckDuckGo fallback. Hard-capped at 5 results.
fetch_url:   crawl4ai only — clean markdown via headless Chromium.
Usage for tavily and duckduckgo is logged to ./usage.json with monthly
rollover and a soft cap of 950/1000 on Tavily.

File tools are sandboxed under ./sandbox/. Run:  python mcp_server.py
"""

from __future__ import annotations

import json
import os
import re
import threading
import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from ddgs import DDGS
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

MAX_SEARCH_RESULTS = 5  # hard cap — Tavily prices per result
DEFAULT_BLOCKED_SEARCH_DOMAINS = ("medium.com",)

load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("eagv3-s6-server")

SANDBOX = Path(__file__).parent / "sandbox"
SANDBOX.mkdir(exist_ok=True)

USAGE_PATH = Path(__file__).parent / "usage.json"
MONTHLY_CAP = 950  # leave 50/mo headroom on Tavily
_usage_lock = threading.Lock()


def _safe(path: str) -> Path:
    p = (SANDBOX / path).resolve()
    base = SANDBOX.resolve()
    if p != base and base not in p.parents:
        raise ValueError(f"Path '{path}' escapes the sandbox")
    return p


def _empty_usage(month: str) -> dict:
    return {
        "month": month,
        "tavily": {"count": 0, "errors": 0},
        "duckduckgo": {"count": 0, "errors": 0},
    }


def _load_usage() -> dict:
    month = datetime.now().strftime("%Y-%m")
    if not USAGE_PATH.exists():
        return _empty_usage(month)
    try:
        data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_usage(month)
    if data.get("month") != month:
        return _empty_usage(month)
    for k in ("tavily", "duckduckgo"):
        data.setdefault(k, {"count": 0, "errors": 0})
    return data


def _save_usage(data: dict) -> None:
    USAGE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _bump(provider: str, field: str = "count") -> None:
    with _usage_lock:
        data = _load_usage()
        data[provider][field] = data[provider].get(field, 0) + 1
        _save_usage(data)


def _under_cap(provider: str) -> bool:
    return _load_usage()[provider]["count"] < MONTHLY_CAP


def _search_blocked_domains() -> set[str]:
    raw = os.environ.get("SEARCH_BLOCKED_DOMAINS", ",".join(DEFAULT_BLOCKED_SEARCH_DOMAINS))
    domains: set[str] = set()
    for token in raw.split(","):
        domain = token.strip().lower().lstrip(".")
        if domain:
            domains.add(domain)
    return domains


def _is_blocked_search_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower().split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return True

    for domain in _search_blocked_domains():
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def _filter_search_results(results: list[dict], max_results: int) -> list[dict]:
    filtered: list[dict] = []
    seen: set[str] = set()

    for row in results:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip()
        if not url:
            continue
        if _is_blocked_search_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)

        filtered.append(
            {
                "title": str(row.get("title", "")),
                "url": url,
                "snippet": str(row.get("snippet", "")),
            }
        )
        if len(filtered) >= max_results:
            break

    return filtered


def _tavily_search(query: str, max_results: int) -> list[dict]:
    from tavily import TavilyClient

    client = TavilyClient(os.environ["TAVILY_API_KEY"])
    resp = client.search(query=query, max_results=max_results, search_depth="advanced")
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in resp.get("results", [])
    ]


def _ddg_search(query: str, max_results: int) -> list[dict]:
    hits: list[dict] = []
    with DDGS() as ddgs:
        for backend in ("auto", "html", "lite"):
            try:
                hits = list(ddgs.text(query, max_results=max_results, backend=backend))
            except Exception:
                hits = []
            if hits:
                break
    return [
        {
            "title": h.get("title", ""),
            "url": h.get("href", ""),
            "snippet": h.get("body", ""),
        }
        for h in hits
    ]


async def _crawl4ai_fetch(url: str, timeout: int) -> dict:
    from crawl4ai import AsyncWebCrawler

    async def _run() -> dict:
        # crawl4ai uses Rich which writes via its own captured stdout reference, so
        # contextlib.redirect_stdout doesn't catch it. Redirect at the file-descriptor
        # level — crawl4ai's banner / [FETCH] / [SCRAPE] markers would otherwise
        # corrupt the MCP stdio JSON-RPC stream.
        saved_fd = os.dup(1)
        os.dup2(2, 1)
        try:
            async with AsyncWebCrawler(verbose=False) as crawler:
                r = await crawler.arun(url=url)
        finally:
            os.dup2(saved_fd, 1)
            os.close(saved_fd)

        # r.markdown is a str subclass (StringCompatibleMarkdown) that Pydantic
        # serializes as {} because its real field is private. Pull the raw string
        # out and force a plain str so FastMCP serializes correctly.
        md = r.markdown
        raw = (
            getattr(md, "raw_markdown", None)
            or getattr(md, "fit_markdown", None)
            or md
            or r.cleaned_html
            or r.html
            or ""
        )
        text = str(raw)
        return {
            "status": int(getattr(r, "status_code", None) or 200),
            "content_type": "text/markdown",
            "length_bytes": len(text.encode("utf-8")),
            "text": text,
        }
    return await asyncio.wait_for(_run(), timeout=max(1, timeout))


async def _http_fetch(url: str, timeout: int) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(timeout=max(1, timeout), follow_redirects=True, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        text = r.text
    return {
        "status": int(r.status_code),
        "content_type": r.headers.get("content-type", "text/html"),
        "length_bytes": len(text.encode("utf-8")),
        "text": text,
    }


def _jina_mirror_url(url: str) -> str:
    normalized = url.strip()
    if normalized.startswith("https://"):
        normalized = "http://" + normalized[len("https://"):]
    return f"https://r.jina.ai/{normalized}"


def _mirror_has_upstream_error(text: str) -> tuple[bool, int | None]:
    lowered = text.lower()
    match = re.search(r"warning:\s*target url returned error\s*(\d{3})", lowered)
    if match:
        try:
            return True, int(match.group(1))
        except ValueError:
            return True, None

    if "access denied" in lowered and "url source:" in lowered:
        return True, 403

    return False, None


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web (Tavily primary, DDG fallback). Hard-capped at 5 results. Example: web_search("python asyncio tutorial", 3)."""
    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))
    provider_fetch_count = min(MAX_SEARCH_RESULTS, max_results + 2)

    if os.environ.get("TAVILY_API_KEY") and _under_cap("tavily"):
        try:
            raw_results = _tavily_search(query, provider_fetch_count)
            _bump("tavily")
            results = _filter_search_results(
                raw_results,
                max_results,
            )
            if results:
                return results
        except Exception:
            _bump("tavily", "errors")

    results = _filter_search_results(
        _ddg_search(query, provider_fetch_count),
        max_results,
    )
    _bump("duckduckgo")
    return results


@mcp.tool()
async def fetch_url(url: str, timeout: int = 20) -> dict:
    """Fetch clean markdown from a URL via crawl4ai (headless Chromium). Example: fetch_url("https://example.com")."""
    use_crawl4ai = os.environ.get("FETCH_USE_CRAWL4AI", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not use_crawl4ai:
        try:
            return await _http_fetch(url, timeout)
        except Exception as exc:
            try:
                mirror = _jina_mirror_url(url)
                out = await _http_fetch(mirror, timeout)
                text = str(out.get("text", ""))
                has_upstream_error, source_status = _mirror_has_upstream_error(text)
                if has_upstream_error:
                    return {
                        "status": 0,
                        "content_type": out.get("content_type", "text/plain"),
                        "length_bytes": int(out.get("length_bytes", 0) or 0),
                        "text": text,
                        "warning": "source URL appears blocked or errored; mirror snapshot is not valid source content",
                        "source_url": mirror,
                        "source_status": source_status,
                    }

                out["warning"] = "direct fetch blocked; returning mirror content via r.jina.ai"
                out["source_url"] = mirror
                return out
            except Exception:
                pass
            return {
                "status": 0,
                "content_type": "text/plain",
                "length_bytes": 0,
                "text": f"[fetch_error] {exc}",
            }

    try:
        return await _crawl4ai_fetch(url, timeout)
    except (TimeoutError, asyncio.TimeoutError):
        # Fallback to a basic HTTP fetch so the agent loop can continue.
        out = await _http_fetch(url, timeout)
        out["warning"] = "crawl4ai timeout; returning raw HTML fallback"
        return out
    except Exception as exc:
        return {
            "status": 0,
            "content_type": "text/plain",
            "length_bytes": 0,
            "text": f"[fetch_error] {exc}",
        }


#@mcp.tool()
def get_time(timezone: str = "UTC") -> dict:
    """Current time in a named IANA timezone. Example: get_time("Asia/Kolkata")."""
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    offset = now.utcoffset()
    offset_hours = offset.total_seconds() / 3600 if offset else 0.0
    return {
        "iso": now.isoformat(),
        "human": now.strftime("%A, %d %B %Y %H:%M:%S %Z"),
        "timezone": timezone,
        "offset_hours": offset_hours,
    }


@mcp.tool()
def currency_convert(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert money between ISO-3 currencies via frankfurter.dev. Example: currency_convert(100, "USD", "INR")."""
    f = from_currency.upper()
    t = to_currency.upper()
    url = f"https://api.frankfurter.dev/v1/latest?amount={amount}&base={f}&symbols={t}"
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    converted = data["rates"][t]
    return {
        "amount": amount,
        "from": f,
        "to": t,
        "rate": converted / amount if amount else 0.0,
        "converted": converted,
        "date": data["date"],
        "source": "frankfurter.dev",
    }


@mcp.tool()
def read_file(path: str) -> dict:
    """Read a UTF-8 text file from the sandbox. Example: read_file("notes.txt")."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    return {
        "path": path,
        "size_bytes": p.stat().st_size,
        "content": text,
        "encoding": "utf-8",
    }


@mcp.tool()
def list_dir(path: str = ".") -> list[dict]:
    """List a directory inside the sandbox. Example: list_dir(".")."""
    p = _safe(path)
    out = []
    for child in sorted(p.iterdir()):
        is_dir = child.is_dir()
        out.append({
            "name": child.name,
            "type": "dir" if is_dir else "file",
            "size_bytes": 0 if is_dir else child.stat().st_size,
        })
    return out


@mcp.tool()
def create_file(path: str, content: str) -> dict:
    """Create a new file in the sandbox; errors if it exists. Example: create_file("hello.txt", "hi")."""
    p = _safe(path)
    if p.exists():
        raise ValueError(f"File '{path}' already exists")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def update_file(path: str, content: str) -> dict:
    """Overwrite an existing sandbox file. Example: update_file("hello.txt", "new body")."""
    p = _safe(path)
    if not p.exists():
        raise ValueError(f"File '{path}' does not exist")
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def edit_file(path: str, find: str, replace: str, replace_all: bool = False) -> dict:
    """Find-and-replace inside a sandbox file. Example: edit_file("hello.txt", "foo", "bar")."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(find)
    if count == 0:
        raise ValueError(f"'{find}' not found in '{path}'")
    if count > 1 and not replace_all:
        raise ValueError(
            f"'{find}' occurs {count} times in '{path}'; pass replace_all=True"
        )
    new_text = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
    p.write_text(new_text, encoding="utf-8")
    replacements = count if replace_all else 1
    return {
        "ok": True,
        "path": path,
        "replacements": replacements,
        "size_bytes": p.stat().st_size,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
