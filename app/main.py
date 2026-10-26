from pathlib import Path
import logging
import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from app.planner import OLLAMA_MODEL, OLLAMA_URL, build_plan

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Тропа · AI Hiking Planner", docs_url=None, redoc_url=None)
logger = logging.getLogger("ai_hiking")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class PlanRequest(BaseModel):
    query: str = Field(min_length=5, max_length=500)
    date: str | None = None


@app.get("/")
async def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/presentation")
async def presentation():
    return FileResponse(ROOT / "presentation" / "index.html")


@app.get("/architecture.png")
async def architecture_image():
    return FileResponse(ROOT / "docs" / "architecture.png")


@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            models = [m["name"] for m in response.json().get("models", [])]
        revision_file = ROOT / ".deploy-commit"
        revision = revision_file.read_text().strip() if revision_file.exists() else "development"
        return {"status": "ok" if any(OLLAMA_MODEL in name for name in models) else "model_missing", "model": OLLAMA_MODEL, "revision": revision}
    except httpx.HTTPError:
        return {"status": "model_unavailable", "model": OLLAMA_MODEL}


@app.post("/api/plan")
async def plan(request: PlanRequest):
    try:
        return await build_plan(request.query.strip(), request.date)
    except (httpx.HTTPError, ValidationError, RuntimeError, ValueError) as exc:
        logger.exception("Planner request failed")
        raise HTTPException(status_code=503, detail="Планировщик сейчас не смог завершить запрос. Попробуйте ещё раз.") from exc
