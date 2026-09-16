"""Build a Qlib data directory for a NASDAQ index universe from Yahoo Finance.

    python scripts/build-us-data.py [--index NDX] [--market nasdaq100] [--start 2007-01-01]
                                    [--target ~/.qlib/qlib_data/us_ndx] [--members-from 2008-01]

Steps: monthly membership snapshots from indexes.nasdaqomx.com -> membership intervals; daily OHLCV for
every symbol that was ever a member (plus the index itself) via yahooquery; qlib's Yahoo normalisation
(adjust by adjclose, first close = 1, `factor` and `change` columns); qlib's dump_bin into <target>;
instruments/<market>.txt from the intervals; and a studio-universe.json so the Studio lists the market.

Needs `pip install yahooquery` and the qlib source checkout next to this repository (for scripts/dump_bin.py).
Tickers no longer on Yahoo (delisted, acquired) are skipped, so the history has survivorship bias.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

SNAPSHOT_URL = "https://indexes.nasdaqomx.com/Index/WeightingData?id={index}&tradeDate={day}T00%3A00%3A00.000&timeOfDay=SOD"
BENCHMARKS = {"NDX": "^NDX"}
LABELS = {"nasdaq100": "纳斯达克 100"}


def snapshot(index: str, day: str, cache: Path) -> tuple[str, list[str]]:
    path = cache / f"{index}_{day}.json"
    if path.exists():
        return day, json.loads(path.read_text())
    for attempt in range(4):
        try:
            r = requests.post(SNAPSHOT_URL.format(index=index, day=day), headers={"Content-Length": "0", "User-Agent": "Mozilla/5.0"}, timeout=30)
            if r.status_code == 200:
                symbols = sorted({row["Symbol"].strip() for row in r.json().get("aaData", []) if row.get("Symbol")})
                if symbols:
                    path.write_text(json.dumps(symbols))
                    return day, symbols
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    return day, []


def membership(index: str, first_month: str, cache: Path) -> pd.DataFrame:
    """Membership intervals [start, end] at monthly resolution (holiday snapshots come back empty and are skipped)."""
    months = pd.date_range(first_month, pd.Timestamp.today().normalize(), freq="MS")
    days = [(d + pd.offsets.BDay(0) if d.weekday() < 5 else d + pd.offsets.BDay(1)).strftime("%Y-%m-%d") for d in months]
    days.append((pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).strftime("%Y-%m-%d"))
    with ThreadPoolExecutor(8) as pool:
        snaps = dict(pool.map(lambda d: snapshot(index, d, cache), days))
    ordered = [d for d in days if snaps[d]]
    print(f"{len(ordered)} snapshots, latest {ordered[-1]} with {len(snaps[ordered[-1]])} members", file=sys.stderr)
    rows = []
    for symbol in sorted({s for d in ordered for s in snaps[d]}):
        start = None
        for day in ordered:
            inside = symbol in snaps[day]
            if inside and start is None:
                start = day
            elif not inside and start is not None:
                rows.append((symbol, start, (pd.Timestamp(day) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")))
                start = None
        if start is not None:
            rows.append((symbol, start, "2099-12-31"))
    return pd.DataFrame(rows, columns=["symbol", "start", "end"])


def download(symbols: list[str], start: str, source: Path) -> list[str]:
    from yahooquery import Ticker

    source.mkdir(parents=True, exist_ok=True)
    todo = [s for s in symbols if not (source / f"{s}.csv").exists()]
    missing = []
    for i in range(0, len(todo), 25):
        batch = todo[i:i + 25]
        frame = None
        for _ in range(3):
            try:
                frame = Ticker(batch, asynchronous=False).history(start=start, interval="1d")
                break
            except Exception as error:  # noqa: BLE001
                print(f"retry {batch[0]}: {error}", file=sys.stderr)
                time.sleep(5)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            missing += batch
            continue
        frame = frame.reset_index()
        for symbol, g in frame.groupby("symbol"):
            g = g[["date", "open", "high", "low", "close", "adjclose", "volume"]].copy()
            g["date"] = pd.to_datetime(g["date"].astype(str).str.slice(0, 10))  # yahooquery mixes date and tz-aware datetimes
            g["symbol"] = symbol
            g.dropna(subset=["close"]).sort_values("date").to_csv(source / f"{symbol}.csv", index=False)
        missing += [s for s in batch if s not in set(frame["symbol"].unique())]
        print(f"{i + len(batch)}/{len(todo)} downloaded", file=sys.stderr)
        time.sleep(1.5)
    return missing


def normalize(source: Path, normalized: Path) -> None:
    """qlib's YahooNormalize1d for US: adjust by adjclose, scale so the first close is 1, add change."""
    normalized.mkdir(parents=True, exist_ok=True)
    for csv in sorted(source.glob("*.csv")):
        df = pd.read_csv(csv, parse_dates=["date"]).sort_values("date").drop_duplicates("date")
        if df.empty:
            continue
        # qlib computes `change` on the raw close (before the adjclose adjustment), so dividend days show the drop.
        df["change"] = df["close"].ffill() / df["close"].ffill().shift(1) - 1
        factor = (df["adjclose"] / df["close"]).ffill()
        for col in ("open", "high", "low", "close"):
            df[col] = df[col] * factor
        df["volume"] = df["volume"] / factor
        df["factor"] = factor
        first_close = df["close"].dropna().iloc[0]
        for col in ("open", "high", "low", "close", "factor"):
            df[col] = df[col] / first_close
        df["volume"] = df["volume"] * first_close
        df.to_csv(normalized / csv.name, index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", default="NDX")
    parser.add_argument("--market", default="nasdaq100")
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--members-from", default="2008-01-01")
    parser.add_argument("--target", default="~/.qlib/qlib_data/us_ndx")
    parser.add_argument("--work", default="~/.qlib/stock_data/us_build")
    args = parser.parse_args()
    target, work = Path(args.target).expanduser(), Path(args.work).expanduser()
    (work / "snapshots").mkdir(parents=True, exist_ok=True)

    intervals = membership(args.index, args.members_from, work / "snapshots")
    intervals.to_csv(work / f"{args.market}_intervals.csv", index=False)
    symbols = sorted(set(intervals.symbol)) + [BENCHMARKS.get(args.index, f"^{args.index}")]
    missing = download(symbols, args.start, work / "source")
    print(f"{len(symbols) - len(missing)} symbols downloaded, {len(missing)} not on Yahoo: {' '.join(missing)}", file=sys.stderr)
    normalize(work / "source", work / "normalized")

    dump_bin = Path(__file__).resolve().parents[2] / "qlib" / "scripts" / "dump_bin.py"
    if not dump_bin.is_file():
        print(f"qlib checkout with scripts/dump_bin.py not found at {dump_bin.parent.parent}", file=sys.stderr)
        return 1
    subprocess.run([sys.executable, str(dump_bin), "dump_all", "--data_path", str(work / "normalized"), "--qlib_dir", str(target),
                    "--include_fields", "open,close,high,low,volume,factor,change", "--date_field_name", "date",
                    "--symbol_field_name", "symbol", "--max_workers", "4"], check=True)

    calendar = (target / "calendars" / "day.txt").read_text().split()
    have = {line.split("\t")[0] for line in (target / "instruments" / "all.txt").read_text().splitlines()}
    inst = intervals[intervals.symbol.isin(have)].copy()
    inst["end"] = inst["end"].where(inst["end"] <= calendar[-1], calendar[-1])
    inst["start"] = inst["start"].where(inst["start"] >= calendar[0], calendar[0])
    inst.sort_values(["symbol", "start"]).to_csv(target / "instruments" / f"{args.market}.txt", sep="\t", header=False, index=False)
    benchmark = BENCHMARKS.get(args.index, f"^{args.index}").lower()
    (target / "studio-universe.json").write_text(json.dumps(
        {"region": "us", "label": "美股", "benchmark": benchmark, "markets": {args.market: LABELS.get(args.market, args.market.upper())}}, ensure_ascii=False))
    print(f"done: {target} ({calendar[0]} → {calendar[-1]}, {inst.symbol.nunique()} instruments in {args.market})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
