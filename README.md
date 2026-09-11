# Marktplaats MCP

A friendly, agent-oriented MCP server for searching and monitoring [Marktplaats.nl](https://www.marktplaats.nl) (and the inherited 2dehands.be support).

Instead of only exposing a single marketplace search, this version adds **multi-query hunts**: an AI agent can turn one shopping goal into several complementary searches, merge the results, remove duplicates, remember what it has already seen, and later ask for only the genuinely new listings.

Good for things like:

- finding a specific laptop without trusting one exact search phrase
- hunting for gaming-PC bargains across complete systems, GPUs and vague titles
- monitoring a saved search over time
- giving an AI a compact candidate pool it can rank semantically

No Marktplaats login or API key is needed for the public search tools.

## Why this version exists

The upstream project already provided a solid MCP retrieval layer for Marktplaats and 2dehands. This wrapper keeps that useful base and adds a more **agent-native hunting workflow** on top.

```text
User goal
   ↓
Agent invents several purposeful searches
   ↓
hunt(...)
   ↓
bounded Marktplaats searches
   ↓
deduplicate by listing ID
   ↓
found_by provenance
   ↓
compact candidate pool
   ↓
agent ranks the best matches
```

A saved hunt can then continue later:

```text
save_hunt
   ↓
run_hunt
   ↓
check_new_matches
   ↓
only listings the agent has not seen before
```

## Main tools

| Tool | What it does |
| --- | --- |
| `search_listings` | Run one filtered marketplace search. |
| `hunt` | Run up to 20 complementary searches and deduplicate the combined results. |
| `save_hunt` | Save a reusable named hunt locally. |
| `list_hunts` | List saved hunts and their seen-listing counts. |
| `run_hunt` | Re-run a saved hunt. |
| `check_new_matches` | Return only listings not seen on earlier checks. |
| `get_listing_details` | Fetch fuller details for one candidate. |
| `get_seller_info` | Fetch seller information. |
| `list_categories` | List known marketplace categories. |
| `get_category_filters` | Inspect category-specific filters. |

The inherited single-query saved-search tools are still available too.

## What is different from the upstream MCP?

The original [`gjoris/marktplaats-2dehands-mcp`](https://github.com/gjoris/marktplaats-2dehands-mcp) is a general Marktplaats / 2dehands MCP with normal search, listing details, category helpers, saved searches and optional account-oriented functionality.

This version focuses on **goal-driven marketplace hunting**:

- one `hunt` can run many complementary searches at once
- every hunt has hard fan-out / result limits so an agent cannot explode the context window
- results are deduplicated by stable listing ID
- `found_by` shows which different searches discovered the same listing
- named hunt packs can be saved and reused
- seen listing IDs are remembered locally
- `check_new_matches` returns only genuinely unseen ads
- the returned candidate payload is intentionally compact for LLM ranking
- account/login tools are not exposed in the lean MCP surface

In short:

```text
Upstream:
"Let an AI search Marktplaats."

This version:
"Give an AI a shopping goal, let it search several clever ways,
merge the evidence, remember what it saw, and come back later
with only the new interesting listings."
```

## Install into any MCP-capable agent

This is a standard **stdio MCP server**. If your agent/client can launch an MCP command, it can usually use this server.

### Option A — run directly from GitHub with `uvx`

Install [`uv`](https://docs.astral.sh/uv/) first, then:

```bash
uvx --from git+https://github.com/RT-codes/marktplaats-mcp.git \
  marktplaats-2dehands-mcp
```

### Generic MCP configuration

Most stdio-capable MCP clients use a configuration shaped roughly like this:

```json
{
  "mcpServers": {
    "marktplaats": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/RT-codes/marktplaats-mcp.git",
        "marktplaats-2dehands-mcp"
      ]
    }
  }
}
```

The exact settings screen or config-file location differs per agent, but the important part is always the same:

```text
command: uvx
args: --from git+https://github.com/RT-codes/marktplaats-mcp.git marktplaats-2dehands-mcp
transport: stdio
```

### Option B — local clone

```bash
git clone https://github.com/RT-codes/marktplaats-mcp.git
cd marktplaats-mcp
uv sync
uv run marktplaats-2dehands-mcp
```

Then point your MCP client at the local command. For example:

```json
{
  "mcpServers": {
    "marktplaats": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/marktplaats-mcp",
        "run",
        "marktplaats-2dehands-mcp"
      ]
    }
  }
}
```

## Quick single-search example

```text
search_listings(
  query="MacBook Air M2",
  price_to=800,
  sort_by="date",
  sort_order="desc",
  limit=10
)
```

Distance filtering needs a postcode:

```text
search_listings(
  query="RTX 4070 gaming pc",
  zip_code="3511",
  distance_km=50,
  price_to=1000,
  limit=10
)
```

## Example 1 — MacBook bargain hunt

### Prompt to the agent

> Find me a good used MacBook for under €700. Prefer M1 or newer, but also check vague or badly titled listings that might be bargains.

### What the agent might summarize

```text
16 searches → 91 raw matches → 58 unique listings

Top candidates
1. MacBook Air M2 2022 — €675
   Found by: macbook-m2, macbook-air, apple-laptop

2. MacBook Pro M1 16GB — €620
   Found by: macbook-m1-16gb, macbook-pro

3. "Apple laptop 2021" — €490
   Found by: vague-apple-bargain
```

Those numbers and listings are illustrative — the real output depends on what is currently for sale.

### What the technical MCP call can look like

```json
{
  "per_search_limit": 10,
  "searches": [
    {
      "label": "macbook-m2",
      "query": "MacBook M2",
      "price_to": 700
    },
    {
      "label": "macbook-m1-16gb",
      "query": "MacBook M1 16GB",
      "price_to": 700
    },
    {
      "label": "macbook-air",
      "query": "MacBook Air",
      "price_to": 700
    },
    {
      "label": "vague-apple-bargain",
      "query": "Apple laptop",
      "price_to": 700
    }
  ]
}
```

And a compact candidate returned by `hunt` is shaped roughly like:

```json
{
  "id": "m1234567890",
  "title": "MacBook Air M2 2022",
  "description": "Very good condition, battery still strong...",
  "price": "€ 675.00",
  "price_cents": 67500,
  "condition": "used",
  "location": {
    "city": "Utrecht",
    "distance_km": null
  },
  "link": "https://link.marktplaats.nl/m1234567890",
  "found_by": [
    "macbook-m2",
    "macbook-air"
  ],
  "found_by_count": 2
}
```

The important bit is that the **agent does not need to trust one search phrase**. It can search several angles and reason over one deduplicated result set.

## Example 2 — gaming PC value hunt

### Prompt to the agent

> Find me the best gaming PC under €900. GPU value matters more than RGB or a fancy case. Check normal gaming-PC listings, complete PCs with RTX cards, workstations with gaming GPUs, and vague titles that might hide a bargain.

### What the agent might summarize

```text
14 searches → 108 raw matches → 73 unique listings

Top candidates
1. Ryzen 7 + RTX 4070 PC — €850
   Strongest overall gaming value.

2. "Game computer Nvidia" with RTX 3080 — €650
   Weak title, unusually good GPU for the price.

3. Dell Precision + RTX 3070 — €575
   Found through both workstation and RTX searches.

One candidate was discovered independently by 4 searches.
```

Again, this is an illustrative result rather than a snapshot of current listings.

### What the technical MCP call can look like

```json
{
  "per_search_limit": 10,
  "searches": [
    {
      "label": "gaming-pc",
      "query": "gaming pc",
      "price_to": 900
    },
    {
      "label": "rtx-4070-pc",
      "query": "RTX 4070 pc",
      "price_to": 900
    },
    {
      "label": "rtx-3080-pc",
      "query": "RTX 3080 computer",
      "price_to": 900
    },
    {
      "label": "workstation-gpu",
      "query": "Dell Precision RTX",
      "subcategory": "desktops",
      "price_to": 900
    },
    {
      "label": "vague-nvidia-pc",
      "query": "computer Nvidia",
      "subcategory": "desktops",
      "price_to": 900
    }
  ]
}
```

A technical hunt response contains summary counters plus the deduplicated candidates:

```json
{
  "search_count": 5,
  "successful_searches": 5,
  "failed_searches": 0,
  "raw_result_count": 50,
  "unique_count": 34,
  "duplicates_removed": 16,
  "candidates": [
    {
      "id": "m0987654321",
      "title": "Ryzen 7 Gaming PC RTX 4070",
      "price": "€ 850.00",
      "price_cents": 85000,
      "found_by": [
        "gaming-pc",
        "rtx-4070-pc"
      ],
      "found_by_count": 2
    }
  ],
  "errors": []
}
```

The MCP deliberately **does not decide what is a good gaming PC**. Retrieval stays broad; the calling agent performs the semantic ranking.

## Saved hunts and “what is new?”

A useful hunt can be saved once:

```text
save_hunt(
  name="gaming-pc-under-900",
  per_search_limit=10,
  searches=[
    {"label": "gaming", "query": "gaming pc", "price_to": 900},
    {"label": "4070", "query": "RTX 4070 pc", "price_to": 900},
    {"label": "workstation", "query": "Dell Precision RTX", "price_to": 900}
  ]
)
```

Run it whenever you want:

```text
run_hunt(name="gaming-pc-under-900")
```

Or ask only for listings that have not appeared in earlier checks:

```text
check_new_matches(name="gaming-pc-under-900")
```

The first check records the currently discovered listing IDs. Later checks can therefore return only genuinely unseen candidates.

## Hunt safety bounds

Hunts are intentionally bounded for agent use:

- maximum **20 searches per hunt**
- maximum **25 requested results per individual search**
- one failed search does not abort the other searches
- results are deduplicated before they are returned to the agent

This makes it practical to let an LLM generate an adventurous search portfolio without giving it unlimited fan-out.

## Local state

Saved hunts live at:

```text
~/.local/share/marktplaats-2dehands-mcp/saved_hunts.json
```

Legacy saved searches live at:

```text
~/.local/share/marktplaats-2dehands-mcp/saved_searches.json
```

You can override the state directory with:

```text
MARKTPLAATS_MCP_STATE_DIR
```

The inherited `MARKTPLAATS_2DEHANDS_STATE_DIR` remains supported as a fallback.

## Backend note

Search currently uses the internal Adevinta / Marktplaats JSON search endpoint behind the website. It does not currently require an API key, login, headless browser or proxy for public search.

That endpoint is undocumented and may change. The retrieval code is deliberately kept behind a small internal layer so the transport can be repaired without redesigning the public MCP tool interface.

## Credits & origin

This project would not exist without the work it builds on.

### Primary upstream

[`gjoris/marktplaats-2dehands-mcp`](https://github.com/gjoris/marktplaats-2dehands-mcp) — MIT licensed.

That project provided the base MCP server, Marktplaats / 2dehands retrieval layer, category tooling, listing-detail support and saved-search foundation that this repository was adapted from.

### Earlier formatting / parsing work

The upstream project credits listing-formatting helpers and related parsing work to:

[`PonClick/marktplaats-mcp`](https://github.com/PonClick/marktplaats-mcp) — MIT licensed, © 2026 lessClick AI.

This repository preserves that attribution because parts of the inherited implementation still derive from that work.

### Additions in this repository

The `RT-codes/marktplaats-mcp` version adds the agent-oriented hunt layer, including:

- bounded multi-query hunts
- cross-search deduplication
- `found_by` provenance
- reusable saved hunt packs
- persistent seen-listing memory
- new-match detection
- a compact candidate payload designed for LLM ranking
- a lean search-focused MCP surface

Thank you to the upstream maintainers for making the original work available under MIT.

## License

MIT — see [LICENSE](LICENSE).
