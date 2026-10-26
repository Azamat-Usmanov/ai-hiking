"""Rebuild the hand-curated catalogue extension from Grenoble Alpes Tourisme pages.

The script is deliberately explicit: metadata is reviewed here, while the start
coordinates are read from the publisher's JSON-LD rather than guessed.
"""

import json
import re
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/routes.json"

# id, Russian name, publisher title, area, start, km, minutes, climb, level,
# features, route type, seasonal window, Grenoble Alpes Tourisme URL.
ADDITIONS = [
    ("mont-rachais", "Гора Раше от перевала Ванс", "Le Mont Rachais, un sommet aux versants contrastés, depuis le col de Vence", "Chartreuse", "Col de Vence", 7, 180, 400, "moderate", ["лес", "панорама"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/le-mont-rachais-un-sommet-aux-versants-contrastes-depuis-le-col-de-vence-776672/"),
    ("emeindras", "Круговой маршрут Эмендра", "Boucle des Emeindras", "Chartreuse", "Place du Sappey-en-Chartreuse", 9, 180, 400, "moderate", ["лес", "альпийские луга", "панорама"], "круговой", ["05-01", "11-30"], "https://www.grenoble-tourisme.com/fr/catalogue/detail/boucle-des-emeindras-5308858/"),
    ("saint-eynard", "Гребни Сен-Эйнара", "Crêtes du St Eynard", "Chartreuse", "Le Sappey-en-Chartreuse", 8, 150, 300, "moderate", ["лес", "панорама", "форт"], "круговой", ["05-01", "11-30"], "https://www.grenoble-tourisme.com/fr/catalogue/detail/cretes-du-st-eynard-5308887/"),
    ("ecoutoux", "Вершина Экуту", "L'Ecoutoux", "Chartreuse", "Le Sappey-en-Chartreuse", 8, 150, 410, "moderate", ["лес", "панорама"], "туда-обратно", ["05-01", "11-30"], "https://www.grenoble-tourisme.com/fr/catalogue/detail/l-ecoutoux-5308901/"),
    ("pre-du-playnet", "Луг Пре-дю-Плейне", "Le Pré du Playnet", "Vercors", "Mairie de Miribel-Lanchâtre", 7, 180, 510, "hard", ["лес", "панорама", "обрывы"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/le-pre-du-playnet-4894447/"),
    ("vignasses", "Тропа Виньяс", "Circuit pédestre des Vignasses", "Uriage", "Maison des Arts, Saint-Martin-d'Uriage", 4, 105, 300, "easy", ["лес", "луга", "ручей"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/circuit-pedestre-des-vignasses-1h45-depart-bourg-st-martin-d-uriage-5153386/"),
    ("remparts-uriage", "Крепостные стены Юриажа", "Circuit pédestre des remparts", "Uriage", "Office de Tourisme d'Uriage", 3, 90, 130, "easy", ["панорама", "история", "парк"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/circuit-pedestre-des-remparts-1h30-depart-office-de-tourisme-5162729/"),
    ("cote-charvet", "Бельведер Кот-Шарве", "La côte Charvet un belvédère fabuleux", "Chartreuse", "Collavière, Mont-Saint-Martin", 6, 150, 300, "moderate", ["лес", "панорама"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/la-cote-charvet-un-belvedere-fabuleux-5588374/"),
    ("cirque-prevourey", "Цирк Превурей и водопад", "Circuit pédestre : Le Cirque de Prévourey", "Taillefer", "Office de Tourisme de l'Alpe-du-Grand-Serre", 4, 150, 300, "moderate", ["лес", "водопад", "панорама"], "круговой", ["05-01", "11-30"], "https://www.grenoble-tourisme.com/fr/catalogue/detail/circuit-pedestre-le-cirque-de-prevourey-375906/"),
    ("traversee-vouillants", "Пересечение леса Вуйян", "Traversée des Vouillants", "Vercors", "Parc de la Poya, Fontaine", 6, 150, 400, "moderate", ["лес", "панорама"], "линейный", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/traversee-des-vouillants-5755752/"),
    ("ferme-froussard", "Ферма Фруссар", "Du désert de Jean-Jacques Rousseau à la ferme Froussard", "Vercors", "Désert Jean-Jacques Rousseau", 5, 120, 250, "easy", ["лес", "ферма"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/du-desert-de-jean-jacques-rousseau-a-la-ferme-froussard-5753936/"),
    ("belvedere-vizille", "Бельведер Визиля", "Le belvédère de Vizille", "Vizille", "Place du Château, Vizille", 6, 120, 310, "easy", ["лес", "панорама"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/le-belvedere-de-vizille-270239/"),
    ("petit-sentier-prairie", "Малая тропа через луга", "Le petit sentier dans la prairie", "Grenoble Sud", "Mairie de Saint-Georges-de-Commiers", 3, 120, 160, "easy", ["лес", "луга", "природа"], "круговой", None, "https://www.grenoble-tourisme.com/fr/catalogue/detail/le-petit-sentier-dans-la-prairie-6420547/"),
]


def coordinates(url: str) -> tuple[float, float]:
    html = urlopen(Request(url, headers={"User-Agent": "AI-Hiking-Student-Project/1.0"}), timeout=20).read().decode("utf-8")
    match = re.search(r'"latitude"\s*:\s*([0-9.]+)\s*,\s*"longitude"\s*:\s*([0-9.]+)', html)
    if not match:
        raise ValueError(f"Publisher page has no coordinates: {url}")
    return float(match[1]), float(match[2])


def main() -> None:
    routes = json.loads(SOURCE.read_text())
    base = routes[:7]
    if len(base) != 7:
        raise ValueError("Expected original seven records at the beginning of the catalogue")
    for route_id, name, name_fr, area, start, distance, minutes, ascent, difficulty, features, route_type, window, url in ADDITIONS:
        lat, lon = coordinates(url)
        route = {"id": route_id, "name": name, "name_fr": name_fr, "area": area,
                 "start": start, "lat": lat, "lon": lon, "distance_km": distance,
                 "duration_minutes": minutes, "ascent_m": ascent, "difficulty": difficulty,
                 "lake": False, "features": features, "type": route_type,
                 "season": "опубликованный сезон 1 мая — 30 ноября; при отсутствии снега" if window else "круглый год при подходящей погоде",
                 "source_url": url}
        if window:
            route["open_month_day"] = window
        base.append(route)
    if len(base) != 20 or len({route["id"] for route in base}) != 20:
        raise ValueError("Expected 20 unique routes")
    SOURCE.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
