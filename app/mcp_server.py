"""MCP data boundary: route catalogue and live weather."""

from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import httpx
from mcp.server import MCPServer

from app.catalog import all_routes, route_by_id

mcp = MCPServer("Grenoble Hiking Data")

DIFFICULTY = {"easy": 0, "moderate": 1, "hard": 2}


@mcp.tool()
def search_routes(max_hours: float | None = None, difficulty: str = "any", lake: bool = False, trip_date: str | None = None) -> dict:
    """Find sourced hiking routes around Grenoble. Return exact matches and clearly marked alternatives.

    Args:
        max_hours: Maximum walking time in hours, or null if unspecified.
        difficulty: Highest allowed difficulty: easy, moderate, hard, or any.
        lake: Whether the route must reach a lake (a pond does not count).
        trip_date: Local date in YYYY-MM-DD for checking published seasonal windows.
    """
    max_minutes = max_hours * 60 if max_hours else None
    ceiling = DIFFICULTY.get(difficulty, 2)
    exact, alternatives = [], []
    for route in all_routes():
        problems = []
        if trip_date and route.get("open_month_day"):
            try:
                month_day = date.fromisoformat(trip_date).strftime("%m-%d")
                first, last = route["open_month_day"]
                if not first <= month_day <= last:
                    problems.append("вне опубликованного периода маршрута")
            except ValueError:
                pass
        if max_minutes is not None and route["duration_minutes"] > max_minutes:
            problems.append("дольше заданного времени")
        if difficulty != "any" and DIFFICULTY[route["difficulty"]] > ceiling:
            problems.append("сложнее заданного уровня")
        if lake and not route["lake"]:
            problems.append("нет озера")
        item = {**route, "mismatches": problems}
        if problems:
            alternatives.append(item)
        else:
            exact.append(item)
    exact.sort(key=lambda r: (abs(r["duration_minutes"] - (max_minutes or r["duration_minutes"])), r["ascent_m"]))
    alternatives.sort(key=lambda r: (len(r["mismatches"]), abs(r["duration_minutes"] - (max_minutes or r["duration_minutes"]))))
    return {"exact": exact[:5], "alternatives": alternatives[:3], "total_catalogue": len(all_routes())}


@mcp.tool()
def get_weather(route_ids: list[str], trip_date: str) -> dict:
    """Get the Open-Meteo daily forecast for route starting points, or an explicit unavailable status.

    Args:
        route_ids: IDs returned by search_routes, maximum five.
        trip_date: Local date in YYYY-MM-DD format.
    """
    try:
        requested = date.fromisoformat(trip_date)
    except ValueError:
        return {"status": "invalid_date", "routes": {}}
    days_ahead = (requested - datetime.now(ZoneInfo("Europe/Paris")).date()).days
    if days_ahead < 0 or days_ahead > 15:
        return {"status": "outside_forecast", "routes": {}, "forecast_horizon_days": 16}
    results = {}
    with httpx.Client(timeout=12.0, headers={"User-Agent": "ai-hiking-planner/1.0"}) as client:
        for route_id in route_ids[:5]:
            route = route_by_id(route_id)
            if not route:
                continue
            try:
                response = client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": route["lat"], "longitude": route["lon"],
                        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum,wind_speed_10m_max,weather_code",
                        "timezone": "Europe/Paris", "forecast_days": 16,
                    },
                )
                response.raise_for_status()
                daily = response.json()["daily"]
                index = daily["time"].index(trip_date)
                results[route_id] = {
                    "status": "ok", "date": trip_date, "location": "точка старта маршрута",
                    "temperature_max_c": daily["temperature_2m_max"][index],
                    "temperature_min_c": daily["temperature_2m_min"][index],
                    "precipitation_probability_percent": daily["precipitation_probability_max"][index],
                    "precipitation_mm": daily["precipitation_sum"][index],
                    "snowfall_cm": daily["snowfall_sum"][index],
                    "wind_max_kmh": daily["wind_speed_10m_max"][index],
                    "weather_code": daily["weather_code"][index],
                }
            except (httpx.HTTPError, KeyError, ValueError, IndexError, json.JSONDecodeError):
                results[route_id] = {"status": "unavailable", "date": trip_date}
    return {"status": "ok" if any(x["status"] == "ok" for x in results.values()) else "unavailable", "routes": results, "source": "https://open-meteo.com/"}


@mcp.tool()
def get_route_details(route_id: str) -> dict:
    """Return one sourced route by ID, including its original listing URL."""
    return route_by_id(route_id) or {"error": "route_not_found"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
