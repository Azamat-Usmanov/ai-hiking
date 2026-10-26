"""Offline NDCG@3 on a small, manually labeled route-query set."""

import json
import math
from pathlib import Path

from app.catalog import route_by_id
from app.ranking import score_route


def dcg(grades: list[int], k: int = 3) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades[:k]))


def main() -> None:
    cases = json.loads((Path(__file__).parent / "ranking_cases.json").read_text())
    rows = []
    for case in cases:
        grades = case["relevance"]
        ranking = sorted(grades, key=lambda route_id: (-score_route(route_by_id(route_id), case["intent"])["score"], route_id))
        ideal = sorted(grades.values(), reverse=True)
        value = dcg([grades[route_id] for route_id in ranking]) / dcg(ideal)
        rows.append({"query": case["query"], "ndcg_at_3": round(value, 3), "ranking": ranking[:3],
                     "grades_at_3": [grades[route_id] for route_id in ranking[:3]]})
    result = {"metric": "NDCG@3", "mean": round(sum(row["ndcg_at_3"] for row in rows) / len(rows), 3),
              "cases": rows, "notes": "Offline, manually graded candidates (0–3), neutral weather; does not measure LLM parsing or live forecast."}
    (Path(__file__).parent / "ranking_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
