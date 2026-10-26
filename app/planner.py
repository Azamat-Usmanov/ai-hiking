"""Two LLM passes with real MCP calls in between."""

import asyncio
import json
import os
import re
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
    min_hours: float = Field(default=0, ge=0, le=24)
    min_hours_exclusive: bool = False
    difficulty: Literal["easy", "moderate", "hard", "any"]
    lake: bool
    target_ascent_m: int = Field(default=0, ge=0, le=3000)


class Decision(BaseModel):
    route_ids: list[str]


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
MODEL_LOCK = asyncio.Semaphore(1)


async def llm_json(system: str, user: str, schema: dict, max_tokens: int = 600) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0)) as client:
        for attempt in range(2):
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": system + (" Ответь одним коротким JSON без повторов." if attempt else "")},
                        {"role": "user", "content": user},
                    ],
                    "format": schema,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "repeat_penalty": 1.15 if attempt else 1.0,
                                "num_ctx": 4096, "num_predict": max_tokens if not attempt else min(max_tokens, 240)},
                },
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                continue
        raise RuntimeError("Ollama returned invalid JSON twice")


def requested_features(query: str) -> list[str]:
    """Keep feature extraction out of the model's unbounded JSON array."""
    patterns = {"лес": r"лес|рощ", "панорама": r"панорам|видов", "водопад": r"водопад",
                "луга": r"луг|лугов|альпийск.*пастбищ", "история": r"истори|крепост|форт"}
    lowered = query.casefold()
    return [name for name, pattern in patterns.items() if re.search(pattern, lowered)]


def explicit_ascent(query: str) -> int | None:
    """Recognize a stated elevation gain if the small LLM leaves it empty."""
    lowered = query.casefold()
    pattern = r"(?:набор\w*\s+высот\w*|подъ[её]м\w*|высот\w*)\s*(?:около\s*|примерно\s*)?(\d{2,4})\s*(?:м\b|метр)"
    match = re.search(pattern, lowered)
    return int(match[1]) if match else None


def explicit_duration_bounds(query: str) -> dict[str, float | bool]:
    """Keep numeric lower and upper limits distinct, including strict 'more than'."""
    bounds: dict[str, float | bool] = {}
    pattern = r"(\d+(?:[.,]\d+)?)\s*(минут\w*|мин\b|час\w*|ч\b)"
    for match in re.finditer(pattern, query.casefold()):
        amount = float(match[1].replace(",", "."))
        hours = amount / 60 if match[2].startswith("мин") else amount
        prefix = query.casefold()[max(0, match.start() - 35):match.start()]
        if re.search(r"(?:не\s+(?:больше|дольше|свыше|более)|до|максимум)\s*$", prefix):
            bounds["max_hours"] = hours
        elif re.search(r"(?:больше|дольше|свыше|более|от|минимум|не\s+менее|не\s+меньше)\s*$", prefix):
            bounds["min_hours"] = hours
            bounds["min_hours_exclusive"] = bool(re.search(r"(?:больше|дольше|свыше|более)\s*$", prefix))
        else:
            bounds["max_hours"] = hours
    return bounds


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
        try:
            parsed = await llm_json(
                "Ты извлекаешь параметры пешего похода из запроса. Верни только JSON по схеме. "
                "'Не слишком сложный' означает moderate. 'Легкий' означает easy. "
                "Озеро и пруд — разные объекты. Не добавляй отсутствующих пожеланий. "
                "Если время не указано, max_hours=0 и min_hours=0; если сложность не указана, difficulty=any. "
                "'Больше 2 часов' означает min_hours=2, min_hours_exclusive=true, max_hours=0. "
                "'Не менее 2 часов' означает min_hours=2, min_hours_exclusive=false. "
                "'До 2 часов' означает max_hours=2, min_hours=0. "
                "Если пользователь говорит о наборе высоты или подъёме в метрах, запиши число в target_ascent_m; "
                "иначе target_ascent_m=0. Высота не означает длительность. "
                "Дату не извлекай: она задаётся отдельно в интерфейсе.",
                f"Сегодня {today}. Запрос: {query}", Intent.model_json_schema(), 220,
            )
            parse_fallback = False
        except RuntimeError:
            parsed = {}
            parse_fallback = True
        if not isinstance(parsed, dict):
            parsed = {}
            parse_fallback = True
        bounds_from_text = explicit_duration_bounds(query)
        if "min_hours" in bounds_from_text:
            parsed["min_hours"] = bounds_from_text["min_hours"]
            parsed["min_hours_exclusive"] = bounds_from_text["min_hours_exclusive"]
            if "max_hours" not in bounds_from_text:
                parsed["max_hours"] = 0
        if "max_hours" in bounds_from_text:
            parsed["max_hours"] = bounds_from_text["max_hours"]
            if "min_hours" not in bounds_from_text:
                parsed["min_hours"] = 0
                parsed["min_hours_exclusive"] = False
        if not isinstance(parsed.get("max_hours"), (int, float)) or not 0 <= parsed["max_hours"] <= 24:
            parsed["max_hours"] = 0
        if not isinstance(parsed.get("min_hours"), (int, float)) or not 0 <= parsed["min_hours"] <= 24:
            parsed["min_hours"] = 0
        if not isinstance(parsed.get("min_hours_exclusive"), bool):
            parsed["min_hours_exclusive"] = False
        lowered = query.casefold()
        if re.search(r"не\s+слишком\s+сложн|умерен", lowered):
            fallback_difficulty = "moderate"
        elif re.search(r"л[её]гк|прост|начинающ", lowered):
            fallback_difficulty = "easy"
        elif re.search(r"сложн|трудн", lowered):
            fallback_difficulty = "hard"
        else:
            fallback_difficulty = "any"
        if parsed.get("difficulty") not in {"easy", "moderate", "hard", "any"}:
            parsed["difficulty"] = fallback_difficulty
        if not isinstance(parsed.get("lake"), bool):
            parsed["lake"] = bool(re.search(r"озер", lowered))
        if not isinstance(parsed.get("target_ascent_m"), int) or not 0 <= parsed["target_ascent_m"] <= 3000:
            parsed["target_ascent_m"] = 0
        intent = Intent.model_validate(parsed)
        if fallback_difficulty == "any":
            intent.difficulty = "any"
        ascent_from_text = explicit_ascent(query)
        if ascent_from_text is not None and ascent_from_text <= 3000:
            intent.target_ascent_m = ascent_from_text
        intent_data = {**intent.model_dump(), "features": requested_features(query)}
        trip_date = supplied_date or today
        try:
            date.fromisoformat(trip_date)
        except ValueError:
            trip_date = today
        trace.append({"stage": "LLM 1", "action": "Разбор запроса" + (" (резервный разбор после сбоя JSON)" if parse_fallback else ""), "result": intent_data})

        server = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], env=os.environ.copy())
        async with Client(server) as mcp:
            args = {"max_hours": intent.max_hours or None, "min_hours": intent.min_hours or None,
                    "min_hours_exclusive": intent.min_hours_exclusive,
                    "difficulty": intent.difficulty, "lake": intent.lake,
                    "target_ascent_m": intent.target_ascent_m or None, "trip_date": trip_date}
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

        ranked = {r["id"]: score_route(r, intent_data, forecast.get("routes", {}).get(r["id"])) for r in candidates}
        candidates.sort(key=lambda r: (-ranked[r["id"]]["score"], r["id"]))
        trace.append({"stage": "Ranking", "action": "Оценка соответствия 0–100", "result": ranked})
        payload = {
            "request": query, "date": trip_date, "intent": intent_data,
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
        try:
            decision_data = await llm_json(
                "Ты выбираешь и ранжируешь до трёх пеших маршрутов. Верни только route_ids из candidates, "
                "лучший первым. Учитывай relevance_score, близость длительности и набора высоты к запросу, сложность, озеро и погоду. "
                "Не выбирай сложный маршрут как легкий. Если точных вариантов нет, предложи ближайшие альтернативы.",
                json.dumps(payload, ensure_ascii=False), schema, 180,
            )
            decision = Decision.model_validate(decision_data)
            decision_fallback = False
        except (RuntimeError, ValidationError):
            decision = Decision(route_ids=[r["id"] for r in candidates[:3]])
            decision_fallback = True
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
            if intent.target_ascent_m:
                reason += f" Набор высоты — {route['ascent_m']} м (запрошено около {intent.target_ascent_m} м)."
            tradeoff = "Отличие от запроса: " + ", ".join(route["mismatches"]) + "." if route["mismatches"] else ""
            route_cards.append({**route, "reason": reason, "tradeoff": tradeoff,
                                "relevance_score": ranked[route_id]["score"],
                                "score_components": ranked[route_id]["components"],
                                "weather": forecast.get("routes", {}).get(route_id, {"status": forecast["status"]})})
        if not route_cards:
            route_cards = [{**r, "reason": "Маршрут выбран по баллу соответствия после некорректного ответа модели.",
                            "tradeoff": "Отличие от запроса: " + ", ".join(r["mismatches"]) + "." if r["mismatches"] else "",
                            "relevance_score": ranked[r["id"]]["score"],
                            "score_components": ranked[r["id"]]["components"],
                            "weather": forecast.get("routes", {}).get(r["id"], {"status": forecast["status"]})}
                           for r in candidates[:3]]
            decision_fallback = True
        route_cards.sort(key=lambda r: (-r["relevance_score"], r["id"]))
        trace.append({"stage": "LLM 2", "action": "Выбор и ранжирование" + (" (резервный выбор по баллам)" if decision_fallback else ""),
                      "result": [r["id"] for r in route_cards]})
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
