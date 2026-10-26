"""Run a small real end-to-end evaluation against a deployed instance."""

import argparse
import json
import time
from pathlib import Path

import httpx
from app.limits import DISPLAY_LIMIT, MCP_CANDIDATE_LIMIT

ROOT = Path(__file__).resolve().parent.parent
CATALOG = {r["id"]: r for r in json.loads((ROOT / "data" / "routes.json").read_text())}

CASES = [
    {"id": "lake_4h_moderate", "query": "Найди поход рядом с Греноблем на 4 часа, с озером, не слишком сложный", "date": "2026-10-27", "max_minutes": 240, "max_difficulty": 1, "lake": True},
    {"id": "easy_2h", "query": "Легкая прогулка к озеру у Гренобля до 2 часов", "date": "2026-10-27", "max_minutes": 120, "max_difficulty": 0, "lake": True},
    {"id": "no_exact", "query": "Найди легкий поход с озером до 30 минут у Гренобля", "date": "2026-10-27", "expect_no_exact": True},
    {"id": "forecast_horizon", "query": "Подбери умеренный маршрут у озера близ Гренобля до 4 часов", "date": "2026-11-20", "expect_no_forecast": True},
    {"id": "ascent_400", "query": "найди маршрут с высотой 400 метров", "date": "2026-10-27", "target_ascent_m": 400},
    {"id": "longer_than_2h", "query": "найди маршруты длительностью больше 2 часов", "date": "2026-10-27", "min_minutes_exclusive": 120, "expect_exact": True},
    {"id": "broad_six", "query": "Подбери любые пешие маршруты рядом с Греноблем", "date": "2026-10-27", "expect_candidates": MCP_CANDIDATE_LIMIT, "expect_routes": DISPLAY_LIMIT},
]


def check(case, response):
    problems = []
    if response.get("status") != "ok":
        return [f"unexpected status: {response.get('status')}"]
    routes = response.get("routes", [])
    if not routes:
        problems.append("empty route list")
    if len(routes) > DISPLAY_LIMIT:
        problems.append("too many displayed routes")
    if case.get("expect_routes") and len(routes) != case["expect_routes"]:
        problems.append(f"expected {case['expect_routes']} displayed routes, got {len(routes)}")
    if case.get("expect_candidates"):
        search = next((x for x in response.get("trace", []) if x.get("tool") == "search_routes"), {})
        if len(search.get("result", {}).get("exact", [])) != case["expect_candidates"]:
            problems.append("MCP did not return eight candidates")
        weather = next((x for x in response.get("trace", []) if x.get("tool") == "get_weather"), {})
        if len(weather.get("result", {}).get("routes", {})) != case["expect_candidates"]:
            problems.append("weather did not cover eight candidates")
    if case.get("expect_no_exact") and response.get("exact_match"):
        problems.append("claimed exact match for impossible request")
    if case.get("expect_exact") and not response.get("exact_match"):
        problems.append("missed existing exact matches")
    if case.get("target_ascent_m"):
        trace = next((x for x in response.get("trace", []) if x.get("stage") == "LLM 1"), {})
        if trace.get("result", {}).get("target_ascent_m") != case["target_ascent_m"]:
            problems.append("elevation gain not extracted")
        if routes and abs(routes[0]["ascent_m"] - case["target_ascent_m"]) > 50:
            problems.append("top route elevation gain too far from target")
    if case.get("min_minutes_exclusive"):
        trace = next((x for x in response.get("trace", []) if x.get("stage") == "LLM 1"), {})
        parsed = trace.get("result", {})
        if parsed.get("min_hours") != case["min_minutes_exclusive"] / 60 or not parsed.get("min_hours_exclusive"):
            problems.append("strict lower duration bound not extracted")
    order = {"easy": 0, "moderate": 1, "hard": 2}
    for route in routes:
        original = CATALOG.get(route.get("id"))
        if not original:
            problems.append("invented route id")
            continue
        for key in ["name", "duration_minutes", "distance_km", "ascent_m", "difficulty", "source_url"]:
            if route.get(key) != original[key]:
                problems.append(f"changed catalogue field {key} for {route['id']}")
        if response.get("exact_match"):
            if case.get("min_minutes_exclusive") and route["duration_minutes"] <= case["min_minutes_exclusive"]:
                problems.append(f"duration does not exceed request: {route['id']}")
            if case.get("max_minutes") and route["duration_minutes"] > case["max_minutes"]:
                problems.append(f"duration exceeds request: {route['id']}")
            if case.get("max_difficulty") is not None and order[route["difficulty"]] > case["max_difficulty"]:
                problems.append(f"difficulty exceeds request: {route['id']}")
            if case.get("lake") and not route["lake"]:
                problems.append(f"no lake: {route['id']}")
        if case.get("expect_no_forecast") and route.get("weather", {}).get("status") != "outside_forecast":
            problems.append(f"forecast fabricated outside horizon: {route['id']}")
    tools = [x.get("tool") for x in response.get("trace", []) if x.get("stage") == "MCP"]
    if tools != ["search_routes", "get_weather"]:
        problems.append(f"wrong MCP trace: {tools}")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default=str(ROOT / "eval" / "results.json"))
    args = parser.parse_args()
    output = []
    with httpx.Client(timeout=300) as client:
        for case in CASES:
            started = time.monotonic()
            try:
                response = client.post(f"{args.base_url.rstrip('/')}/api/plan", json={"query": case["query"], "date": case["date"]})
                if response.status_code != 200:
                    output.append({"id": case["id"], "status": "error", "http_status": response.status_code, "seconds": round(time.monotonic()-started, 1)})
                    continue
                data = response.json()
                problems = check(case, data)
                output.append({"id": case["id"], "status": "passed" if not problems else "failed", "seconds": round(time.monotonic()-started, 1), "route_ids": [r["id"] for r in data.get("routes", [])], "exact_match": data.get("exact_match"), "weather_status": [r.get("weather", {}).get("status") for r in data.get("routes", [])], "problems": problems})
            except Exception as exc:
                output.append({"id": case["id"], "status": "error", "seconds": round(time.monotonic()-started, 1), "error": str(exc)[:200]})
            print(output[-1], flush=True)
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
