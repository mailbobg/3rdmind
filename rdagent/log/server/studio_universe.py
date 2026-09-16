"""Build the daily OHLCV input RD-Agent's factor code reads, for one Qlib instrument universe.

Runs as a subprocess (like studio_worker.py) so the Flask server never imports Qlib:

    python studio_universe.py <provider_uri> <market> <start> <end> <out dir>

Writes ``<out>/full/daily_pv.h5`` (every member of the universe over [start, end]) and
``<out>/debug/daily_pv.h5`` (the first half year, up to 100 instruments: what RD-Agent uses to smoke-test
factor code), each with a README.md, in the same six-column, (datetime, instrument) layout as the
CSI300 data the experiments were built with. Prints one JSON status line.
"""
import json
import sys
from pathlib import Path

FIELDS = ["$open", "$close", "$high", "$low", "$volume", "$factor"]


def main(provider, market, start, end, out_dir):
    import pandas as pd
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(Path(provider).expanduser()), region="cn")
    last = pd.Timestamp(D.calendar(freq="day")[-1])
    end_ts = min(pd.Timestamp(end), last)
    frame = D.features(D.instruments(market), FIELDS, start_time=start, end_time=str(end_ts.date()), freq="day")
    if frame.empty:
        raise ValueError(f"No data for universe {market!r}")
    if frame.index.names[0] == "instrument":
        frame = frame.swaplevel()
    frame = frame.sort_index().astype("float32")
    frame.index = frame.index.set_names(["datetime", "instrument"])
    out = Path(out_dir)
    (out / "full").mkdir(parents=True, exist_ok=True)
    (out / "debug").mkdir(parents=True, exist_ok=True)
    frame.to_hdf(out / "full" / "daily_pv.h5", key="data", mode="w")
    dates = frame.index.get_level_values("datetime")
    debug_end = min(pd.Timestamp(start) + pd.DateOffset(months=6), end_ts)
    instruments = frame.index.get_level_values("instrument").unique()[:100]
    debug = frame[(dates <= debug_end) & frame.index.get_level_values("instrument").isin(instruments)]
    debug.to_hdf(out / "debug" / "daily_pv.h5", key="data", mode="w")
    summary = {"market": market, "start": str(dates.min().date()), "end": str(dates.max().date()),
               "instruments": int(frame.index.get_level_values("instrument").nunique()), "rows": int(len(frame)),
               "debug": {"end": str(debug_end.date()), "instruments": int(len(instruments)), "rows": int(len(debug))}}
    readme = (f"{market.upper()} historical membership OHLCV from the local Qlib snapshot. Full: {summary['start']} to {summary['end']}"
              f" ({summary['instruments']} instruments); debug: first half year, {summary['debug']['instruments']} instruments."
              " Adjusted prices, not a live feed.\n")
    (out / "full" / "README.md").write_text(readme)
    (out / "debug" / "README.md").write_text(readme)
    (out / "meta.json").write_text(json.dumps(summary))
    return summary


if __name__ == "__main__":
    try:
        print(json.dumps({"status": "completed", **main(*sys.argv[1:6])}))
    except Exception as error:  # noqa: BLE001 - relayed by the server
        print(json.dumps({"status": "failed", "error": str(error)}))
        sys.exit(1)
