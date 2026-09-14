"""Isolated Qlib factor-portfolio worker for the local research studio.

Reads each selected factor workspace's ``result.h5`` file, combines the
factors into a single ranked signal, and runs a TopkDropoutStrategy backtest
over the requested date range.
"""
import json
import math
import sys
import traceback
from pathlib import Path


def validate_config(config):
    from datetime import date
    result = dict(config)
    for key in ("start", "end"):
        date.fromisoformat(result[key])
    if result["start"] >= result["end"]:
        raise ValueError("Start date must be earlier than end date")
    for key, default, lower, upper in (
        ("topk", 10, 1, 500), ("n_drop", 2, 0, 500),
        ("account", 1000000, 1000, 10000000000),
        ("open_cost", 0.0005, 0, 0.1), ("close_cost", 0.0015, 0, 0.1),
    ):
        value = float(result.get(key, default))
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"Invalid {key}")
        if key in ("topk", "n_drop") and not value.is_integer():
            raise ValueError(f"{key} must be an integer")
        result[key] = int(value) if key in ("topk", "n_drop") else value
    if result["n_drop"] > result["topk"]:
        raise ValueError("n_drop cannot exceed topk")
    if result.get("market") not in ("csi300", "csi500", "all"):
        raise ValueError("Unsupported instrument universe")
    factors = result.get("factors", [])
    if not isinstance(factors, list) or not 1 <= len(factors) <= 20:
        raise ValueError("Select 1 to 20 factors")
    total = 0
    for factor in factors:
        for key in ("name", "path"):
            if not isinstance(factor.get(key), str) or not factor[key].strip():
                raise ValueError(f"Missing factor {key}")
        weight = float(factor["weight"])
        if not math.isfinite(weight):
            raise ValueError("Invalid factor weight")
        total += abs(weight)
    if total == 0:
        raise ValueError("At least one factor must have a non-zero weight")
    return result


def write_json(path, data):
    target = Path(path)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(target)


def trading_day_on_or_before(calendar, date):
    """Return the latest trading day in ``calendar`` that is <= ``date``.

    ``calendar`` is a sorted pandas DatetimeIndex of trading days. Raises
    ValueError if ``date`` precedes the first entry in ``calendar``.
    """
    import pandas as pd

    target = pd.Timestamp(date)
    eligible = calendar[calendar <= target]
    if not len(eligible):
        raise ValueError(f"No trading day on or before {target.date()}")
    return eligible[-1]


def require_signal_coverage(score_index_dates, start, end):
    """Ensure the factor signal index actually spans the requested backtest window.

    ``score_index_dates`` may be a pandas DatetimeIndex/Series of the datetime
    level of the score index. Missing coverage is an error, never silently
    patched (e.g. by holding the last book past the end of signal history).
    """
    import pandas as pd

    dates = pd.DatetimeIndex(score_index_dates)
    first = dates.min()
    last = dates.max()
    if last < pd.Timestamp(end) or first > pd.Timestamp(start):
        raise ValueError(
            f"Factor signals cover {first.date()} to {last.date()}; choose a window inside that range"
        )


def load_factor_frame(factor, start, end):
    """Read one factor workspace's result.h5 as a single-column frame named after the factor."""
    import pandas as pd

    source = Path(factor["path"]) / "result.h5"
    if not source.is_file():
        raise ValueError(f"Factor {factor['name']} has no result.h5 at {factor['path']}")
    frame = pd.read_hdf(source)
    if isinstance(frame, pd.Series):
        frame = frame.to_frame()
    if frame.empty or frame.shape[1] == 0:
        raise ValueError(f"Factor {factor['name']} result is empty")
    frame = frame.iloc[:, [0]]
    frame.columns = [factor["name"]]
    if list(frame.index.names) != ["datetime", "instrument"]:
        raise ValueError(f"Factor {factor['name']} index must be (datetime, instrument)")
    dates = frame.index.get_level_values("datetime")
    return frame[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]


def run(config):
    # Use the user's adjacent Qlib checkout, not an unrelated installed checkout.
    checkout = Path(__file__).resolve().parents[4] / "qlib"
    if checkout.is_dir():
        sys.path.insert(0, str(checkout))
    import numpy as np
    import pandas as pd
    import qlib
    from qlib.data import D
    from qlib.backtest import backtest

    provider = Path(config["provider_uri"]).expanduser().resolve()
    if not (provider / "calendars" / "day.txt").is_file():
        raise ValueError(f"Qlib daily data is missing: {provider}")
    qlib.init(provider_uri=str(provider), region="cn")
    calendar = D.calendar(freq="day")
    if pd.Timestamp(config["end"]) > calendar[-1] or pd.Timestamp(config["start"]) < calendar[0]:
        raise ValueError(f"Requested dates outside data coverage: {calendar[0]} to {calendar[-1]}")
    # TopkDropoutStrategy reads the previous trading day's prediction.
    prior = calendar[calendar < pd.Timestamp(config["start"])]
    if not len(prior):
        raise ValueError("At least one trading day of signal history is required")
    factors = config["factors"]
    frames = [load_factor_frame(f, prior[-1], config["end"]) for f in factors]
    features = pd.concat(frames, axis=1).sort_index()
    if features.empty:
        raise ValueError("No factor observations for this date range")
    universe = set(D.list_instruments(D.instruments(config["market"]),
                                      start_time=prior[-1], end_time=config["end"], as_list=True))
    features = features[features.index.get_level_values("instrument").isin(universe)]
    if features.empty:
        raise ValueError("No factor observations inside the selected universe")
    # Require all selected factors on a row; do not silently treat missing data as zero.
    ranks = features.groupby(level="datetime").rank(pct=True)
    weights = np.array([float(f["weight"]) for f in factors])
    score = ranks.mul(weights, axis=1).sum(axis=1, min_count=len(factors)) / abs(weights).sum()
    score = score.dropna().sort_index()
    if score.empty:
        raise ValueError("Selected factors have no complete observations")
    end_day = trading_day_on_or_before(calendar, config["end"])
    require_signal_coverage(score.index.get_level_values("datetime"), prior[-1], end_day)
    strategy = {"class": "TopkDropoutStrategy", "module_path": "qlib.contrib.strategy",
                "kwargs": {"signal": score, "topk": config["topk"], "n_drop": config["n_drop"]}}
    portfolios, _ = backtest(
        start_time=config["start"], end_time=config["end"], strategy=strategy,
        executor={"class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
                  "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True}},
        account=config["account"], benchmark=config.get("benchmark", "SH000300"),
        exchange_kwargs={"freq": "day", "limit_threshold": 0.095, "deal_price": "close",
                         "open_cost": config["open_cost"], "close_cost": config["close_cost"], "min_cost": 5},
    )
    report, _ = portfolios["1day"]
    if report.empty:
        raise ValueError("Backtest returned no daily report")
    net = report["return"] - report["cost"]
    equity = (1 + net).cumprod()
    benchmark = (1 + report["bench"]).cumprod()
    peak = equity.cummax().clip(lower=1)
    drawdown = equity / peak - 1
    vol = net.std(ddof=1)
    sharpe = float(net.mean() / vol * np.sqrt(252)) if vol > 0 else None
    rows = []
    for day, row in report.iterrows():
        rows.append({"date": str(day.date()), "equity": float(equity.loc[day]),
                     "benchmark": float(benchmark.loc[day]), "drawdown": float(drawdown.loc[day]),
                     "return": float(net.loc[day]), "cost": float(row["cost"]),
                     "turnover": float(row["turnover"]), "account": float(row["account"])})
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return clean({"metrics": {"total_return": float(equity.iloc[-1] - 1),
                    "annualized_return": float(equity.iloc[-1] ** (252 / len(net)) - 1),
                    "sharpe": sharpe, "max_drawdown": float(drawdown.min()),
                    "benchmark_return": float(benchmark.iloc[-1] - 1), "days": len(net)},
                  "rows": rows, "config": config,
                  "method": "Net-of-cost compounded returns; 252 trading days; Sharpe risk-free rate = 0. Previous-day signals, close execution."})


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    try:
        config = validate_config(json.loads((folder / "config.json").read_text()))
        write_json(folder / "result.json", {"status": "running"})
        output = run(config)
        write_json(folder / "result.json", {"status": "completed", **output})
    except Exception as error:
        traceback.print_exc()
        write_json(folder / "result.json", {"status": "failed", "error": str(error)})
        sys.exit(1)
