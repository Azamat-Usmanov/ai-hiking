"""Fail CI on malformed or unsourced route records."""

from urllib.parse import urlparse

from app.catalog import all_routes


def main() -> None:
    routes = all_routes()
    assert len(routes) == 20, f"expected 20 routes, got {len(routes)}"
    assert len({route["id"] for route in routes}) == len(routes)
    for route in routes:
        assert route["name"] and route["start"]
        assert route["duration_minutes"] > 0 and route["distance_km"] > 0
        assert route["ascent_m"] >= 0
        assert route["difficulty"] in {"easy", "moderate", "hard"}
        assert -90 <= route["lat"] <= 90 and -180 <= route["lon"] <= 180
        assert urlparse(route["source_url"]).hostname == "www.grenoble-tourisme.com"
        if route.get("photo"):
            photo = route["photo"]
            assert all(photo.get(field) for field in ("path", "caption", "author", "license", "source_url", "license_url"))
    print(f"Catalogue valid: {len(routes)} sourced routes")


if __name__ == "__main__":
    main()
