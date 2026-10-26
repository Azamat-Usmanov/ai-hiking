import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "routes.json"


def all_routes() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def route_by_id(route_id: str) -> dict | None:
    return next((route for route in all_routes() if route["id"] == route_id), None)
