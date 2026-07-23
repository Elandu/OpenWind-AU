"""Tests for Microsoft Australia Building Footprints cache provider."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from openwind_au.microsoft_footprints import (
    MAX_MICROSOFT_INDEX_BYTES,
    MAX_MICROSOFT_TILE_BYTES,
    MICROSOFT_FOOTPRINT_SOURCE,
    load_tile_index,
    microsoft_target_lock,
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


def test_microsoft_provider_geojsonl_prefilter_keeps_polygon_crossing_query_bbox(tmp_path) -> None:
    cache = tmp_path / "microsoft"
    tiles = cache / "tiles"
    tiles.mkdir(parents=True)
    tile = tiles / "-34_151.geojsonl"
    crossing = {
        "type": "Feature",
        "properties": {"id": "crossing"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [151.202, -33.864],
                    [151.212, -33.864],
                    [151.212, -33.856],
                    [151.202, -33.856],
                    [151.202, -33.864],
                ]
            ],
        },
    }
    tile.write_text(json.dumps(crossing) + "\n", encoding="utf-8")

    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=cache,
        allow_download=False,
    )

    assert len(result.footprints) == 1
    assert result.footprints[0]["source_id"] == "ms-au-crossing"


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
        headers = {"content-length": str(len(content))}
        url = "https://example.test/-34_151.geojsonl"

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield self.content

    def fake_get(url: str, headers: dict[str, str], timeout: int, stream: bool):
        assert headers["User-Agent"].startswith("OpenWind-AU/")
        assert stream is True
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


def test_microsoft_provider_uses_default_index_inside_cache(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "microsoft"
    cache.mkdir()
    (cache / "metadata.json").write_text('{"not":"a footprint"}', encoding="utf-8")
    tile_content = (json.dumps(feature("local-index", 151.21, -33.86)) + "\n").encode()
    (cache / "index.json").write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/-34_151.geojsonl",
                        "file": "tiles/-34_151.geojsonl",
                        "sha256": hashlib.sha256(tile_content).hexdigest(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        headers = {"content-length": str(len(tile_content))}
        url = "https://example.test/-34_151.geojsonl"

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield tile_content

    monkeypatch.delenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", raising=False)
    monkeypatch.setattr(
        "openwind_au.microsoft_footprints.requests.get",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=cache,
        allow_download=True,
    )

    assert (cache / "tiles" / "-34_151.geojsonl").exists()
    assert len(result.footprints) == 1
    assert result.footprints[0]["source_id"] == "ms-au-local-index"


@pytest.mark.parametrize(
    "cached_content",
    [
        b"{not-json",
        json.dumps(feature("stale", 151.21, -33.86)).encode() + b"\n",
    ],
)
def test_microsoft_provider_refreshes_invalid_indexed_cache_tile(
    tmp_path,
    monkeypatch,
    cached_content: bytes,
) -> None:
    cache = tmp_path / "microsoft"
    tile = cache / "tiles" / "-34_151.geojsonl"
    tile.parent.mkdir(parents=True)
    tile.write_bytes(cached_content)
    expected_content = (json.dumps(feature("refreshed", 151.21, -33.86)) + "\n").encode()
    (cache / "index.json").write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/-34_151.geojsonl",
                        "file": "tiles/-34_151.geojsonl",
                        "sha256": hashlib.sha256(expected_content).hexdigest(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    responses = []

    class FakeResponse:
        headers = {"content-length": str(len(expected_content))}
        url = "https://example.test/-34_151.geojsonl"
        closed = False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield expected_content

        def close(self) -> None:
            self.closed = True

    def fake_get(*_args, **_kwargs):
        response = FakeResponse()
        responses.append(response)
        return response

    monkeypatch.delenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", raising=False)
    monkeypatch.setattr("openwind_au.microsoft_footprints.requests.get", fake_get)

    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=cache,
        allow_download=True,
    )

    assert tile.read_bytes() == expected_content
    assert len(responses) == 1
    assert responses[0].closed is True
    assert [item["source_id"] for item in result.footprints] == ["ms-au-refreshed"]


def test_microsoft_provider_validates_matching_indexed_cache_without_download(
    tmp_path,
    monkeypatch,
) -> None:
    cache = tmp_path / "microsoft"
    tile = cache / "tiles" / "-34_151.geojsonl"
    tile.parent.mkdir(parents=True)
    tile_content = (json.dumps(feature("verified", 151.21, -33.86)) + "\n").encode()
    tile.write_bytes(tile_content)
    (cache / "index.json").write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/-34_151.geojsonl",
                        "file": "tiles/-34_151.geojsonl",
                        "sha256": hashlib.sha256(tile_content).hexdigest(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "openwind_au.microsoft_footprints.requests.get",
        lambda *_args, **_kwargs: pytest.fail("a verified cached tile must not be downloaded"),
    )

    result = query_microsoft_building_footprints(
        -33.86,
        151.21,
        500,
        cache_dir=cache,
        allow_download=True,
    )

    assert [item["source_id"] for item in result.footprints] == ["ms-au-verified"]


def test_concurrent_microsoft_queries_download_an_indexed_tile_once(
    tmp_path,
    monkeypatch,
) -> None:
    cache = tmp_path / "microsoft"
    cache.mkdir()
    tile_content = (json.dumps(feature("concurrent", 151.21, -33.86)) + "\n").encode()
    (cache / "index.json").write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/-34_151.geojsonl",
                        "file": "tiles/-34_151.geojsonl",
                        "sha256": hashlib.sha256(tile_content).hexdigest(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    request_count = 0
    request_count_lock = threading.Lock()
    start = threading.Barrier(3)

    class FakeResponse:
        headers = {"content-length": str(len(tile_content))}
        url = "https://example.test/-34_151.geojsonl"

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield tile_content

        def close(self) -> None:
            return None

    def fake_get(*_args, **_kwargs):
        nonlocal request_count
        with request_count_lock:
            request_count += 1
        return FakeResponse()

    def run_query():
        start.wait()
        return query_microsoft_building_footprints(
            -33.86,
            151.21,
            500,
            cache_dir=cache,
            allow_download=True,
        )

    monkeypatch.setattr("openwind_au.microsoft_footprints.requests.get", fake_get)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_query) for _ in range(2)]
        start.wait()
        results = [future.result() for future in futures]

    assert request_count == 1
    assert all(len(result.footprints) == 1 for result in results)
    assert not list(cache.rglob("*.part"))


@pytest.mark.skipif(os.name != "nt", reason="Windows extended paths are platform-specific")
def test_microsoft_target_lock_normalizes_windows_extended_path_aliases(
    tmp_path,
) -> None:
    ordinary_target = tmp_path / "microsoft" / "tiles" / "-34_151.geojsonl"
    extended_target = type(ordinary_target)(f"\\\\?\\{ordinary_target}")

    assert microsoft_target_lock(ordinary_target) is microsoft_target_lock(extended_target)


@pytest.mark.parametrize(
    "unsafe_file",
    [
        "../../outside.geojsonl",
        "tiles/../../../outside.geojson",
        "C:/outside.geojson",
        r"\\server\share\outside.geojson",
    ],
)
def test_microsoft_index_cannot_write_outside_cache(
    tmp_path,
    monkeypatch,
    unsafe_file: str,
) -> None:
    cache = tmp_path / "microsoft"
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/tile.geojsonl",
                        "file": unsafe_file,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", str(index))

    with pytest.raises(ValueError, match="relative|escapes"):
        query_microsoft_building_footprints(
            -33.86,
            151.21,
            500,
            cache_dir=cache,
            allow_download=True,
        )

    assert not (tmp_path / "outside.geojsonl").exists()
    assert not (tmp_path / "outside.geojson").exists()


def test_microsoft_tile_download_is_bounded_and_leaves_no_partial_file(
    tmp_path,
    monkeypatch,
) -> None:
    cache = tmp_path / "microsoft"
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/tile.geojsonl",
                        "file": "tiles/-34_151.geojsonl",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class OversizedResponse:
        headers = {"content-length": str(MAX_MICROSOFT_TILE_BYTES + 1)}
        url = "https://example.test/tile.geojsonl"
        closed = False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            raise AssertionError("oversized response should be rejected before streaming")

        def close(self) -> None:
            self.closed = True

    response = OversizedResponse()

    monkeypatch.setenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", str(index))
    monkeypatch.setattr(
        "openwind_au.microsoft_footprints.requests.get",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(ValueError, match="exceeds"):
        query_microsoft_building_footprints(
            -33.86,
            151.21,
            500,
            cache_dir=cache,
            allow_download=True,
        )

    assert not (cache / "tiles" / "-34_151.geojsonl").exists()
    assert not list(cache.rglob("*.part"))
    assert response.closed is True


def test_microsoft_tile_hash_mismatch_is_rejected(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "microsoft"
    index = tmp_path / "index.json"
    tile_content = (json.dumps(feature("downloaded", 151.21, -33.86)) + "\n").encode()
    index.write_text(
        json.dumps(
            {
                "tiles": {
                    "-34_151": {
                        "url": "https://example.test/tile.geojsonl",
                        "file": "tiles/-34_151.geojsonl",
                        "sha256": hashlib.sha256(b"different content").hexdigest(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        headers = {"content-length": str(len(tile_content))}
        url = "https://example.test/tile.geojsonl"

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield tile_content

    monkeypatch.setenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", str(index))
    monkeypatch.setattr(
        "openwind_au.microsoft_footprints.requests.get",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    with pytest.raises(ValueError, match="SHA-256"):
        query_microsoft_building_footprints(
            -33.86,
            151.21,
            500,
            cache_dir=cache,
            allow_download=True,
        )

    assert not (cache / "tiles" / "-34_151.geojsonl").exists()


def test_remote_microsoft_index_requires_https(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", raising=False)
    monkeypatch.setenv(
        "OPENWIND_MICROSOFT_FOOTPRINT_INDEX_URL",
        "http://example.test/index.json",
    )
    monkeypatch.setattr(
        "openwind_au.microsoft_footprints.requests.get",
        lambda *_args, **_kwargs: pytest.fail("an insecure index URL must not be requested"),
    )

    with pytest.raises(ValueError, match="index URLs must use HTTPS"):
        load_tile_index(tmp_path / "missing-cache")


@pytest.mark.parametrize(
    ("response_url", "content_length", "error"),
    [
        ("http://example.test/index.json", "2", "redirects must remain on HTTPS"),
        (
            "https://example.test/index.json",
            str(MAX_MICROSOFT_INDEX_BYTES + 1),
            "exceeds",
        ),
    ],
)
def test_remote_microsoft_index_rejects_unsafe_response_and_closes_it(
    tmp_path,
    monkeypatch,
    response_url: str,
    content_length: str,
    error: str,
) -> None:
    class FakeResponse:
        headers = {"content-length": content_length}
        url = response_url
        closed = False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield b"{}"

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()
    monkeypatch.delenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", raising=False)
    monkeypatch.setenv(
        "OPENWIND_MICROSOFT_FOOTPRINT_INDEX_URL",
        "https://example.test/index.json",
    )
    monkeypatch.setattr(
        "openwind_au.microsoft_footprints.requests.get",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(ValueError, match=error):
        load_tile_index(tmp_path / "missing-cache")

    assert response.closed is True


def test_remote_microsoft_index_stream_is_bounded_and_closed(tmp_path, monkeypatch) -> None:
    class FakeResponse:
        headers = {}
        url = "https://example.test/index.json"
        closed = False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield b"x" * MAX_MICROSOFT_INDEX_BYTES
            yield b"x"

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()
    monkeypatch.delenv("OPENWIND_MICROSOFT_FOOTPRINT_INDEX", raising=False)
    monkeypatch.setenv(
        "OPENWIND_MICROSOFT_FOOTPRINT_INDEX_URL",
        "https://example.test/index.json",
    )
    monkeypatch.setattr(
        "openwind_au.microsoft_footprints.requests.get",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(ValueError, match="exceeds"):
        load_tile_index(tmp_path / "missing-cache")

    assert response.closed is True
