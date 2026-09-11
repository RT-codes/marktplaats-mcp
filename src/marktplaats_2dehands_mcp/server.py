"""MCP server exposing tools for marktplaats.nl and 2dehands.be."""

from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

from . import saved_searches as ss
from . import saved_hunts as sh
from .api import REQUEST_HEADERS, REQUEST_TIMEOUT, SearchError, build_search_params, search
from .category_fetcher import get_categories
from .formatting import format_listing
from .listing import fetch_listing_details
from .sites import SITES, listing_url, seller_url

mcp = FastMCP("marktplaats-2dehands")


def _make_listings(site: str, raw_listings: list[dict]) -> list[dict]:
    return [
        format_listing(l, listing_url(site, l.get("itemId", "")))
        for l in raw_listings
    ]


def _filter_by_seller_type(listings: list[dict], seller_type: str) -> list[dict]:
    st = seller_type.lower()
    if st in ("business", "zakelijk"):
        return [l for l in listings if l["seller"]["type"] == "business"]
    if st in ("private", "particulier"):
        return [l for l in listings if l["seller"]["type"] == "private"]
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
    """Search for listings on marktplaats.nl or 2dehands.be.

    Args:
        site: "marktplaats" (NL, default) or "2dehands" (BE).
        query: Search query text (required if no category specified).
        category: Main category name (e.g., "computers en software").
        subcategory: Subcategory name (e.g., "laptops", "elektrische fietsen").
        zip_code: Postal code for distance filtering. NL: "1016LV". BE: "2000".
        distance_km: Maximum distance in km (default 1000). Requires zip_code.
        price_from / price_to: Price range in euros.
        condition: "new", "as_good_as_new", "used", "refurbished", "not_working".
        seller_type: "business" / "zakelijk" or "private" / "particulier".
        sort_by: "date", "price", "optimized", "location".
        sort_order: "asc" or "desc".
        limit: 1-100 (default 10).
        offset: Pagination offset.
        offered_since_days: Only show items posted within the last N days.
        attribute_ids: Category-specific filter IDs (use get_category_filters).

    Returns:
        Dict with total_count, returned_count, listings, optional next_offset.
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
    except SearchError as e:
        return {"error": str(e)}

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


HUNT_MAX_SEARCHES = 20
HUNT_MAX_PER_SEARCH = 25

HUNT_ALLOWED_PARAMS = {
    "site",
    "query",
    "category",
    "subcategory",
    "zip_code",
    "distance_km",
    "price_from",
    "price_to",
    "condition",
    "seller_type",
    "sort_by",
    "sort_order",
    "limit",
    "offset",
    "offered_since_days",
    "attribute_ids",
}


@mcp.tool()
def hunt(
    searches: list[dict[str, Any]],
    per_search_limit: int = 10,
) -> dict[str, Any]:
    """Run several complementary Marktplaats searches as one bounded hunt.

    Each search is a dict containing normal search_listings arguments plus an
    optional human-readable ``label`` used for provenance.

    Example:
        [
            {"label": "p100 nearby", "query": "Tesla P100", "price_to": 150},
            {"label": "cheap workstation", "query": "Dell Precision", "price_to": 120},
        ]

    Results are deduplicated by Marktplaats listing ID. Every candidate keeps
    a ``found_by`` list showing which searches independently discovered it.

    Hard limits:
        - maximum 20 searches per hunt
        - maximum 25 returned listings per individual search
    """
    if not searches:
        return {"error": "Provide at least one search."}

    if len(searches) > HUNT_MAX_SEARCHES:
        return {
            "error": (
                f"Too many searches: {len(searches)}. "
                f"Maximum is {HUNT_MAX_SEARCHES}."
            )
        }

    per_search_limit = max(1, min(int(per_search_limit), HUNT_MAX_PER_SEARCH))

    candidates_by_id: dict[str, dict[str, Any]] = {}
    search_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    raw_result_count = 0

    for index, original in enumerate(searches, start=1):
        if not isinstance(original, dict):
            errors.append({
                "search": index,
                "error": "Search entry must be an object/dict.",
            })
            continue

        params = dict(original)
        label = str(
            params.pop("label", "")
            or params.get("query")
            or params.get("subcategory")
            or params.get("category")
            or f"search-{index}"
        )

        unknown = sorted(set(params) - HUNT_ALLOWED_PARAMS)
        if unknown:
            errors.append({
                "search": index,
                "label": label,
                "error": f"Unknown search parameters: {', '.join(unknown)}",
            })
            continue

        requested_limit = params.get("limit", per_search_limit)
        try:
            requested_limit = int(requested_limit)
        except (TypeError, ValueError):
            requested_limit = per_search_limit

        params["limit"] = max(
            1,
            min(requested_limit, per_search_limit, HUNT_MAX_PER_SEARCH),
        )

        try:
            result = search_listings(**params)
        except TypeError as exc:
            errors.append({
                "search": index,
                "label": label,
                "error": str(exc),
            })
            continue

        if "error" in result:
            errors.append({
                "search": index,
                "label": label,
                "error": result["error"],
            })
            continue

        listings = result.get("listings", [])
        raw_result_count += len(listings)

        search_summaries.append({
            "label": label,
            "returned_count": len(listings),
            "total_count": result.get("total_count", 0),
        })

        for listing in listings:
            listing_id = listing.get("id")
            if not listing_id:
                continue

            existing = candidates_by_id.get(listing_id)

            if existing is None:
                candidate = dict(listing)
                candidate["found_by"] = [label]
                candidates_by_id[listing_id] = candidate
            elif label not in existing["found_by"]:
                existing["found_by"].append(label)

    candidates = list(candidates_by_id.values())

    for candidate in candidates:
        candidate["found_by_count"] = len(candidate["found_by"])

    return {
        "search_count": len(searches),
        "successful_searches": len(search_summaries),
        "failed_searches": len(errors),
        "raw_result_count": raw_result_count,
        "unique_count": len(candidates),
        "duplicates_removed": raw_result_count - len(candidates),
        "searches": search_summaries,
        "candidates": candidates,
        "errors": errors,
    }


@mcp.tool()
def get_listing_details(listing_id: str, site: str = "marktplaats") -> dict[str, Any]:
    """Fetch a listing page and return title, price, description, images, stats.

    Args:
        listing_id: e.g. "m2340580395" (the 'm' prefix is added if missing).
        site: "marktplaats" or "2dehands".
    """
    return fetch_listing_details(site, listing_id)


@mcp.tool()
def get_seller_info(seller_id: int, site: str = "marktplaats") -> dict[str, Any]:
    """Fetch a seller profile (verification status, payment method, reviews).

    Note: the endpoint does not return seller name/id — those are available
    from the listing response. It only exposes verification flags, the
    accepted payment method, and aggregated review stats.
    """
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
    except requests.RequestException as e:
        return {"error": f"Request failed: {e}"}
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
    """List the supported main categories and common subcategories.

    Same IDs work on both marktplaats.nl and 2dehands.be.
    """
    if site not in SITES:
        return {"error": f"Unknown site: {site!r}. Use 'marktplaats' or '2dehands'."}
    cats = get_categories(site)
    return {
        "main_categories": [
            {"name": name.title(), "id": id_} for name, id_ in sorted(cats["l1"].items())
        ],
        "subcategories": [
            {"name": name.title(), "id": info["id"], "parent_id": info["parent"]}
            for name, info in sorted(cats["l2"].items())
        ],
        "note": "Use category names (not IDs) in search_listings.",
    }


@mcp.tool()
def get_category_filters(
    category: str | None = None,
    subcategory: str | None = None,
    site: str = "marktplaats",
) -> dict[str, Any]:
    """Discover the attribute filters available within a category."""
    if site not in SITES:
        return {"error": f"Unknown site: {site!r}."}
    if not category and not subcategory:
        return {"error": "Provide a category or subcategory."}

    params: dict[str, Any] = {"limit": "1", "query": ""}
    cats = get_categories(site)
    if subcategory:
        sub = subcategory.lower()
        if sub not in cats["l2"]:
            return {"error": f"Unknown subcategory: {subcategory}"}
        params["l2CategoryId"] = str(cats["l2"][sub]["id"])
        params["l1CategoryId"] = str(cats["l2"][sub]["parent"])
    else:
        # Both-None already returned above; subcategory is falsy here, so
        # category must be truthy.
        assert category is not None
        cat = category.lower()
        if cat not in cats["l1"]:
            return {"error": f"Unknown category: {category}"}
        params["l1CategoryId"] = str(cats["l1"][cat])

    try:
        data = search(site, params)
    except SearchError as e:
        return {"error": str(e)}

    filters: dict[str, list[dict]] = {}
    skip_keys = {"PriceCents", "RelevantCategories", "offeredSince"}
    for facet in data.get("facets", []):
        if facet.get("key") in skip_keys:
            continue
        label = facet.get("label", facet.get("key"))
        options = []
        for attr in facet.get("attributeGroup") or []:
            attr_id = attr.get("attributeValueId")
            if attr_id is not None:
                options.append({
                    "name": attr.get("attributeValueLabel") or attr.get("attributeValueKey"),
                    "id": attr_id,
                    "count": attr.get("histogramCount", 0),
                })
        if options:
            filters[label] = options

    return {
        "site": site,
        "category": subcategory or category,
        "filters": filters,
        "usage": "Pass selected ids via 'attribute_ids' on search_listings.",
    }


@mcp.tool()
def save_hunt(
    name: str,
    searches: list[dict[str, Any]],
    per_search_limit: int = 10,
) -> dict[str, Any]:
    """Save a reusable named hunt locally."""
    name = name.strip()

    if not name:
        return {"error": "Provide a hunt name."}

    if not searches:
        return {"error": "Provide at least one search."}

    if len(searches) > HUNT_MAX_SEARCHES:
        return {
            "error": (
                f"Too many searches: {len(searches)}. "
                f"Maximum is {HUNT_MAX_SEARCHES}."
            )
        }

    for index, spec in enumerate(searches, start=1):
        if not isinstance(spec, dict):
            return {
                "error": f"Search {index} must be an object/dict."
            }

        unknown = sorted(
            set(spec) - HUNT_ALLOWED_PARAMS - {"label"}
        )

        if unknown:
            return {
                "error": (
                    f"Search {index} has unknown parameters: "
                    f"{', '.join(unknown)}"
                )
            }

    per_search_limit = max(
        1,
        min(int(per_search_limit), HUNT_MAX_PER_SEARCH),
    )

    return sh.save_hunt(
        name=name,
        searches=searches,
        per_search_limit=per_search_limit,
    )


@mcp.tool()
def list_hunts() -> dict[str, Any]:
    """List locally saved hunts."""
    return {"hunts": sh.list_hunts()}


@mcp.tool()
def run_hunt(name: str) -> dict[str, Any]:
    """Run a previously saved hunt."""
    entry = sh.get_hunt(name)

    if entry is None:
        return {"error": f"No saved hunt named {name!r}."}

    result = hunt(
        searches=entry["searches"],
        per_search_limit=entry.get("per_search_limit", 10),
    )

    if "error" not in result:
        result["name"] = name

    return result


@mcp.tool()
def check_new_matches(
    name: str,
    mark_seen: bool = True,
) -> dict[str, Any]:
    """Run a saved hunt and return only listings not seen before."""
    entry = sh.get_hunt(name)

    if entry is None:
        return {"error": f"No saved hunt named {name!r}."}

    result = hunt(
        searches=entry["searches"],
        per_search_limit=entry.get("per_search_limit", 10),
    )

    if "error" in result:
        return result

    candidates = result["candidates"]
    seen_ids = set(entry.get("seen_ids", []))

    new_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("id") not in seen_ids
    ]

    if mark_seen:
        sh.record_check(
            name,
            [
                candidate["id"]
                for candidate in candidates
                if candidate.get("id")
            ],
        )

    return {
        "name": name,
        "first_check": entry.get("last_checked_at") is None,
        "checked_count": len(candidates),
        "new_count": len(new_candidates),
        "new_candidates": new_candidates,
        "hunt_summary": {
            "search_count": result["search_count"],
            "successful_searches": result["successful_searches"],
            "failed_searches": result["failed_searches"],
            "raw_result_count": result["raw_result_count"],
            "unique_count": result["unique_count"],
            "duplicates_removed": result["duplicates_removed"],
        },
    }


@mcp.tool()
def save_search(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Persist a search so it can be re-run via check_saved_search.

    Args:
        name: Identifier for the saved search (e.g. "trek-bike-antwerp").
        params: Same kwargs as search_listings (must include 'site').

    On creation, seen_ids is empty — the first check_saved_search call will
    return all current matches. To suppress that backfill, call check
    immediately after saving.
    """
    if "site" not in params:
        return {"error": "params must include 'site'."}
    return ss.save_search(name, params)


@mcp.tool()
def list_saved_searches() -> dict[str, Any]:
    """List all persisted searches."""
    return {"searches": ss.list_searches()}


@mcp.tool()
def delete_saved_search(name: str) -> dict[str, Any]:
    """Remove a persisted search."""
    return {"name": name, "deleted": ss.delete_search(name)}


@mcp.tool()
def check_saved_search(name: str, mark_seen: bool = True) -> dict[str, Any]:
    """Re-run a saved search and return only listings not seen before.

    Args:
        name: The saved search name.
        mark_seen: If True (default), record the returned IDs as seen so
            the next call returns only newer ones. Set False for a dry-run.
    """
    entry = ss.get_search(name)
    if entry is None:
        return {"error": f"No saved search named {name!r}"}

    params = dict(entry["params"])
    site = params.get("site")
    if site not in SITES:
        return {"error": f"Saved search has unknown site: {site!r}"}

    # Force a manageable limit for monitoring; user can override via params.
    params.setdefault("limit", 50)
    params.setdefault("sort_by", "date")
    params.setdefault("sort_order", "desc")

    result = search_listings(**params)
    if "error" in result:
        return result

    listings = result["listings"]
    seen_ids = set(entry.get("seen_ids", []))
    new_listings = [l for l in listings if l.get("id") not in seen_ids]

    if mark_seen:
        ss.record_check(name, [l["id"] for l in listings if l.get("id")])

    return {
        "name": name,
        "site": site,
        "checked_count": len(listings),
        "new_count": len(new_listings),
        "new_listings": new_listings,
        "first_check": entry.get("last_checked_at") is None,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
