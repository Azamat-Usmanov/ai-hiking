"""Two LLM passes with real MCP calls in between."""

import asyncio
import json
import os
import sys
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from mcp import Client, StdioServerParameters
from pydantic import BaseModel, Field, ValidationError
from app.ranking import score_route


class Intent(BaseModel):
    max_hours: float = Field(ge=0, le=24)
    difficulty: Literal["easy", "moderate", "hard", "any"]
    lake: bool
    features: list[Literal["лес", "панорама", "водопад", "луга", "история"]] = Field(default_factory=list)


class Decision(BaseModel):
    route_ids: list[str]


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
MODEL_LOCK = asyncio.Semaphore(1)


async def llm_json(system: str, user: str, schema: dict, max_tokens: int = 600) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0)) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "format": schema,
                "stream": False,
                "think": False,
                "options": {"temperature": 0, "num_ctx": 4096, "num_predict": max_tokens},
            },
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned invalid JSON: {content[:300]!r}") from exc


def mcp_payload(result) -> dict:
    if getattr(result, "is_error", False):
        raise RuntimeError("MCP tool returned an error")
    structured = getattr(result, "structured_content", None)
    if structured:
        return structured.get("result", structured)
    for part in result.content:
        if getattr(part, "type", "") == "text":
            return json.loads(part.text)
    raise RuntimeError("MCP tool returned no usable data")


async def build_plan(query: str, supplied_date: str | None = None) -> dict:
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    trace = []
    async with MODEL_LOCK:
        parsed = await llm_json(
            "Ты извлекаешь параметры пешего похода из запроса. Верни только JSON по схеме. "
            "'Не слишком сложный' означает moderate. 'Легкий' означает easy. "
            "Озеро и пруд — разные объекты. Не добавляй отсутствующих пожеланий. "
            "Если время не указано, max_hours=0. Дату не извлекай: она задаётся отдельно в интерфейсе. "
            "Извлекай только явно запрошенные признаки из списка features; не додумывай их.",
            f"Сегодня {today}. Запрос: {query}", Intent.model_json_schema(), 600,
        )
        intent = Intent.model_validate(parsed)
        trip_date = supplied_date or today
        try:
            date.fromisoformat(trip_date)
        except ValueError:
            trip_date = today
        trace.append({"stage": "LLM 1", "action": "Разбор запроса", "result": intent.model_dump()})

        server = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], env=os.environ.copy())
        async with Client(server) as mcp:
            args = {"max_hours": intent.max_hours or None, "difficulty": intent.difficulty, "lake": intent.lake, "trip_date": trip_date}
            found = mcp_payload(await mcp.call_tool("search_routes", args))
            trace.append({"stage": "MCP", "tool": "search_routes", "arguments": args, "result": {
                "exact": [{"id": r["id"], "duration_minutes": r["duration_minutes"], "difficulty": r["difficulty"]} for r in found["exact"]],
                "alternatives": [{"id": r["id"], "mismatches": r["mismatches"]} for r in found["alternatives"]],
            }})
            candidates = found["exact"][:5] if found["exact"] else found["alternatives"][:3]
            if not candidates:
                return {"status": "no_routes", "message": "Маршруты по запросу не найдены.", "routes": [], "trace": trace}
            ids = [r["id"] for r in candidates]
            weather_args = {"route_ids": ids, "trip_date": trip_date}
            forecast = mcp_payload(await mcp.call_tool("get_weather", weather_args))
            trace.append({"stage": "MCP", "tool": "get_weather", "arguments": weather_args, "result": forecast})

        ranked = {r["id"]: score_route(r, intent.model_dump(), forecast.get("routes", {}).get(r["id"])) for r in candidates}
        candidates.sort(key=lambda r: (-ranked[r["id"]]["score"], r["id"]))
        trace.append({"stage": "Ranking", "action": "Оценка соответствия 0–100", "result": ranked})
        payload = {
            "request": query, "date": trip_date, "intent": intent.model_dump(),
            "exact_match_available": bool(found["exact"]),
            "candidates": [
                {"id": r["id"], "duration_minutes": r["duration_minutes"],
                 "ascent_m": r["ascent_m"], "difficulty": r["difficulty"],
                 "lake": r["lake"], "mismatches": r["mismatches"],
                 "features": r["features"], "weather": forecast.get("routes", {}).get(r["id"], {}),
                 "relevance_score": ranked[r["id"]]["score"]}
                for r in candidates
            ],
        }
        schema = Decision.model_json_schema()
        schema["properties"]["route_ids"]["items"]["enum"] = ids
        schema["properties"]["route_ids"]["minItems"] = 1
        schema["properties"]["route_ids"]["maxItems"] = 3
        decision_data = await llm_json(
            "Ты выбираешь и ранжируешь до трёх пеших маршрутов. Верни только route_ids из candidates, "
            "лучший первым. Учитывай relevance_score, близость длительности к запросу, сложность, озеро и погоду. "
            "Не выбирай сложный маршрут как легкий. Если точных вариантов нет, предложи ближайшие альтернативы.",
            json.dumps(payload, ensure_ascii=False), schema, 180,
        )
        decision = Decision.model_validate(decision_data)
        allowed = {r["id"]: r for r in candidates}
        route_cards = []
        for route_id in decision.route_ids[:3]:
            if route_id not in allowed or any(r["id"] == route_id for r in route_cards):
                continue
            route = allowed[route_id]
            duration = route["duration_minutes"]
            hours, minutes = divmod(duration, 60)
            duration_text = f"{hours} ч {minutes:02d} мин"
            level = {"easy": "лёгкий", "moderate": "умеренный", "hard": "сложный"}[route["difficulty"]]
            features = "есть озеро" if route["lake"] else "озера на маршруте нет"
            reason = f"По данным источника, это {level} маршрут на {duration_text}; {features}."
            tradeoff = "Отличие от запроса: " + ", ".join(route["mismatches"]) + "." if route["mismatches"] else ""
            route_cards.append({**route, "reason": reason, "tradeoff": tradeoff,
                                "relevance_score": ranked[route_id]["score"],
                                "score_components": ranked[route_id]["components"],
                                "weather": forecast.get("routes", {}).get(route_id, {"status": forecast["status"]})})
        if not route_cards:
            raise RuntimeError("LLM returned no valid route IDs")
        route_cards.sort(key=lambda r: (-r["relevance_score"], r["id"]))
        trace.append({"stage": "LLM 2", "action": "Выбор и ранжирование", "result": [r["id"] for r in route_cards]})
        message = ("Нашёл маршруты, которые соответствуют указанным ограничениям." if found["exact"]
                   else "Точного совпадения нет. Ниже ближайшие варианты и их отличия от запроса.")
        if forecast["status"] == "outside_forecast":
            message += " Дата за пределами доступного прогноза; погоду нужно проверить позже."
        elif forecast["status"] == "unavailable":
            message += " Прогноз сейчас недоступен; проверьте погоду перед выходом."
        return {
            "status": "ok", "message": message, "date": trip_date,
            "exact_match": bool(found["exact"]), "routes": route_cards,
            "trace": trace, "model": OLLAMA_MODEL,
        }
