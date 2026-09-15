# Marktplaats MCP

A lean, stateless MCP provider for public marketplace data from Marktplaats.nl and 2dehands.be.

This repository intentionally stays close to the marketplace/API layer. It exposes retrieval and platform-specific helpers, but does **not** own deal-hunt orchestration, multi-query fan-out, ranking, persistence, seen-state, refresh logic, or tracker updates.

Those higher-level behaviors belong in consuming fabrics such as the Secondhand Dealhunt Fabric in `RT-codes/mcp-hub`.

## Provider tools

| Tool | Purpose |
| --- | --- |
| `search_listings` | Run one filtered marketplace search. |
| `get_listing_details` | Fetch fuller details for one listing. |
| `get_seller_info` | Fetch seller verification/review information. |
| `list_categories` | List known marketplace categories. |
| `get_category_filters` | Discover category-specific attribute filters. |

No Marktplaats login or API key is required for these public retrieval tools.

## Architecture boundary

```text
Secondhand Dealhunt Fabric
    |
    | repeated provider calls
    v
Marktplaats MCP
    |
    +-- search_listings
    +-- get_listing_details
    +-- get_seller_info
    +-- list_categories
    +-- get_category_filters
    |
    v
Marktplaats / 2dehands endpoints
```

The provider returns marketplace facts. The consuming fabric decides **how many searches to run, how to combine them, what has already been seen, and how candidates should be ranked or tracked**.

## Install

Requires `uv`.

```bash
git clone https://github.com/RT-codes/marktplaats-mcp.git
cd marktplaats-mcp
uv sync
uv run marktplaats-2dehands-mcp
```

Or run directly from GitHub:

```bash
uvx --from git+https://github.com/RT-codes/marktplaats-mcp.git \
  marktplaats-2dehands-mcp
```

## Example

```text
search_listings(
  query="RTX 4090",
  zip_code="3811",
  distance_km=50,
  price_to=1500,
  sort_by="date",
  sort_order="desc",
  limit=20
)
```

A normalized result contains a stable listing ID and URL plus marketplace fields such as title, description, price, condition, location, seller metadata and image.

## Relationship to upstream

This project originated from the Marktplaats / 2dehands MCP ecosystem and keeps the useful retrieval layer while deliberately avoiding application-level workflow logic.

That makes it suitable as a small provider MCP that can be plugged into different orchestration layers instead of becoming one large opinionated shopping agent by itself.
