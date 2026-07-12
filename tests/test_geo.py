"""Tests for geocoding result normalization and supported bounds."""

from __future__ import annotations

import openwind_au.geo as geo_module


def test_geocode_address_skips_unsupported_australian_territory(monkeypatch) -> None:
    monkeypatch.setattr(
        geo_module,
        "_get_json",
        lambda *_args, **_kwargs: [
            {
                "lat": "-54.6318",
                "lon": "158.8618",
                "display_name": "Macquarie Island, Tasmania, Australia",
            },
            {
                "lat": "-33.8688",
                "lon": "151.2093",
                "display_name": "Sydney, New South Wales, Australia",
            },
        ],
    )

    result = geo_module.geocode_address("Sydney")

    assert result["latitude"] == -33.8688
    assert result["longitude"] == 151.2093


def test_address_suggestions_exclude_coordinates_rejected_by_request_model(monkeypatch) -> None:
    monkeypatch.setattr(
        geo_module,
        "_get_json",
        lambda *_args, **_kwargs: {
            "features": [
                {
                    "geometry": {"coordinates": [158.8618, -54.6318]},
                    "properties": {
                        "name": "Macquarie Island",
                        "state": "Tasmania",
                        "country": "Australia",
                        "countrycode": "AU",
                    },
                },
                {
                    "geometry": {"coordinates": [151.21319, -33.85918]},
                    "properties": {
                        "housenumber": "1",
                        "street": "Macquarie Street",
                        "city": "Sydney",
                        "state": "New South Wales",
                        "country": "Australia",
                        "countrycode": "AU",
                    },
                },
            ]
        },
    )
    geo_module._cached_get_json.cache_clear()

    suggestions = geo_module.geocode_address_suggestions("macquarie")

    assert [item["display_name"] for item in suggestions] == [
        "1 Macquarie Street, Sydney, New South Wales, Australia"
    ]
