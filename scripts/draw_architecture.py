"""Regenerate docs/architecture.png: pip install pillow; python scripts/draw_architecture.py"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "architecture.png"
OUT.parent.mkdir(exist_ok=True)
W, H = 2400, 650
im = Image.new("RGB", (W, H), "#f3f1e9")
d = ImageDraw.Draw(im)
font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
if not Path(font_path).exists():
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
title = ImageFont.truetype(font_path, 55)
body = ImageFont.truetype(font_path, 31)
small = ImageFont.truetype(font_path, 23)
d.text((95, 57), "Архитектура AI Hiking Planner", fill="#17332f", font=title)
d.text((95, 131), "Один пользовательский запрос · две стадии LLM · реальные вызовы MCP", fill="#63736e", font=small)

nodes = [
    ("01", "Пользователь", "Свободный запрос"),
    ("02", "Web + FastAPI", "Ввод и валидация"),
    ("03", "LLM #1", "Извлечь условия"),
    ("04", "MCP-клиент", "Вызвать инструменты"),
    ("05", "MCP-сервер", "Маршруты + погода"),
    ("06", "LLM #2", "Ранжировать"),
    ("07", "Результат", "Карточки и источники"),
]
x0, y, width, gap = 95, 235, 285, 42
for i, (num, name, detail) in enumerate(nodes):
    x = x0 + i * (width + gap)
    fill = "#17332f" if i in (2, 4, 5) else "#ffffff"
    fg = "#ffffff" if i in (2, 4, 5) else "#17332f"
    d.rounded_rectangle((x, y, x + width, y + 245), radius=23, fill=fill, outline="#cfd8cc", width=2)
    d.text((x + 25, y + 22), num, fill="#a8d785" if i in (2, 4, 5) else "#749363", font=small)
    d.text((x + 25, y + 91), name, fill=fg, font=body)
    d.text((x + 25, y + 167), detail, fill="#c6d8cb" if i in (2, 4, 5) else "#65766c", font=small)
    if i < len(nodes) - 1:
        a = x + width + 7
        d.line((a, y + 122, a + gap - 14, y + 122), fill="#6d9668", width=5)
        d.polygon([(a + gap - 13, y + 122), (a + gap - 27, y + 113), (a + gap - 27, y + 131)], fill="#6d9668")

d.text((95, 545), "MCP tools: search_routes · get_weather · get_route_details", fill="#496357", font=small)
d.text((95, 584), "Источники: проверенный каталог Grenoble Alpes Tourisme + прогноз Open-Meteo", fill="#6e7f74", font=small)
im.save(OUT, optimize=True)
print(OUT)
