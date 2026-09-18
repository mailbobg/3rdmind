"""Single-factor analysis for the Studio factor library.

Runs as a subprocess (like studio_worker.py) so the Flask server never imports Qlib:

    python studio_analysis.py <factor workspace> <provider_uri> <market> <output json> [region]

Writes coverage and the daily information coefficient of the factor against the next-day
close-to-close return, the label Qlib's templates use with close execution.
"""
import json
import math
import sys
from pathlib import Path


def factor_series(workspace):
    import pandas as pd

    frame = pd.read_hdf(Path(workspace) / "result.h5")
    if isinstance(frame, pd.Series):
        frame = frame.to_frame()
    series = frame.iloc[:, 0]
    if list(series.index.names) != ["datetime", "instrument"]:
        raise ValueError("factor index must be (datetime, instrument)")
    return series.dropna().sort_index()


def daily_ic(factor, label):
    """Per-day Pearson and Spearman correlation between factor values and the label."""
    frame = factor.rename("factor").to_frame().join(label.rename("label"), how="inner").dropna()
    if frame.empty:
        raise ValueError("factor and label share no observations")
    by_day = frame.groupby(level="datetime")
    ic = by_day.apply(lambda d: d["factor"].corr(d["label"]) if len(d) > 5 else float("nan")).dropna()
    rank_ic = by_day.apply(lambda d: d["factor"].corr(d["label"], method="spearman") if len(d) > 5 else float("nan")).dropna()
    return ic, rank_ic


def summarize(ic, rank_ic, coverage_start, coverage_end, universe_rows):
    def stats(series):
        mean, std = float(series.mean()), float(series.std(ddof=1)) if len(series) > 1 else float("nan")
        return {
            "mean": mean,
            "std": std,
            "ir": mean / std if std and math.isfinite(std) and std > 0 else None,
            "positive_ratio": float((series > 0).mean()),
        }
    monthly = (
        ic.groupby(ic.index.to_period("M")).mean().rename("ic").to_frame()
        .join(rank_ic.groupby(rank_ic.index.to_period("M")).mean().rename("rank_ic"))
    )
    return {
        "coverage": {"start": str(coverage_start.date()), "end": str(coverage_end.date())},
        "days": int(len(ic)),
        "rows": int(universe_rows),
        "ic": stats(ic),
        "rank_ic": stats(rank_ic),
        "monthly": [
            {"month": str(period), "ic": None if math.isnan(row["ic"]) else float(row["ic"]),
             "rank_ic": None if math.isnan(row["rank_ic"]) else float(row["rank_ic"])}
            for period, row in monthly.iterrows()
        ],
    }


def run(workspace, provider_uri, market, region="cn"):
    checkout = Path(__file__).resolve().parents[4] / "qlib"
    if checkout.is_dir():
        sys.path.insert(0, str(checkout))
    import qlib
    from qlib.data import D

    factor = factor_series(workspace)
    dates = factor.index.get_level_values("datetime")
    start, end = dates.min(), dates.max()
    qlib.init(provider_uri=str(Path(provider_uri).expanduser()), region=region)
    instruments = D.instruments(market)
    universe = set(D.list_instruments(instruments, start_time=start, end_time=end, as_list=True))
    factor = factor[factor.index.get_level_values("instrument").isin(universe)]
    if factor.empty:
        raise ValueError(f"factor has no observations inside {market}")
    label = D.features(instruments, ["Ref($close, -2)/Ref($close, -1) - 1"], start_time=start, end_time=end, freq="day").iloc[:, 0]
    if label.index.names[0] == "instrument":
        label = label.swaplevel(0, 1)
    label = label.sort_index()
    ic, rank_ic = daily_ic(factor, label)
    return summarize(ic, rank_ic, start, end, len(factor))


def main(argv):
    workspace, provider_uri, market, output = argv[:4]
    region = argv[4] if len(argv) > 4 else "cn"
    try:
        result = {"status": "completed", **run(workspace, provider_uri, market, region)}
    except Exception as error:  # the caller shows the message; a traceback on stderr helps debugging
        import traceback
        traceback.print_exc()
        result = {"status": "failed", "error": str(error)}
    Path(output).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
