"""Tests for the stateless provider MCP surface."""

from __future__ import annotations

from typing import Any

import responses

from marktplaats_2dehands_mcp import server


def _add_search_response(
    mocked_responses: Any,
    site: str,
    payload: dict[str, Any],
    status: int = 200,
):
    host = "www.marktplaats.nl" if site == "marktplaats" else "www.2dehands.be"
    mocked_responses.add(
        responses.GET,
        f"https://{host}/lrp/api/search",
        json=payload,
        status=status,
    )


class TestSearchListings:
    def test_unknown_site_returns_error(self):
        result = server.search_listings(site="ebay", query="x")
        assert "error" in result

    def test_no_query_returns_error(self):
        result = server.search_listings(site="marktplaats")
        assert "error" in result

    def test_basic_marktplaats(
        self, mocked_responses, search_response_factory, listing_factory
    ):
        _add_search_response(
            mocked_responses,
            "marktplaats",
            search_response_factory(
                listings=[listing_factory(itemId="m100")],
                total=1,
            ),
        )
        result = server.search_listings(site="marktplaats", query="bike")
        assert result["site"] == "marktplaats"
        assert result["total_count"] == 1
        assert result["returned_count"] == 1
        assert result["listings"][0]["id"] == "m100"

    def test_2dehands_uses_correct_host(
        self, mocked_responses, search_response_factory
    ):
        _add_search_response(mocked_responses, "2dehands", search_response_factory())
        result = server.search_listings(site="2dehands", query="bike")
        assert result["site"] == "2dehands"
        assert "2dehands.be" in mocked_responses.calls[0].request.url

    def test_pagination_offset(
        self, mocked_responses, search_response_factory, listing_factory
    ):
        _add_search_response(
            mocked_responses,
            "marktplaats",
            search_response_factory(
                listings=[listing_factory(itemId="m1")],
                total=10,
            ),
        )
        result = server.search_listings(site="marktplaats", query="x", offset=2)
        assert result["next_offset"] == 3

    def test_seller_type_filter(
        self, mocked_responses, search_response_factory, listing_factory
    ):
        _add_search_response(
            mocked_responses,
            "marktplaats",
            search_response_factory(
                listings=[
                    listing_factory(itemId="m1", traits=["VERIFIED_SELLER"]),
                    listing_factory(itemId="m2", traits=[]),
                ],
                total=2,
            ),
        )
        result = server.search_listings(
            site="marktplaats", query="x", seller_type="private"
        )
        assert [item["id"] for item in result["listings"]] == ["m2"]


class TestProviderHelpers:
    def test_listing_details_delegates(self, monkeypatch):
        monkeypatch.setattr(
            server,
            "fetch_listing_details",
            lambda site, listing_id: {"site": site, "id": listing_id},
        )
        assert server.get_listing_details("m1") == {
            "site": "marktplaats",
            "id": "m1",
        }

    def test_list_categories(self):
        result = server.list_categories()
        assert result["main_categories"]
        assert result["subcategories"]

    def test_category_filters_no_args(self):
        assert "error" in server.get_category_filters()

    def test_seller_info(self, mocked_responses):
        mocked_responses.add(
            responses.GET,
            "https://www.marktplaats.nl/v/api/seller-profile/123",
            json={
                "bankAccount": True,
                "phoneNumber": True,
                "identification": False,
                "smbVerified": True,
                "paymentMethod": {"name": "ideal"},
                "reviews": [{"averageScore": 4.5, "numberOfReviews": 10}],
            },
            status=200,
        )
        result = server.get_seller_info(123)
        assert result["average_score"] == 4.5
        assert result["number_of_reviews"] == 10


def test_surface_is_stateless_provider_only():
    removed = {
        "hunt",
        "save_hunt",
        "list_hunts",
        "run_hunt",
        "check_new_matches",
        "save_search",
        "list_saved_searches",
        "delete_saved_search",
        "check_saved_search",
    }
    assert removed.isdisjoint(vars(server))


def test_main_runs(monkeypatch):
    called = []
    monkeypatch.setattr(server.mcp, "run", lambda: called.append(True))
    server.main()
    assert called == [True]
