"""Single-factor analysis for the Studio factor library.

Runs as a subprocess (like studio_worker.py) so the Flask server never imports Qlib:

    python studio_analysis.py <factor workspace> <provider_uri> <market> <output json> [region]

Writes coverage and the daily information coefficient of the factor against the next-day
close-to-close return (the label Qlib's templates use with close execution), plus the same at 5, 10
and 20-day horizons, each with a t statistic, and against the size-neutral residual of the return.
"""
import json
import math
import sys
from pathlib import Path


def read_result(path):
    """The factor frame in a result.h5, taking the first dataset when the file holds several."""
    import pandas as pd

    try:
        return pd.read_hdf(path)
    except ValueError:
        with pd.HDFStore(path, mode="r") as store:
            return store[store.keys()[0]]


def factor_series(workspace):
    import pandas as pd

    frame = read_result(Path(workspace) / "result.h5")
    if isinstance(frame, pd.Series):
        frame = frame.to_frame()
    series = frame.iloc[:, 0]
    if list(series.index.names) != ["datetime", "instrument"]:
        raise ValueError("factor index must be (datetime, instrument)")
    valid = series.dropna()
    if valid.empty:
        dates = series.index.get_level_values("datetime")
        raise ValueError(f"factor has no valid values: all {len(series)} rows are NaN over {dates.min().date()} → {dates.max().date()} "
                         "(a rolling window longer than the data, or a formula that never resolves)")
    return valid.sort_index()


def daily_ic(factor, label):
    """Per-day Pearson and Spearman correlation between factor values and the label."""
    frame = factor.rename("factor").to_frame().join(label.rename("label"), how="inner").dropna()
    if frame.empty:
        raise ValueError("factor and label share no observations")
    by_day = frame.groupby(level="datetime")
    ic = by_day.apply(lambda d: d["factor"].corr(d["label"]) if len(d) > 5 else float("nan")).dropna()
    rank_ic = by_day.apply(lambda d: d["factor"].corr(d["label"], method="spearman") if len(d) > 5 else float("nan")).dropna()
    return ic, rank_ic


HORIZONS = (1, 5, 10, 20)
# |t| of the Rank IC at the best horizon: what a factor has to clear to count as a signal, and as weak.
T_SIGNAL, T_WEAK = 3.0, 2.0


def label_expression(horizon):
    """Forward return of buying at the next close and holding ``horizon`` days, as a Qlib expression."""
    return f"Ref($close, -{horizon + 1})/Ref($close, -1) - 1"


def residualize(label, size):
    """Per day, the part of ``label`` a cross-sectional regression on log ``size`` (traded value) cannot explain.

    Removes the market (the intercept) and the size tilt, so the IC against it says what the factor knows
    beyond "big versus small" and "up day versus down day".
    """
    import numpy as np

    frame = label.rename("y").to_frame().join(np.log(size.clip(lower=1)).rename("x"), how="inner").dropna()
    if frame.empty:
        return frame["y"]

    def fit(day):
        if len(day) < 10 or day["x"].std() == 0:
            return day["y"] - day["y"].mean()
        slope, intercept = np.polyfit(day["x"], day["y"], 1)
        return day["y"] - (intercept + slope * day["x"])

    return frame.groupby(level="datetime", group_keys=False).apply(fit)


def stats(series, horizon=1):
    """Mean, dispersion, ICIR and a t statistic; overlapping labels at ``horizon`` > 1 leave about n / horizon
    independent days, and the t is scaled to that rather than to the raw count."""
    if series is None or len(series) == 0:
        return None
    mean, std = float(series.mean()), float(series.std(ddof=1)) if len(series) > 1 else float("nan")
    ir = mean / std if std and math.isfinite(std) and std > 0 else None
    return {
        "mean": mean,
        "std": std,
        "ir": ir,
        "t": ir * math.sqrt(len(series) / horizon) if ir is not None else None,
        "positive_ratio": float((series > 0).mean()),
    }


def verdict(horizons):
    """The horizon where the Rank IC is most clearly non-zero, and whether that clears the signal / weak bars."""
    scored = [(h["days"], abs(h["rank_ic"]["t"])) for h in horizons if h.get("rank_ic") and h["rank_ic"].get("t") is not None]
    if not scored:
        return None
    best, t = max(scored, key=lambda pair: pair[1])
    return {"best_horizon": best, "t": t, "level": "signal" if t >= T_SIGNAL else "weak" if t >= T_WEAK else "noise"}


def summarize(ic, rank_ic, coverage_start, coverage_end, universe_rows, horizons=None):
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
        "horizons": horizons or [],
        "verdict": verdict(horizons or []),
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
    fields = [label_expression(h) for h in HORIZONS] + ["Ref(Mean($close * $volume, 20), 1)"]
    frame = D.features(instruments, fields, start_time=start, end_time=end, freq="day")
    frame.columns = [*HORIZONS, "size"]
    if frame.index.names[0] == "instrument":
        frame = frame.swaplevel(0, 1)
    frame = frame.sort_index()
    horizons = []
    for h in HORIZONS:
        h_ic, h_rank_ic = daily_ic(factor, frame[h])
        residual = residualize(frame[h], frame["size"])
        _, residual_rank_ic = daily_ic(factor, residual) if not residual.empty else (None, None)
        horizons.append({"days": h, "ic": stats(h_ic, h), "rank_ic": stats(h_rank_ic, h), "residual_rank_ic": stats(residual_rank_ic, h)})
    ic, rank_ic = daily_ic(factor, frame[1])
    return summarize(ic, rank_ic, start, end, len(factor), horizons)


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
