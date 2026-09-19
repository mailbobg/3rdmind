"""Extra daily fields for A-share factor code, beyond OHLCV: turnover, valuation, float cap, ST flag.

Source: baostock (free, no key), one query per instrument, cached per instrument under
``<traces>/studio_data/extra/baostock/<CODE>.csv`` and extended incrementally. The fields are joined onto
the OHLCV frames the Studio exports (``daily_pv.h5`` for research, ``daily_pv_latest.<market>.h5`` for
recomputation), so factor code sees them as ordinary ``$`` columns:

    $turnover   daily turnover rate as a fraction of float shares (baostock ``turn`` / 100)
    $pe_ttm     price / trailing-12-month earnings (negative when earnings are negative)
    $pb         price / book (most recent quarter)
    $ps_ttm     price / trailing-12-month sales
    $pcf_ttm    price / trailing-12-month operating cash flow
    $float_cap  float market cap in yuan: raw close × raw volume ÷ turnover rate
    $amount     traded value in yuan
    $is_st      1 when the name carried an ST / *ST flag that day

Runs as a subprocess so the Flask server never imports the fetch client:

    python studio_extra.py fetch <cache dir> <codes file> <start> <end>

``codes file`` holds one Qlib instrument code (SH600000) per line. Prints one JSON status line.
"""
import json
import sys
import time
from pathlib import Path

EXTRA_COLUMNS = ["$turnover", "$pe_ttm", "$pb", "$ps_ttm", "$pcf_ttm", "$float_cap", "$amount", "$is_st"]
BS_FIELDS = "date,code,close,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
README_NOTE = (
    "\nExtra columns (from baostock, joined by date and instrument; NaN where the source has no row):"
    " $turnover = daily turnover rate as a fraction of float shares; $pe_ttm, $pb, $ps_ttm, $pcf_ttm = valuation"
    " ratios (price over trailing-12-month earnings / most-recent-quarter book / TTM sales / TTM operating cash"
    " flow, negative when the denominator is negative); $float_cap = float market cap in yuan; $amount = traded"
    " value in yuan; $is_st = 1 on days the name carried an ST flag. These open turnover-structure, valuation"
    " and size mechanisms that OHLCV alone cannot express; treat $pe_ttm and friends as slow-moving (they change"
    " with price daily and with earnings quarterly).\n"
)


def bs_code(code: str) -> str:
    """Qlib SH600000 → baostock sh.600000."""
    return f"{code[:2].lower()}.{code[2:]}"


def qlib_code(code: str) -> str:
    """baostock sh.600000 → Qlib SH600000."""
    return code.replace(".", "").upper()


def cache_path(cache: Path, code: str) -> Path:
    return cache / f"{code.upper()}.csv"


def fetch(cache: Path, codes, start: str, end: str, log=lambda *_: None) -> dict:
    """Fetch (or extend) every instrument's cached rows up to ``end``; returns counts."""
    import baostock as bs
    import pandas as pd

    cache.mkdir(parents=True, exist_ok=True)
    session = bs.login()
    if session.error_code != "0":
        raise RuntimeError(f"baostock login failed: {session.error_msg}")
    done, updated, empty, failed = 0, 0, 0, []
    try:
        for i, code in enumerate(codes):
            path = cache_path(cache, code)
            since = start
            existing = None
            if path.is_file():
                existing = pd.read_csv(path, dtype=str)
                if len(existing):
                    last = existing["date"].max()
                    if last >= end:
                        done += 1
                        continue
                    since = str((pd.Timestamp(last) + pd.Timedelta(days=1)).date())
            rows = []
            for attempt in range(3):
                try:
                    rs = bs.query_history_k_data_plus(bs_code(code), BS_FIELDS, start_date=since, end_date=end, frequency="d", adjustflag="3")
                    if rs.error_code != "0":
                        raise RuntimeError(rs.error_msg)
                    while rs.next():
                        rows.append(rs.get_row_data())
                    break
                except Exception as error:  # noqa: BLE001 - retried, then reported
                    if attempt == 2:
                        failed.append(f"{code}: {str(error)[:80]}")
                    time.sleep(2 * (attempt + 1))
            if rows:
                new = pd.DataFrame(rows, columns=BS_FIELDS.split(","))
                merged = pd.concat([existing, new]) if existing is not None and len(existing) else new
                merged = merged.drop_duplicates("date").sort_values("date")
                merged.to_csv(path, index=False)
                updated += 1
            elif existing is None:
                path.write_text(",".join(BS_FIELDS.split(",")) + "\n")  # remember the empty answer
                empty += 1
            done += 1
            if (i + 1) % 50 == 0:
                log(f"{i + 1}/{len(codes)} instruments")
    finally:
        bs.logout()
    return {"instruments": len(codes), "done": done, "updated": updated, "empty": empty, "failed": failed[:20], "failed_count": len(failed)}


def load(cache: Path, codes, start=None, end=None):
    """The extra fields for ``codes`` as a (datetime, instrument) frame with EXTRA_COLUMNS, from the cache."""
    import numpy as np
    import pandas as pd

    frames = []
    for code in codes:
        path = cache_path(cache, code.upper())
        if not path.is_file():
            continue
        raw = pd.read_csv(path)
        if raw.empty:
            continue
        raw["instrument"] = code.upper()
        frames.append(raw)
    if not frames:
        return pd.DataFrame(columns=EXTRA_COLUMNS, index=pd.MultiIndex.from_tuples([], names=["datetime", "instrument"]))
    raw = pd.concat(frames, ignore_index=True)
    raw["datetime"] = pd.to_datetime(raw["date"])
    numeric = ["close", "volume", "amount", "turn", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "isST"]
    for column in numeric:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    turn = raw["turn"] / 100.0
    out = pd.DataFrame({
        "datetime": raw["datetime"], "instrument": raw["instrument"],
        "$turnover": turn,
        "$pe_ttm": raw["peTTM"], "$pb": raw["pbMRQ"], "$ps_ttm": raw["psTTM"], "$pcf_ttm": raw["pcfNcfTTM"],
        "$float_cap": np.where(turn > 0, raw["close"] * raw["volume"] / turn.where(turn > 0), np.nan),
        "$amount": raw["amount"], "$is_st": raw["isST"].fillna(0).astype(float),
    })
    if start is not None:
        out = out[out["datetime"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["datetime"] <= pd.Timestamp(end)]
    return out.set_index(["datetime", "instrument"]).sort_index().astype("float32")


def attach(frame, cache: Path):
    """Left-join the extra fields onto an OHLCV frame indexed (datetime, instrument); unchanged when the cache
    holds nothing for these instruments. Returns (frame, attached: bool)."""
    if not cache.is_dir():
        return frame, False
    codes = frame.index.get_level_values("instrument").unique()
    extra = load(cache, codes, frame.index.get_level_values("datetime").min(), frame.index.get_level_values("datetime").max())
    if extra.empty:
        return frame, False
    joined = frame.join(extra, how="left")
    return joined, True


def main(argv):
    command = argv[0] if argv else ""
    if command != "fetch" or len(argv) != 5:
        raise ValueError("usage: studio_extra.py fetch <cache dir> <codes file> <start> <end>")
    cache, codes_file, start, end = Path(argv[1]), Path(argv[2]), argv[3], argv[4]
    codes = [line.strip() for line in codes_file.read_text().splitlines() if line.strip()]
    return fetch(cache, codes, start, end, log=lambda msg: print(msg, file=sys.stderr, flush=True))


if __name__ == "__main__":
    try:
        print(json.dumps({"status": "completed", **main(sys.argv[1:])}, ensure_ascii=False))
    except Exception as error:  # noqa: BLE001 - relayed by the server
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
