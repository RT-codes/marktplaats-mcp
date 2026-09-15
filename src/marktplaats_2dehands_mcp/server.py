"""MCP server exposing provider tools for marktplaats.nl and 2dehands.be."""

from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

from .api import REQUEST_HEADERS, REQUEST_TIMEOUT, SearchError, build_search_params, search
from .category_fetcher import get_categories
from .formatting import format_listing
from .listing import fetch_listing_details
from .sites import SITES, listing_url, seller_url

mcp = FastMCP("marktplaats-2dehands")


def _make_listings(site: str, raw_listings: list[dict]) -> list[dict]:
    return [
        format_listing(listing, listing_url(site, listing.get("itemId", "")))
        for listing in raw_listings
    ]


def _filter_by_seller_type(listings: list[dict], seller_type: str) -> list[dict]:
    normalized = seller_type.lower()
    if normalized in ("business", "zakelijk"):
        return [listing for listing in listings if listing["seller"]["type"] == "business"]
    if normalized in ("private", "particulier"):
        return [listing for listing in listings if listing["seller"]["type"] == "private"]
    return listings


@mcp.tool()
def search_listings(
    site: str = "marktplaats",
    query: str = "",
    category: str | None = None,
    subcategory: str | None = None,
    zip_code: str = "",
    distance_km: int = 1000,
    price_from: int | None = None,
    price_to: int | None = None,
    condition: str | None = None,
    seller_type: str | None = None,
    sort_by: str = "optimized",
    sort_order: str = "asc",
    limit: int = 10,
    offset: int = 0,
    offered_since_days: int | None = None,
    attribute_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Search listings on Marktplaats or 2dehands.

    This provider is intentionally stateless. Multi-query fan-out, persistence,
    dedupe, ranking, refresh state, and hunt orchestration belong to consuming
    fabrics rather than this marketplace adapter.
    """
    if site not in SITES:
        return {"error": f"Unknown site: {site!r}. Use 'marktplaats' or '2dehands'."}
    if not query and not category and not subcategory:
        return {"error": "Provide a query, category, or subcategory."}

    try:
        params = build_search_params(
            site=site,
            query=query,
            category=category,
            subcategory=subcategory,
            zip_code=zip_code,
            distance_km=distance_km,
            price_from=price_from,
            price_to=price_to,
            condition=condition,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            offered_since_days=offered_since_days,
            attribute_ids=attribute_ids,
        )
        data = search(site, params)
    except SearchError as exc:
        return {"error": str(exc)}

    listings = _make_listings(site, data.get("listings", []))
    if seller_type:
        listings = _filter_by_seller_type(listings, seller_type)

    total_count = data.get("totalResultCount", 0)
    result: dict[str, Any] = {
        "site": site,
        "total_count": total_count,
        "returned_count": len(listings),
        "offset": offset,
        "listings": listings,
    }
    if not zip_code:
        result["note"] = "Provide zip_code to enable distance filtering."
    if offset + len(listings) < total_count:
        result["next_offset"] = offset + len(listings)
    return result


@mcp.tool()
def get_listing_details(listing_id: str, site: str = "marktplaats") -> dict[str, Any]:
    """Fetch a listing page and return title, price, description, images, and stats."""
    return fetch_listing_details(site, listing_id)


@mcp.tool()
def get_seller_info(seller_id: int, site: str = "marktplaats") -> dict[str, Any]:
    """Fetch seller verification, payment method, and review summary."""
    if site not in SITES:
        return {"error": f"Unknown site: {site!r}."}
    if not seller_id:
        return {"error": "Provide a seller_id."}

    try:
        response = requests.get(
            f"{seller_url(site)}/{seller_id}",
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {"error": f"Request failed: {exc}"}
    except ValueError:
        return {"error": "Invalid response"}

    reviews = data.get("reviews") or []
    review_summary = reviews[0] if reviews else {}

    return {
        "id": seller_id,
        "site": site,
        "is_business_verified": data.get("smbVerified", False),
        "verification": {
            "bank_account": data.get("bankAccount", False),
            "identification": data.get("identification", False),
            "phone_number": data.get("phoneNumber", False),
        },
        "payment_method": (data.get("paymentMethod") or {}).get("name"),
        "average_score": review_summary.get("averageScore"),
        "number_of_reviews": review_summary.get("numberOfReviews", 0),
    }


@mcp.tool()
def list_categories(site: str = "marktplaats") -> dict[str, Any]:
    """List supported main categories and common subcategories."""
    if site not in SITES:
        return {"error": f"Unknown site: {site!r}. Use 'marktplaats' or '2dehands'."}

    categories = get_categories(site)
    return {
        "main_categories": [
            {"name": name.title(), "id": category_id}
            for name, category_id in sorted(categories["l1"].items())
        ],
        "subcategories": [
            {"name": name.title(), "id": info["id"], "parent_id": info["parent"]}
            for name, info in sorted(categories["l2"].items())
        ],
        "note": "Use category names (not IDs) in search_listings.",
    }


@mcp.tool()
def get_category_filters(
    category: str | None = None,
    subcategory: str | None = None,
    site: str = "marktplaats",
) -> dict[str, Any]:
    """Discover attribute filters available within a category."""
    if site not in SITES:
        return {"error": f"Unknown site: {site!r}."}
    if not category and not subcategory:
        return {"error": "Provide a category or subcategory."}

    params: dict[str, Any] = {"limit": "1", "query": ""}
    categories = get_categories(site)

    if subcategory:
        key = subcategory.lower()
        if key not in categories["l2"]:
            return {"error": f"Unknown subcategory: {subcategory}"}
        params["l2CategoryId"] = str(categories["l2"][key]["id"])
        params["l1CategoryId"] = str(categories["l2"][key]["parent"])
    else:
        assert category is not None
        key = category.lower()
        if key not in categories["l1"]:
            return {"error": f"Unknown category: {category}"}
        params["l1CategoryId"] = str(categories["l1"][key])

    try:
        data = search(site, params)
    except SearchError as exc:
        return {"error": str(exc)}

    filters: dict[str, list[dict]] = {}
    skip_keys = {"PriceCents", "RelevantCategories", "offeredSince"}

    for facet in data.get("facets", []):
        if facet.get("key") in skip_keys:
            continue
        label = facet.get("label", facet.get("key"))
        options = []
        for attribute in facet.get("attributeGroup") or []:
            attribute_id = attribute.get("attributeValueId")
            if attribute_id is not None:
                options.append(
                    {
                        "name": attribute.get("attributeValueLabel")
                        or attribute.get("attributeValueKey"),
                        "id": attribute_id,
                        "count": attribute.get("histogramCount", 0),
                    }
                )
        if options:
            filters[label] = options

    return {
        "site": site,
        "category": subcategory or category,
        "filters": filters,
        "usage": "Pass selected ids via 'attribute_ids' on search_listings.",
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
