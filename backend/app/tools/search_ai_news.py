"""
AI News Search Tool
Searches for latest AI news using Gemini's built-in Google Search grounding.
"""

import aiohttp
import html
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AINewsSearcher:
    """Search for latest AI news using Gemini's grounding."""
    
    def __init__(self, gemini_client):
        self.client = gemini_client
        self.cache = {}
        self.cache_timestamp = 0

    @staticmethod
    def _strip_html(text: str) -> str:
        clean = re.sub(r"<[^>]+>", "", text or "")
        return html.unescape(clean).strip()
    
    async def search_ai_news(self, query: str = "latest AI news", limit: int = 5) -> Dict[str, Any]:
        """
        Search for AI news using Gemini with Google Search grounding.
        
        Args:
            query: Search query for AI news
            limit: Number of articles to return
            
        Returns:
            Dictionary with news articles
        """
        logger.info(f"Searching for AI news: {query}")
        
        try:
            encoded_query = urllib.parse.quote_plus(query)
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url, timeout=20) as response:
                    response.raise_for_status()
                    rss_text = await response.text()

            root = ET.fromstring(rss_text)
            articles = []
            for item in root.findall(".//item")[:limit]:
                title = self._strip_html(item.findtext("title", default="AI News"))
                url = item.findtext("link", default="")
                date = item.findtext("pubDate", default="")
                source = item.findtext("source", default="Google News")
                description = self._strip_html(item.findtext("description", default=""))
                summary = description or f"Latest update about {query}: {title}"
                articles.append({
                    "title": title,
                    "source": source,
                    "summary": summary,
                    "url": url,
                    "date": date,
                })

            news_data = {
                "status": "success",
                "query": query,
                "articles": articles,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"Found news articles for: {query}")
            return news_data
            
        except Exception as e:
            logger.error(f"Error searching AI news: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "articles": []
            }
    
    async def get_trending_ai_news(self) -> Dict[str, Any]:
        """Get trending AI news of the day."""
        logger.info("Fetching trending AI news...")
        return await self.search_ai_news("trending AI breakthroughs today", limit=5)
    
    async def get_ai_research_news(self) -> Dict[str, Any]:
        """Get latest AI research announcements."""
        logger.info("Fetching AI research news...")
        return await self.search_ai_news("latest AI research papers and announcements", limit=5)


def create_ai_news_searcher(gemini_client):
    """Factory function to create AINewsSearcher instance."""
    return AINewsSearcher(gemini_client)
