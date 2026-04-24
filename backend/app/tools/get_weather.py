"""
Weather Fetcher Tool
Fetches weather data using browser geolocation or city name.
"""

import aiohttp
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class WeatherFetcher:
    """Fetch weather data for a given location."""
    
    def __init__(self, gemini_client):
        self.client = gemini_client
        self.cache = {}
        self.cache_timestamp = 0

    @staticmethod
    def _map_weather_code(code: Optional[int]) -> Dict[str, str]:
        mapping = {
            0: {"condition": "Clear", "icon": "☀️"},
            1: {"condition": "Mainly clear", "icon": "🌤️"},
            2: {"condition": "Partly cloudy", "icon": "⛅"},
            3: {"condition": "Overcast", "icon": "☁️"},
            45: {"condition": "Fog", "icon": "🌫️"},
            48: {"condition": "Rime fog", "icon": "🌫️"},
            51: {"condition": "Light drizzle", "icon": "🌦️"},
            53: {"condition": "Drizzle", "icon": "🌦️"},
            55: {"condition": "Dense drizzle", "icon": "🌧️"},
            61: {"condition": "Slight rain", "icon": "🌦️"},
            63: {"condition": "Rain", "icon": "🌧️"},
            65: {"condition": "Heavy rain", "icon": "🌧️"},
            71: {"condition": "Snow fall", "icon": "❄️"},
            80: {"condition": "Rain showers", "icon": "🌦️"},
            81: {"condition": "Rain showers", "icon": "🌧️"},
            82: {"condition": "Heavy rain showers", "icon": "⛈️"},
            95: {"condition": "Thunderstorm", "icon": "⛈️"},
        }
        return mapping.get(code, {"condition": "Unavailable", "icon": "🌤️"})

    async def _fetch_weather_payload(self, latitude: float, longitude: float) -> Dict[str, Any]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 3,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20) as response:
                response.raise_for_status()
                return await response.json()

    async def _geocode_city(self, city: str, country: str) -> Dict[str, Any]:
        params = {
            "name": city,
            "count": 1,
            "language": "en",
            "format": "json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get("https://geocoding-api.open-meteo.com/v1/search", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()

        results = payload.get("results") or []
        if not results:
            raise ValueError(f"Could not resolve weather location for {city}, {country}")
        return results[0]

    async def _reverse_geocode(self, latitude: float, longitude: float) -> Dict[str, Any]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "language": "en",
            "format": "json",
            "count": 1,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get("https://geocoding-api.open-meteo.com/v1/reverse", params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()

        results = payload.get("results") or []
        return results[0] if results else {}

    def _build_weather_response(self, location: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        current = payload.get("current", {})
        daily = payload.get("daily", {})
        weather_meta = self._map_weather_code(current.get("weather_code"))
        forecast = []
        for index, date_value in enumerate(daily.get("time", [])[:3]):
            day_meta = self._map_weather_code((daily.get("weather_code") or [None])[index])
            forecast.append({
                "date": date_value,
                "condition": day_meta["condition"],
                "icon": day_meta["icon"],
                "temperature_max": (daily.get("temperature_2m_max") or [None])[index],
                "temperature_min": (daily.get("temperature_2m_min") or [None])[index],
            })

        return {
            "status": "success",
            "location": {
                "city": location.get("city") or location.get("name"),
                "country": location.get("country") or location.get("country_name") or "Unknown",
            },
            "current": {
                "temperature": current.get("temperature_2m"),
                "condition": weather_meta["condition"],
                "humidity": current.get("relative_humidity_2m"),
                "wind_speed": current.get("wind_speed_10m"),
                "icon": weather_meta["icon"],
            },
            "forecast": forecast,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    async def get_weather(self, city: str = "", country: str = "USA") -> Dict[str, Any]:
        """
        Get weather data for a city.
        
        Args:
            city: City name (required; returns error if empty)
            country: Country name
            
        Returns:
            Dictionary with weather information
        """
        if not city or not city.strip():
            logger.warning("get_weather called without a city; returning error instead of defaulting")
            return {
                "status": "error",
                "error": "No city provided. Please supply a city name or coordinates.",
                "location": {}
            }
        logger.info(f"Fetching weather for {city}, {country}...")
        
        try:
            location = await self._geocode_city(city, country)
            payload = await self._fetch_weather_payload(location["latitude"], location["longitude"])
            weather_data = self._build_weather_response(
                {
                    "city": location.get("name", city),
                    "country": location.get("country", country),
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                },
                payload,
            )
            logger.info(f"Retrieved weather for {city}")
            return weather_data
            
        except Exception as e:
            logger.error(f"Error fetching weather: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "location": {"city": city, "country": country}
            }
    
    async def get_weather_by_coordinates(self, latitude: float, longitude: float, city_label: Optional[str] = None) -> Dict[str, Any]:
        """
        Get weather by geolocation coordinates.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            city_label: Optional human-readable city/location label
            
        Returns:
            Dictionary with weather information
        """
        logger.info(f"Fetching weather for coordinates ({latitude}, {longitude})...")
        
        try:
            payload = await self._fetch_weather_payload(latitude, longitude)
            reverse_geo = {}
            try:
                reverse_geo = await self._reverse_geocode(latitude, longitude)
            except Exception as reverse_exc:
                logger.warning("Reverse geocoding failed for (%s, %s): %s", latitude, longitude, reverse_exc)

            resolved_city = city_label
            if not resolved_city:
                resolved_city = (
                    reverse_geo.get("name")
                    or reverse_geo.get("admin2")
                    or reverse_geo.get("admin1")
                    or payload.get("timezone")
                    or "Current Location"
                )

            resolved_country = (
                reverse_geo.get("country")
                or reverse_geo.get("country_code")
                or "Current Location"
            )

            weather_data = self._build_weather_response(
                {
                    "city": resolved_city,
                    "country": resolved_country,
                    "latitude": latitude,
                    "longitude": longitude,
                },
                payload,
            )
            logger.info("Retrieved weather for coordinates")
            return weather_data
            
        except Exception as e:
            logger.error(f"Error fetching weather by coordinates: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "coordinates": {"latitude": latitude, "longitude": longitude}
            }


def create_weather_fetcher(gemini_client):
    """Factory function to create WeatherFetcher instance."""
    return WeatherFetcher(gemini_client)
