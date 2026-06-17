"""Tests for Microsoft Australia Building Footprints cache provider."""

from __future__ import annotations

import json

from openwind_au.microsoft_footprints import (
    MICROSOFT_FOOTPRINT_SOURCE,
    query_microsoft_building_footprints,
)


def feature(feature_id: str, lon: float, lat: float) -> dict:
    ring = [
        [lon - 0.00005, lat - 0.00005],
        [lon + 0.00005, lat - 0.00005],
        [lon + 0.00005, lat + 0.00005],
        [lon - 0.00005, lat + 0.00005],
        [lon - 0.00005, lat - 0.00005],
    ]
    return {
        "type": "Feature",
        "properties": {"id": feature_id},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def test_microsoft_provider_reads_cache_hit_and_clips_to_radius(tmp_path) -> None:
    cache = tmp_path / "microsoft"
    cache.mkdir()
    tile = cache / "-34_151.geojson"
    tile.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    feature("inside", 151.21, -33.86),
                    feature("outside", 151.30, -33.86),
                ],
            }
        ),
        encoding="utf-8",
    )

    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=cache,
        allow_download=False,
    )

    assert result.source_status == "available"
    assert result.cache_status == "hit"
    assert len(result.footprints) == 1
    assert result.footprints[0]["source_id"] == "ms-au-inside"
    assert result.footprints[0]["footprint_source"] == MICROSOFT_FOOTPRINT_SOURCE


def test_microsoft_provider_reports_cache_miss(tmp_path) -> None:
    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=tmp_path / "missing-cache",
        allow_download=False,
    )

    assert result.footprints == []
    assert result.source_status == "unavailable"
    assert result.cache_status == "miss"
    assert "cache not found" in result.warnings[0]


def test_microsoft_provider_reads_geojsonl_cache(tmp_path) -> None:
    cache = tmp_path / "microsoft"
    tiles = cache / "tiles"
    tiles.mkdir(parents=True)
    tile = tiles / "-34_151.geojsonl"
    tile.write_text(json.dumps(feature("line", 151.21, -33.86)) + "\n", encoding="utf-8")

    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=cache,
        allow_download=False,
    )

    assert len(result.footprints) == 1
    assert result.footprints[0]["source_id"] == "ms-au-line"


def test_microsoft_provider_downloads_required_index_tile(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "microsoft"
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/-34_151.geojsonl",
                        "file": "tiles/-34_151.geojsonl",
                    },
                    "-33_151": {
                        "url": "https://example.test/-33_151.geojsonl",
                        "file": "tiles/-33_151.geojsonl",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    requested_urls: list[str] = []

    class FakeResponse:
        content = (json.dumps(feature("downloaded", 151.21, -33.86)) + "\n").encode()

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: int):
        requested_urls.append(url)
        return FakeResponse()

    monkeypatch.setenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", str(index))
    monkeypatch.setattr("openwind_au.microsoft_footprints.requests.get", fake_get)

    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=cache,
        allow_download=True,
    )

    assert requested_urls == ["https://example.test/-34_151.geojsonl"]
    assert (cache / "tiles" / "-34_151.geojsonl").exists()
    assert len(result.footprints) == 1
    assert result.footprints[0]["source_id"] == "ms-au-downloaded"
