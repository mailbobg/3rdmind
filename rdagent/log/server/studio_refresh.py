"""Recompute a research factor on the latest Qlib data so its signal reaches the present.

Runs as a subprocess (like studio_worker.py) so the Flask server never imports Qlib:

    python studio_refresh.py <provider_uri> <data.h5> <start> <factor.py> <name> <out dir> [market] [region]

1. Make sure ``data.h5`` holds CSI300 daily OHLCV (the same six columns RD-Agent gives factor code)
   from ``start`` to the last day in the Qlib calendar, rebuilding it when it is missing or stale.
2. Run the factor's own ``factor.py`` in a scratch directory that contains that file as ``daily_pv.h5``.
3. Validate the ``result.h5`` it writes and store it, the code and a ``meta.json`` under ``out dir``.

Prints a JSON status line on stdout; anything else goes to stderr.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["$open", "$close", "$high", "$low", "$volume", "$factor"]
FACTOR_TIMEOUT = 900


def ensure_data(provider, data_path, start, market="csi300", region="cn"):
    """Build or extend the shared daily_pv.h5 for ``market``; return (first day, last day, rows)."""
    import pandas as pd
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(Path(provider).expanduser()), region=region)
    last = pd.Timestamp(D.calendar(freq="day")[-1])
    if data_path.is_file():
        existing = pd.read_hdf(data_path)
        dates = existing.index.get_level_values("datetime")
        if pd.Timestamp(dates.max()) >= last and pd.Timestamp(dates.min()) <= pd.Timestamp(start):
            return str(dates.min().date()), str(dates.max().date()), int(len(existing))
    frame = D.features(D.instruments(market), FIELDS, start_time=start, end_time=str(last.date()), freq="day")
    if frame.index.names[0] == "instrument":
        frame = frame.swaplevel()
    frame = frame.sort_index().astype("float32")
    frame.index = frame.index.set_names(["datetime", "instrument"])
    data_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_hdf(data_path, key="data", mode="w")
    dates = frame.index.get_level_values("datetime")
    return str(dates.min().date()), str(dates.max().date()), int(len(frame))


def run_factor(code_path, data_path, name):
    """Execute factor.py the way RD-Agent does (cwd holds daily_pv.h5) and return its result frame."""
    import pandas as pd

    with tempfile.TemporaryDirectory(prefix="studio-refresh-") as tmp:
        work = Path(tmp)
        shutil.copy(code_path, work / "factor.py")
        (work / "daily_pv.h5").symlink_to(data_path.resolve())
        completed = subprocess.run([sys.executable, "factor.py"], cwd=work, capture_output=True, text=True, timeout=FACTOR_TIMEOUT)
        result = work / "result.h5"
        if completed.returncode != 0 or not result.is_file():
            tail = (completed.stderr or completed.stdout).strip().splitlines()[-3:]
            raise RuntimeError("factor.py failed: " + (" | ".join(tail) if tail else f"exit code {completed.returncode}"))
        frame = pd.read_hdf(result)
    if isinstance(frame, pd.Series):
        frame = frame.to_frame(name)
    if list(frame.index.names) != ["datetime", "instrument"]:
        raise ValueError(f"result.h5 index must be (datetime, instrument), got {list(frame.index.names)}")
    if frame.shape[1] != 1:
        raise ValueError(f"result.h5 must hold one column, got {frame.shape[1]}")
    frame.columns = [name]
    return frame.sort_index()


def main(provider, data_h5, start, code_path, name, out_dir, market="csi300", region="cn"):
    data_path, out = Path(data_h5), Path(out_dir)
    data_start, data_end, data_rows = ensure_data(provider, data_path, start, market, region)
    frame = run_factor(Path(code_path), data_path, name)
    values = frame.iloc[:, 0].dropna()
    if values.empty:
        raise ValueError("factor produced no values")
    dates = values.index.get_level_values("datetime")
    out.mkdir(parents=True, exist_ok=True)
    frame.to_hdf(out / "result.h5", key="data", mode="w")
    shutil.copy(code_path, out / "factor.py")
    meta = {
        "name": name, "start": str(dates.min().date()), "end": str(dates.max().date()), "rows": int(len(values)),
        "data": {"start": data_start, "end": data_end, "rows": data_rows},
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    return meta


if __name__ == "__main__":
    try:
        print(json.dumps({"status": "completed", **main(*sys.argv[1:9])}, ensure_ascii=False))
    except Exception as error:  # noqa: BLE001 - the server relays the message
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
