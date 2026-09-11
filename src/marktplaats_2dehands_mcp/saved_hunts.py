"""Persistent hunt state stored as a tiny local JSON file."""

import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_STATE_DIR = Path(
    os.environ.get("MARKTPLAATS_MCP_STATE_DIR")
    or os.environ.get("MARKTPLAATS_2DEHANDS_STATE_DIR")
    or Path.home() / ".local" / "share" / "marktplaats-2dehands-mcp"
)

DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / "saved_hunts.json"


def _load(path: Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "hunts": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "hunts": {}}

    data.setdefault("version", 1)
    data.setdefault("hunts", {})
    return data


def _save(data: dict[str, Any], path: Path = DEFAULT_STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def save_hunt(
    name: str,
    searches: list[dict[str, Any]],
    per_search_limit: int = 10,
    path: Path = DEFAULT_STATE_FILE,
) -> dict[str, Any]:
    """Create or replace a named hunt."""
    data = _load(path)

    data["hunts"][name] = {
        "searches": searches,
        "per_search_limit": per_search_limit,
        "created_at": time.time(),
        "last_checked_at": None,
        "seen_ids": [],
    }

    _save(data, path)

    return {
        "name": name,
        "saved": True,
        "search_count": len(searches),
        "per_search_limit": per_search_limit,
    }


def list_hunts(path: Path = DEFAULT_STATE_FILE) -> list[dict[str, Any]]:
    data = _load(path)

    return [
        {
            "name": name,
            "search_count": len(entry.get("searches", [])),
            "per_search_limit": entry.get("per_search_limit", 10),
            "created_at": entry.get("created_at"),
            "last_checked_at": entry.get("last_checked_at"),
            "seen_count": len(entry.get("seen_ids", [])),
        }
        for name, entry in data["hunts"].items()
    ]


def get_hunt(
    name: str,
    path: Path = DEFAULT_STATE_FILE,
) -> dict[str, Any] | None:
    return _load(path)["hunts"].get(name)


def record_check(
    name: str,
    seen_ids: list[str],
    path: Path = DEFAULT_STATE_FILE,
) -> None:
    """Record the current candidate IDs as seen."""
    data = _load(path)

    if name not in data["hunts"]:
        return

    entry = data["hunts"][name]
    entry["last_checked_at"] = time.time()

    # Preserve insertion order while avoiding duplicates.
    combined = list(
        dict.fromkeys([
            *entry.get("seen_ids", []),
            *seen_ids,
        ])
    )

    # Prevent state from growing forever.
    entry["seen_ids"] = combined[-5000:]

    _save(data, path)
