"""Parsers: turn raw JSON/CSV/SQL/YAML file text into heterogeneous label dicts.

Each parser yields plain ``dict`` records with *arbitrary* key names. The
normalizer later remaps those onto the unified :class:`AddressLabel` schema, so
parsers only need to surface address-like strings and any nearby metadata.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")
QUOTED_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")

# Repo-specific default category when a record omits one (cheap, no per-row logic).
DEFAULT_CATEGORY_BY_REPO: dict[str, str] = {
    "DefiLlama/token-lists": "Token",
    "DefiLlama/chainlist": "Chain",
}


def parse_json_records(text: str) -> Iterator[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("json_parse_error", extra={"error": str(exc)})
        return
    yield from _json_to_records(data)


def _json_to_records(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
    elif isinstance(data, dict):
        # Common shapes: {"tokens": [...]}, {"labels": [...]}, {"data": [...]}.
        for key in ("tokens", "labels", "data", "results", "entities"):
            if isinstance(data.get(key), list):
                yield from _json_to_records(data[key])
                return
        yield data


def parse_csv_records(text: str) -> Iterator[dict[str, Any]]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            yield {k: (v if v is not None else "") for k, v in row.items()}
    except csv.Error as exc:
        logger.warning("csv_parse_error", extra={"error": str(exc)})


def parse_yaml_records(text: str) -> Iterator[dict[str, Any]]:
    try:
        import yaml  # optional dependency
    except ImportError:
        logger.warning("yaml_skipped", extra={"reason": "pyyaml not installed"})
        return
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 - yaml can raise many error types
        logger.warning("yaml_parse_error", extra={"error": str(exc)})
        return
    yield from _json_to_records(data)


def parse_sql_records(text: str) -> Iterator[dict[str, Any]]:
    """Best-effort extractor for dbt seed SQL (INSERT ... VALUES rows).

    In SQL, addresses are single-quoted string literals, so we isolate the
    quoted token that *is* an address, then treat the remaining quoted tokens as
    (name, category, entity) in order."""
    for line in text.splitlines():
        quotes = [m[0] or m[1] for m in QUOTED_RE.findall(line)]
        if not quotes:
            continue
        addr_candidates = [q for q in quotes if ADDRESS_RE.fullmatch(q)]
        if addr_candidates:
            addr = addr_candidates[0]
            meta = [q for q in quotes if q != addr]
        else:
            addrs = ADDRESS_RE.findall(line)
            if not addrs:
                continue
            addr = addrs[0]
            meta = quotes
        if not meta:
            continue
        name = meta[0]
        category = meta[1] if len(meta) > 1 else ""
        entity = meta[2] if len(meta) > 2 else name
        yield {"address": addr, "name_tag": name, "category": category, "entity": entity}


def extract_records(text: str, path: str, source: str = "") -> Iterator[dict[str, Any]]:
    """Dispatch to the right parser by file extension; tag a repo default category."""
    lowered = path.lower()
    if lowered.endswith(".json"):
        records = parse_json_records(text)
    elif lowered.endswith(".csv"):
        records = parse_csv_records(text)
    elif lowered.endswith((".yaml", ".yml")):
        records = parse_yaml_records(text)
    elif lowered.endswith(".sql"):
        records = parse_sql_records(text)
    else:
        return

    default_cat = DEFAULT_CATEGORY_BY_REPO.get(source, "")
    for rec in records:
        if default_cat and not rec.get("category") and not rec.get("type"):
            rec = {**rec, "category": default_cat}
        yield rec
