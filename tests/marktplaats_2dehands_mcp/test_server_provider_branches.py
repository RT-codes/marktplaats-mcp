"""Focused branch coverage for the stateless provider wrapper."""

from __future__ import annotations

from typing import Any

import responses

from marktplaats_2dehands_mcp import server


def test_seller_type_helper_covers_all_modes() -> None:
    listings = [
        {"id": "business", "seller": {"type": "business"}},
        {"id": "private", "seller": {"type": "private"}},
    ]

    assert [item["id"] for item in server._filter_by_seller_type(listings, "zakelijk")] == [
        "business"
    ]
    assert [item["id"] for item in server._filter_by_seller_type(listings, "particulier")] == [
        "private"
    ]
    assert server._filter_by_seller_type(listings, "anything-else") == listings


def test_search_listings_surfaces_search_error(monkeypatch) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise server.SearchError("boom")

    monkeypatch.setattr(server, "search", fail)
    assert server.search_listings(query="gpu") == {"error": "boom"}


def test_search_listings_with_zip_omits_distance_note(
    monkeypatch,
    listing_factory,
) -> None:
    monkeypatch.setattr(
        server,
        "search",
        lambda *_args, **_kwargs: {
            "listings": [listing_factory(itemId="m1")],
            "totalResultCount": 1,
        },
    )

    result = server.search_listings(query="gpu", zip_code="3811AA")

    assert "note" not in result
    assert "next_offset" not in result


def test_seller_info_validation() -> None:
    assert "error" in server.get_seller_info(123, site="ebay")
    assert server.get_seller_info(0) == {"error": "Provide a seller_id."}


def test_seller_info_request_failure(mocked_responses) -> None:
    mocked_responses.add(
        responses.GET,
        "https://www.marktplaats.nl/v/api/seller-profile/123",
        status=500,
    )

    result = server.get_seller_info(123)
    assert result["error"].startswith("Request failed:")


def test_seller_info_invalid_json(mocked_responses) -> None:
    mocked_responses.add(
        responses.GET,
        "https://www.marktplaats.nl/v/api/seller-profile/123",
        body="not-json",
        status=200,
        content_type="application/json",
    )

    assert server.get_seller_info(123) == {"error": "Invalid response"}


def test_seller_info_handles_missing_optional_fields(mocked_responses) -> None:
    mocked_responses.add(
        responses.GET,
        "https://www.marktplaats.nl/v/api/seller-profile/123",
        json={},
        status=200,
    )

    result = server.get_seller_info(123)
    assert result["payment_method"] is None
    assert result["average_score"] is None
    assert result["number_of_reviews"] == 0


def test_list_categories_rejects_unknown_site() -> None:
    assert "error" in server.list_categories("ebay")


def test_category_filters_validation() -> None:
    assert "error" in server.get_category_filters(site="ebay", category="computers en software")
    assert "error" in server.get_category_filters(subcategory="does-not-exist")
    assert "error" in server.get_category_filters(category="does-not-exist")


def test_category_filters_subcategory_builds_ids(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search(site: str, params: dict[str, Any]) -> dict[str, Any]:
        captured.update(params)
        return {"facets": []}

    monkeypatch.setattr(server, "search", fake_search)

    result = server.get_category_filters(subcategory="laptops")

    assert result["category"] == "laptops"
    assert captured["l2CategoryId"] == "339"
    assert captured["l1CategoryId"] == "322"


def test_category_filters_category_builds_id(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search(site: str, params: dict[str, Any]) -> dict[str, Any]:
        captured.update(params)
        return {"facets": []}

    monkeypatch.setattr(server, "search", fake_search)

    result = server.get_category_filters(category="computers en software")

    assert result["category"] == "computers en software"
    assert captured["l1CategoryId"] == "322"
    assert "l2CategoryId" not in captured


def test_category_filters_surfaces_search_error(monkeypatch) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise server.SearchError("facet lookup failed")

    monkeypatch.setattr(server, "search", fail)

    assert server.get_category_filters(category="computers en software") == {
        "error": "facet lookup failed"
    }


def test_category_filters_normalizes_facets(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "search",
        lambda *_args, **_kwargs: {
            "facets": [
                {
                    "key": "PriceCents",
                    "label": "Price",
                    "attributeGroup": [
                        {
                            "attributeValueId": 999,
                            "attributeValueLabel": "ignored",
                            "histogramCount": 1,
                        }
                    ],
                },
                {
                    "key": "Brand",
                    "label": "Brand",
                    "attributeGroup": [
                        {
                            "attributeValueId": 7,
                            "attributeValueLabel": "NVIDIA",
                            "histogramCount": 3,
                        },
                        {
                            "attributeValueId": None,
                            "attributeValueLabel": "missing id",
                            "histogramCount": 4,
                        },
                    ],
                },
                {
                    "key": "Connector",
                    "attributeGroup": [
                        {
                            "attributeValueId": 8,
                            "attributeValueKey": "pcie",
                        }
                    ],
                },
                {
                    "key": "Empty",
                    "label": "Empty",
                    "attributeGroup": None,
                },
            ]
        },
    )

    result = server.get_category_filters(category="computers en software")

    assert "Price" not in result["filters"]
    assert result["filters"]["Brand"] == [
        {"name": "NVIDIA", "id": 7, "count": 3}
    ]
    assert result["filters"]["Connector"] == [
        {"name": "pcie", "id": 8, "count": 0}
    ]
    assert "Empty" not in result["filters"]
