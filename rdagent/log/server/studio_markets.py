"""The instrument universes the Studio can research and backtest on, and the Qlib data behind each.

The default provider (``QLIB_PROVIDER_URI``, the A-share snapshot) contributes every ``instruments/*.txt`` it
holds. Any sibling directory of it that carries a ``studio-universe.json`` contributes its own markets::

    {"region": "us", "label": "美股", "benchmark": "^ndx", "markets": {"nasdaq100": "纳斯达克 100"}}

Each universe resolves to the provider directory, Qlib region, benchmark and the exchange rules a backtest
should use (A-shares: 9.5% limit, 5-yuan minimum commission; US: no limit, 1-dollar minimum). Everything else
in the Studio asks this module instead of assuming ``cn_data``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CN_LABELS = {"csi300": "沪深300", "csi500": "中证500", "csi1000": "中证1000", "all": "全部 A 股"}
CN_BENCHMARKS = {"csi300": "SH000300", "csi500": "SH000905", "csi1000": "SH000852", "all": "SH000300"}
CN_ORDER = ["csi300", "csi500", "csi1000", "all"]
# Exchange rules per region: A-shares carry the 9.5% price limit, a 5-yuan minimum commission and a sell-side
# cost that includes stamp duty; US large caps trade without a limit at near-zero brokerage.
RULES = {"cn": {"limit_threshold": 0.095, "min_cost": 5, "open_cost": 0.0005, "close_cost": 0.0015},
         "us": {"limit_threshold": None, "min_cost": 1, "open_cost": 0.0001, "close_cost": 0.0001}}
MANIFEST = "studio-universe.json"


def default_provider() -> Path:
    return Path(os.environ.get("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser()


def _instruments(provider: Path) -> set[str]:
    return {p.stem for p in (provider / "instruments").glob("*.txt")}


def _extra_providers(default: Path) -> list[tuple[Path, dict]]:
    """Sibling data directories that declare their universes, in name order."""
    found = []
    parent = default.parent
    if not parent.is_dir():
        return found
    for folder in sorted(parent.iterdir()):
        manifest = folder / MANIFEST
        if folder == default or not manifest.is_file():
            continue
        try:
            found.append((folder, json.loads(manifest.read_text())))
        except ValueError:
            continue
    return found


_CACHE: dict = {"key": None, "at": 0.0, "value": None}
_CACHE_TTL = 15.0


def universes() -> list[dict]:
    """Every known universe: A-share lists first (small to large), then each declared provider's markets.

    Reading the instrument lists (thousands of lines for the all-market ones) costs ~80 ms, and list endpoints
    ask per record, so the answer is cached for a few seconds per default provider."""
    import time

    default = default_provider()
    # The key carries the directory mtimes, so adding a manifest or an instruments file invalidates at once.
    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0
    siblings = [p for p in (default.parent.iterdir() if default.parent.is_dir() else []) if p.is_dir()]
    key = (str(default), mtime(default / "instruments"), mtime(default.parent), tuple(mtime(p / MANIFEST) for p in siblings), tuple(mtime(p / "instruments") for p in siblings))
    if _CACHE["value"] is not None and _CACHE["key"] == key and time.monotonic() - _CACHE["at"] < _CACHE_TTL:
        return _CACHE["value"]
    value = _universes(default)
    _CACHE.update({"key": key, "at": time.monotonic(), "value": value})
    return value


def _universes(default: Path) -> list[dict]:
    # Without any Qlib data yet, still offer CSI300 so the rest of the Studio reports "data missing" instead of
    # "unknown universe".
    names = _instruments(default) or {"csi300"}
    out = []
    for market in [m for m in CN_ORDER if m in names] + sorted(names - set(CN_ORDER)):
        out.append(_record(market, CN_LABELS.get(market, market.upper()), default, "cn", CN_BENCHMARKS.get(market, "SH000300"), "A 股"))
    for folder, manifest in _extra_providers(default):
        region = str(manifest.get("region") or "cn").lower()
        present = _instruments(folder)
        for market, label in (manifest.get("markets") or {}).items():
            if market in present:
                out.append(_record(market, str(label or market.upper()), folder, region, str(manifest.get("benchmark") or ""), str(manifest.get("label") or region.upper())))
    return out


def _members(provider: Path, market: str) -> int | None:
    """How many instruments the universe holds on its last day (None when the list cannot be read)."""
    path = provider / "instruments" / f"{market}.txt"
    if not path.is_file():
        return None
    ends = []
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            ends.append(parts[2].strip())
    if not ends:
        return None
    last = max(ends)
    return sum(1 for e in ends if e == last)


def _record(market, label, provider: Path, region, benchmark, group) -> dict:
    rules = RULES.get(region, RULES["cn"])
    return {"market": market, "label": label, "group": group, "provider_uri": str(provider), "region": region,
            "benchmark": benchmark, "limit_threshold": rules["limit_threshold"], "min_cost": rules["min_cost"],
            "open_cost": rules["open_cost"], "close_cost": rules["close_cost"], "members": _members(provider, market)}


def universe(market: str) -> dict:
    market = (market or "").strip().lower()
    for record in universes():
        if record["market"] == market:
            return record
    raise ValueError(f"Unknown universe {market!r}; available: {', '.join(r['market'] for r in universes())}")


def markets() -> list[str]:
    return [r["market"] for r in universes()]


REGION_LABELS = {"cn": "A 股", "us": "美股"}


def region_of(market: str | None) -> str:
    """The region a market belongs to; unknown or unmarked records count as A-shares."""
    market = (market or "").strip().lower()
    records = universes()
    index = _CACHE.get("regions")
    if index is None or _CACHE.get("regions_for") is not records:
        index = {r["market"]: r["region"] for r in records}
        _CACHE["regions"], _CACHE["regions_for"] = index, records
    return index.get(market, "cn")


def regions() -> list[dict]:
    """The workspaces the Studio offers: one per region with data, plus "us" as a placeholder when there is no
    US data yet (so the UI can offer to build it). Each carries its provider directory and calendar span."""
    seen: dict[str, dict] = {}
    for record in universes():
        region = record["region"]
        entry = seen.setdefault(region, {"region": region, "label": REGION_LABELS.get(region, region.upper()),
                                         "provider_uri": record["provider_uri"], "markets": []})
        entry["markets"].append(record["market"])
    for region in ("cn", "us"):
        seen.setdefault(region, {"region": region, "label": REGION_LABELS[region], "provider_uri": None, "markets": []})
    out = []
    for region in ["cn", "us"] + sorted(r for r in seen if r not in ("cn", "us")):
        entry = seen[region]
        dates: list[str] = []
        if entry["provider_uri"]:
            calendar = Path(entry["provider_uri"]) / "calendars" / "day.txt"
            dates = calendar.read_text().split() if calendar.is_file() else []
        entry.update({"ready": bool(dates) and bool(entry["markets"]), "start": dates[0] if dates else None, "end": dates[-1] if dates else None})
        out.append(entry)
    return out


def provider_for(region: str) -> Path | None:
    for entry in regions():
        if entry["region"] == region and entry["provider_uri"]:
            return Path(entry["provider_uri"])
    return None
