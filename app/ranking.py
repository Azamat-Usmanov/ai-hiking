"""Explainable route relevance score (0–100) used after MCP retrieval."""

DIFFICULTY = {"easy": 0, "moderate": 1, "hard": 2}


def score_route(route: dict, intent: dict, weather: dict | None = None) -> dict:
    """Higher is better; the component weights sum to 100 points.

    A missing forecast receives a neutral weather score. This is a relevance
    score, not a safety prediction or a probability of enjoying the hike.
    """
    weather = weather or {}
    target = (intent.get("max_hours") or 0) * 60
    duration = 35.0 if not target else 35 * max(0.0, 1 - abs(route["duration_minutes"] - target) / max(target, 60))
    requested_level = intent.get("difficulty", "any")
    difficulty = 25.0 if requested_level == "any" or DIFFICULTY[route["difficulty"]] <= DIFFICULTY[requested_level] else 0.0
    lake = 20.0 if not intent.get("lake") or route["lake"] else 0.0
    requested_features = set(intent.get("features") or [])
    features = 10.0 if not requested_features else 10 * len(requested_features.intersection(route["features"])) / len(requested_features)
    if weather.get("status") == "ok":
        rain = weather.get("precipitation_probability_percent") or 0
        wind = weather.get("wind_max_kmh") or 0
        snow = weather.get("snowfall_cm") or 0
        weather_points = max(0.0, 10 - rain / 20 - max(0, wind - 20) / 10 - (5 if snow > 0 else 0))
    else:
        weather_points = 5.0
    parts = {"duration": round(duration, 1), "difficulty": difficulty, "lake": lake,
             "features": round(features, 1), "weather": round(weather_points, 1)}
    return {"score": round(sum(parts.values())), "components": parts}
