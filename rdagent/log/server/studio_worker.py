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
    benchmark = result.get("benchmark", "SH000300")
    if not isinstance(benchmark, str) or not benchmark.strip() or len(benchmark) > 20:
        raise ValueError("Invalid benchmark")
    result["benchmark"] = benchmark.strip()
    result["model"] = validate_model(result.get("model"), result["start"])
    if result.get("search") is not None:
        search = result["search"] if isinstance(result["search"], dict) else {}
        objective = search.get("objective", "sharpe")
        if objective not in ("sharpe", "total_return"):
            raise ValueError("Search objective must be sharpe or total_return")
        split = float(search.get("split", 2 / 3))
        if not 0.4 <= split <= 0.85:
            raise ValueError("Search split must be between 0.4 and 0.85")
        result["search"] = {"objective": objective, "split": split}
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


LGBM_DEFAULTS = {"learning_rate": 0.05, "num_leaves": 63, "max_depth": 8, "colsample_bytree": 0.8,
                 "subsample": 0.8, "subsample_freq": 1, "lambda_l1": 0.0, "lambda_l2": 1.0,
                 "n_estimators": 1000, "early_stopping_rounds": 50}
LGBM_LIMITS = {"learning_rate": (0.001, 1.0), "num_leaves": (2, 1024), "max_depth": (-1, 64),
               "colsample_bytree": (0.1, 1.0), "subsample": (0.1, 1.0), "subsample_freq": (0, 100),
               "lambda_l1": (0.0, 10000.0), "lambda_l2": (0.0, 10000.0),
               "n_estimators": (10, 5000), "early_stopping_rounds": (0, 1000)}
INTEGER_LGBM = {"num_leaves", "max_depth", "subsample_freq", "n_estimators", "early_stopping_rounds"}


def validate_model(model, backtest_start):
    """Normalise the signal-synthesis block.

    ``{"method": "rank"}`` (default) is the weighted percentile-rank blend. ``{"method": "lgbm", "train":
    [start, end], "valid": [start, end], "params": {...}}`` trains LightGBM on the selected signals and uses
    its prediction as the portfolio score. Windows must be ordered train < valid < backtest so the model never
    sees the period it is evaluated on.
    """
    from datetime import date
    model = dict(model or {})
    method = model.get("method", "rank")
    if method == "rank":
        return {"method": "rank"}
    if method != "lgbm":
        raise ValueError("Unsupported signal method")
    windows = {}
    for key in ("train", "valid"):
        window = model.get(key)
        if not isinstance(window, (list, tuple)) or len(window) != 2:
            raise ValueError(f"Model {key} window must be [start, end]")
        for value in window:
            date.fromisoformat(value)
        if window[0] >= window[1]:
            raise ValueError(f"Model {key} window start must be earlier than its end")
        windows[key] = [window[0], window[1]]
    if not windows["train"][1] < windows["valid"][0]:
        raise ValueError("Validation window must start after the training window ends")
    if not windows["valid"][1] < backtest_start:
        raise ValueError("Backtest must start after the validation window ends")
    params = dict(LGBM_DEFAULTS)
    for key, value in (model.get("params") or {}).items():
        if key not in LGBM_LIMITS:
            raise ValueError(f"Unknown LightGBM parameter {key}")
        value = float(value)
        lower, upper = LGBM_LIMITS[key]
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"Invalid LightGBM parameter {key}")
        params[key] = int(value) if key in INTEGER_LGBM else value
    return {"method": "lgbm", **windows, "params": params}


def cross_sectional_zscore(series):
    """Per-day z-score, the label normalisation Qlib's templates apply (CSZScoreNorm)."""
    grouped = series.groupby(level="datetime")
    std = grouped.transform("std")
    return ((series - grouped.transform("mean")) / std.where(std > 0)).dropna()


def require_window_coverage(features, window, purpose):
    """Name every signal column that has no observation inside ``window`` instead of failing on an empty join."""
    import pandas as pd

    start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    dates = features.index.get_level_values("datetime")
    inside = features[(dates >= start) & (dates <= end)]
    missing = [column for column in features.columns if inside[column].notna().sum() == 0]
    if missing:
        spans = []
        for column in missing:
            observed = features[column].dropna().index.get_level_values("datetime")
            spans.append(f"{column} ({observed.min().date()} to {observed.max().date()})" if len(observed) else f"{column} (no data)")
        raise ValueError(f"No {purpose} data for: {', '.join(spans)}; remove these signals or move the {purpose} window")


def train_lgbm_signal(features, label, model, log=print):
    """Fit LightGBM on ``features`` (already cross-sectionally ranked) and return scores for every row.

    Returns ``(score, report)`` where ``report`` carries the best iteration, validation loss and feature importances.
    """
    import lightgbm as lgb
    import pandas as pd

    dates = features.index.get_level_values("datetime")
    def window(name):
        start, end = pd.Timestamp(model[name][0]), pd.Timestamp(model[name][1])
        return features[(dates >= start) & (dates <= end)]
    train_x, valid_x = window("train"), window("valid")
    require_window_coverage(features, model["train"], "training")
    require_window_coverage(features, model["valid"], "validation")
    train = train_x.join(label.rename("label"), how="inner").dropna()
    valid = valid_x.join(label.rename("label"), how="inner").dropna()
    if len(train) < 100:
        raise ValueError(f"Training window has only {len(train)} labelled rows; widen it")
    if len(valid) < 20:
        raise ValueError(f"Validation window has only {len(valid)} labelled rows; widen it")
    params = dict(model["params"])
    rounds = params.pop("n_estimators")
    patience = params.pop("early_stopping_rounds")
    params.update({"objective": "regression", "metric": "l2", "verbosity": -1, "seed": 0, "num_threads": 4})
    columns = list(features.columns)
    dtrain = lgb.Dataset(train[columns], train["label"])
    dvalid = lgb.Dataset(valid[columns], valid["label"], reference=dtrain)
    callbacks = [lgb.log_evaluation(period=100)]
    if patience > 0:
        callbacks.append(lgb.early_stopping(patience, verbose=False))
    booster = lgb.train(params, dtrain, num_boost_round=rounds, valid_sets=[dvalid], valid_names=["valid"], callbacks=callbacks)
    score = pd.Series(booster.predict(features[columns], num_iteration=booster.best_iteration or None), index=features.index)
    importance = dict(zip(columns, (float(v) for v in booster.feature_importance("gain"))))
    report = {"best_iteration": int(booster.best_iteration or rounds),
              "valid_l2": float(booster.best_score.get("valid", {}).get("l2", float("nan"))),
              "train_rows": int(len(train)), "valid_rows": int(len(valid)), "feature_importance": importance}
    log(f"LightGBM trained: {report}")
    return score, report


def information_coefficient(score, label):
    """Mean daily Pearson and Spearman IC between a score and the forward-return label."""
    frame = score.rename("score").to_frame().join(label.rename("label"), how="inner").dropna()
    if frame.empty:
        return None, None
    by_day = frame.groupby(level="datetime")
    ic = by_day.apply(lambda d: d["score"].corr(d["label"]) if len(d) > 2 else float("nan")).dropna()
    rank_ic = by_day.apply(lambda d: d["score"].corr(d["label"], method="spearman") if len(d) > 2 else float("nan")).dropna()
    return (float(ic.mean()) if len(ic) else None, float(rank_ic.mean()) if len(rank_ic) else None)


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
        # `start` here is the trading day BEFORE the first backtest day (TopkDropout trades on the
        # previous day's signal), so spell out both constraints instead of quoting a range that may
        # look identical to what the user asked for.
        raise ValueError(
            f"Signals cover {first.date()} to {last.date()}. The backtest needs a signal on the trading day "
            f"before its start, so start after {first.date()} and end on or before {last.date()}"
        )


def load_factor_frame(factor, start, end):
    """Read one signal as a single-column frame named after it.

    ``kind == "factor"`` (default) reads the workspace's result.h5; ``kind == "prediction"`` reads a Qlib
    ``pred.pkl`` (model scores) so a research round's model can be backtested like any other signal.
    """
    import pandas as pd

    if factor.get("kind", "factor") == "prediction":
        source = Path(factor["path"])
        if not source.is_file():
            raise ValueError(f"Prediction {factor['name']} is missing at {factor['path']}")
        frame = pd.read_pickle(source)
    else:
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


def trades_from_indicator(order_indicator_his):
    """Flatten Qlib's per-day order indicators into one row per filled order.

    ``order_indicator_his`` maps a trade date to a Qlib order indicator exposing
    ``get_index_data(metric).to_dict()`` (instrument -> value) for deal_amount, trade_price,
    trade_value (signed: + buy, - sell), trade_cost and trade_dir (1 buy, 0 sell). Qlib's
    ``to_series`` is avoided on purpose: it breaks under pandas 2 with custom Index objects.
    """
    trades = []
    for day, indicator in order_indicator_his.items():
        metric = lambda name: indicator.get_index_data(name).to_dict()  # noqa: E731
        deal = metric("deal_amount")
        if not deal:
            continue
        price, value, cost, direction = metric("trade_price"), metric("trade_value"), metric("trade_cost"), metric("trade_dir")
        for instrument, amount in deal.items():
            if not amount:
                continue
            trades.append({
                "date": str(getattr(day, "date", lambda: day)()),
                "instrument": str(instrument),
                "direction": "buy" if int(direction.get(instrument, 1)) == 1 else "sell",
                "amount": float(amount),
                "price": float(price.get(instrument, 0.0)),
                "value": abs(float(value.get(instrument, 0.0))),
                "cost": float(cost.get(instrument, 0.0)),
            })
    return trades


def holdings_from_position(position):
    """The final book: one row per held instrument plus the cash line."""
    rows = []
    for instrument in position.get_stock_list():
        amount = float(position.get_stock_amount(instrument))
        price = float(position.get_stock_price(instrument))
        rows.append({"instrument": str(instrument), "amount": amount, "price": price,
                     "value": amount * price, "weight": float(position.get_stock_weight(instrument))})
    rows.sort(key=lambda r: -r["value"])
    return {"positions": rows, "cash": float(position.get_cash()), "total": float(position.calculate_value())}


def instrument_summary(trades, holdings):
    """Per-instrument realised + unrealised P&L: sells - buys - costs + what is still held."""
    held = {row["instrument"]: row["value"] for row in holdings["positions"]}
    summary = {}
    for trade in trades:
        row = summary.setdefault(trade["instrument"], {"instrument": trade["instrument"], "trades": 0,
                                                          "buy_value": 0.0, "sell_value": 0.0, "cost": 0.0})
        row["trades"] += 1
        row["cost"] += trade["cost"]
        row["buy_value" if trade["direction"] == "buy" else "sell_value"] += trade["value"]
    for instrument, value in held.items():
        summary.setdefault(instrument, {"instrument": instrument, "trades": 0, "buy_value": 0.0, "sell_value": 0.0, "cost": 0.0})
    result = []
    for row in summary.values():
        row["holding_value"] = held.get(row["instrument"], 0.0)
        row["pnl"] = row["sell_value"] - row["buy_value"] - row["cost"] + row["holding_value"]
        row["held"] = row["instrument"] in held
        result.append(row)
    result.sort(key=lambda r: -r["pnl"])
    return result


def prepare(config):
    """Everything up to the score: Qlib init, calendar, ranked features, label, universe.

    Returns a dict shared by the backtest and the diagnosis so both look at exactly the same data.
    """
    # Use the user's adjacent Qlib checkout, not an unrelated installed checkout.
    checkout = Path(__file__).resolve().parents[4] / "qlib"
    if checkout.is_dir():
        sys.path.insert(0, str(checkout))
    import pandas as pd
    import qlib
    from qlib.data import D

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
    model = config.get("model") or {"method": "rank"}
    # A trained model needs its training history as well; the rank blend only needs the backtest window.
    feature_start = pd.Timestamp(model["train"][0]) if model["method"] == "lgbm" else prior[-1]
    frames = [load_factor_frame(f, feature_start, config["end"]) for f in factors]
    features = pd.concat(frames, axis=1).sort_index()
    if features.empty:
        raise ValueError("No factor observations for this date range")
    universe = set(D.list_instruments(D.instruments(config["market"]),
                                      start_time=feature_start, end_time=config["end"], as_list=True))
    features = features[features.index.get_level_values("instrument").isin(universe)]
    if features.empty:
        raise ValueError("No factor observations inside the selected universe")
    # Require all selected factors on a row; do not silently treat missing data as zero.
    ranks = features.groupby(level="datetime").rank(pct=True).dropna()
    # Next-day close-to-close return, the label Qlib's templates use with close execution.
    label_raw = D.features(D.instruments(config["market"]), ["Ref($close, -2)/Ref($close, -1) - 1"],
                           start_time=feature_start, end_time=config["end"], freq="day").iloc[:, 0]
    if label_raw.index.names[0] == "instrument":  # Qlib returns (instrument, datetime); signals are (datetime, instrument)
        label_raw = label_raw.swaplevel(0, 1)
    label = cross_sectional_zscore(label_raw.sort_index())
    return {"calendar": calendar, "prior_day": prior[-1], "end_day": trading_day_on_or_before(calendar, config["end"]),
            "factors": factors, "model": model, "ranks": ranks, "label": label}


def combine(prepared, columns, weights, model, log=print):
    """Score a subset of the ranked signals: weighted rank blend, or a LightGBM fit on just those columns.

    Returns ``(score restricted to the backtest window, model report or None)``.
    """
    import numpy as np

    ranks = prepared["ranks"][list(columns)]
    if model["method"] == "lgbm":
        score, report = train_lgbm_signal(ranks, prepared["label"], model, log=log)
        score = score[score.index.get_level_values("datetime") >= prepared["prior_day"]]
    else:
        w = np.array([float(x) for x in weights])
        score, report = ranks.mul(w, axis=1).sum(axis=1) / abs(w).sum(), None
    score = score.dropna().sort_index()
    if score.empty:
        raise ValueError("Selected factors have no complete observations")
    require_signal_coverage(score.index.get_level_values("datetime"), prepared["prior_day"], prepared["end_day"])
    return score, report


def backtest_score(score, config):
    """Run Qlib's TopkDropout backtest on ``score``; returns the daily report and Qlib's positions/indicators."""
    from qlib.backtest import backtest

    strategy = {"class": "TopkDropoutStrategy", "module_path": "qlib.contrib.strategy",
                "kwargs": {"signal": score, "topk": config["topk"], "n_drop": config["n_drop"]}}
    portfolios, indicators = backtest(
        start_time=config["start"], end_time=config["end"], strategy=strategy,
        executor={"class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
                  "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True}},
        account=config["account"], benchmark=config.get("benchmark", "SH000300"),
        exchange_kwargs={"freq": "day", "limit_threshold": 0.095, "deal_price": "close",
                         "open_cost": config["open_cost"], "close_cost": config["close_cost"], "min_cost": 5},
    )
    report, positions = portfolios["1day"]
    _, indicator = indicators["1day"]
    if report.empty:
        raise ValueError("Backtest returned no daily report")
    return report, positions, indicator


def summarize_report(report):
    """Net-of-cost metrics and the daily rows the UI charts, from Qlib's daily report."""
    import numpy as np

    net = report["return"] - report["cost"]
    equity = (1 + net).cumprod()
    benchmark = (1 + report["bench"]).cumprod()
    peak = equity.cummax().clip(lower=1)
    drawdown = equity / peak - 1
    vol = net.std(ddof=1)
    metrics = {"total_return": float(equity.iloc[-1] - 1),
               "annualized_return": float(equity.iloc[-1] ** (252 / len(net)) - 1),
               "sharpe": float(net.mean() / vol * np.sqrt(252)) if vol > 0 else None,
               "max_drawdown": float(drawdown.min()),
               "benchmark_return": float(benchmark.iloc[-1] - 1), "days": len(net)}
    rows = [{"date": str(day.date()), "equity": float(equity.loc[day]), "benchmark": float(benchmark.loc[day]),
             "drawdown": float(drawdown.loc[day]), "return": float(net.loc[day]), "cost": float(row["cost"]),
             "turnover": float(row["turnover"]), "account": float(row["account"])} for day, row in report.iterrows()]
    return metrics, rows


def clean(value):
    """JSON-safe copy: NaN/inf become null."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def signal_diagnosis(prepared, score):
    """The cheap part of the portfolio diagnosis, computed on every run.

    Per signal: its own IC / Rank IC over the backtest window and its correlation with the final score;
    plus the pairwise correlation of the ranked signals over the window. Together they say which signals
    pull their weight, which point the wrong way, and which pairs are near duplicates.
    """
    window = prepared["ranks"][prepared["ranks"].index.get_level_values("datetime") >= prepared["prior_day"]]
    label = prepared["label"]
    signals = []
    for factor in prepared["factors"]:
        column = window[factor["name"]]
        ic, rank_ic = information_coefficient(column, label)
        joined = column.rename("s").to_frame().join(score.rename("score"), how="inner").dropna()
        corr = float(joined["s"].corr(joined["score"])) if len(joined) > 2 else None
        signals.append({"name": factor["name"], "kind": factor.get("kind", "factor"), "weight": float(factor["weight"]),
                        "ic": ic, "rank_ic": rank_ic, "corr_with_score": corr})
    names = [f["name"] for f in prepared["factors"]]
    matrix = window[names].corr().values.tolist() if len(names) > 1 else [[1.0]]
    return {"signals": signals, "correlation": {"names": names, "matrix": matrix, "days": int(window.index.get_level_values("datetime").nunique())}}


def run(config):
    prepared = prepare(config)
    factors, model = prepared["factors"], prepared["model"]
    score, model_report = combine(prepared, [f["name"] for f in factors], [f["weight"] for f in factors], model)
    test_ic, test_rank_ic = information_coefficient(score, prepared["label"])
    report, positions, indicator = backtest_score(score, config)
    trades = trades_from_indicator(getattr(indicator, "order_indicator_his", {}))
    last_day = max(positions) if positions else None
    holdings = holdings_from_position(positions[last_day]) if last_day is not None else {"positions": [], "cash": None, "total": None}
    instruments = instrument_summary(trades, holdings)
    metrics, rows = summarize_report(report)
    return clean({"metrics": {**metrics, "signal_ic": test_ic, "signal_rank_ic": test_rank_ic},
                  "model": model_report,
                  "rows": rows, "config": config,
                  "trades": trades, "holdings": holdings, "instruments": instruments,
                  "diagnosis": signal_diagnosis(prepared, score) if len(factors) > 1 else None,
                  "method": "Net-of-cost compounded returns; 252 trading days; Sharpe risk-free rate = 0. Previous-day signals, close execution."})


def diagnose(config, progress=lambda *_: None):
    """Take the portfolio apart: every signal alone, and the portfolio without each signal, on the same window.

    Each variant is scored the same way the portfolio was (rank blend with the configured weights, or a
    LightGBM refit on the remaining columns) and put through the same backtest. ``progress`` is called
    with (done, total) after each variant.
    """
    prepared = prepare(config)
    factors, model = prepared["factors"], prepared["model"]
    if len(factors) < 2:
        raise ValueError("Diagnosis needs at least two signals")
    names = [f["name"] for f in factors]
    weights = {f["name"]: f["weight"] for f in factors}

    def variant(columns):
        score, _ = combine(prepared, columns, [weights[c] for c in columns], model, log=lambda *_: None)
        ic, rank_ic = information_coefficient(score, prepared["label"])
        metrics, rows = summarize_report(backtest_score(score, config)[0])
        # Equity only, so the UI can overlay every variant's curve on the portfolio's without bloating the file.
        return {**metrics, "signal_ic": ic, "signal_rank_ic": rank_ic, "equity": [[r["date"], round(r["equity"], 6)] for r in rows]}

    total, done = 2 * len(names) + 1, 0
    base = variant(names); done += 1; progress(done, total)
    alone, without = {}, {}
    for name in names:
        try:
            alone[name] = variant([name])
        except ValueError as error:
            alone[name] = {"error": str(error)}
        done += 1; progress(done, total)
    for name in names:
        try:
            without[name] = variant([n for n in names if n != name])
        except ValueError as error:
            without[name] = {"error": str(error)}
        done += 1; progress(done, total)
    return clean({"base": base, "alone": alone, "without": without, "names": names, "method": model["method"]})


def split_window(calendar, start, end, ratio):
    """Search on the first ``ratio`` of the trading days in [start, end], validate on the rest."""
    import pandas as pd

    days = calendar[(calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end))]
    if len(days) < 60:
        raise ValueError("The window is too short to split into search and validation parts (need 60 trading days)")
    cut = max(20, min(len(days) - 20, int(len(days) * ratio)))
    return (str(days[0].date()), str(days[cut - 1].date())), (str(days[cut].date()), str(days[-1].date()))


def search(config, progress=lambda *_: None):
    """Greedy portfolio search: forward selection, then backward elimination, judged on a search window and
    reported on a held-out validation window so the recommendation is not just the best fit of its own data.

    Every candidate is scored with the configured weights (rank blend); LightGBM is not searched because each
    variant would need a refit. ``progress`` receives (done, total estimate, steps so far) after each backtest.
    """
    prepared = prepare(config)
    factors, model = prepared["factors"], prepared["model"]
    if model["method"] != "rank":
        raise ValueError("Portfolio search works with the rank blend; switch 信号合成 to 排名加权")
    names = [f["name"] for f in factors]
    if len(names) < 2:
        raise ValueError("Search needs at least two candidate signals")
    weights = {f["name"]: f["weight"] for f in factors}
    objective = (config.get("search") or {}).get("objective", "sharpe")
    search_win, valid_win = split_window(prepared["calendar"], config["start"], config["end"], (config.get("search") or {}).get("split", 2 / 3))
    total = [len(names) + len(names) * (len(names) - 1) // 2 + len(names) + 3]
    steps, done = [], [0]

    def score_of(metrics):
        value = metrics.get(objective)
        return value if isinstance(value, (int, float)) else float("-inf")

    def run_variant(columns, window, keep_curve=False):
        score, _ = combine(prepared, columns, [weights[c] for c in columns], model, log=lambda *_: None)
        report = backtest_score(score, {**config, "start": window[0], "end": window[1]})[0]
        metrics, rows = summarize_report(report)
        if keep_curve:
            metrics["equity"] = [[r["date"], round(r["equity"], 6)] for r in rows]
        return metrics

    def record(kind, members, metrics, tried=None, accepted=None):
        steps.append({"step": len(steps) + 1, "kind": kind, "tried": tried, "members": list(members), "accepted": accepted, **{k: metrics.get(k) for k in ("total_return", "sharpe", "max_drawdown", "days")}})
        done[0] += 1
        progress(done[0], total[0], steps)

    def better(candidate, incumbent):
        return score_of(candidate) > score_of(incumbent) + 1e-9

    # 1. every candidate alone
    singles = {}
    for name in names:
        try:
            singles[name] = run_variant([name], search_win)
        except ValueError as error:
            singles[name] = {"error": str(error)}
        record("single", [name], singles[name], tried=name)
    usable = [n for n in names if "error" not in singles[n]]
    if not usable:
        raise ValueError("No candidate could be backtested alone on the search window")
    current = [max(usable, key=lambda n: score_of(singles[n]))]
    current_metrics = singles[current[0]]
    record("start", current, current_metrics, accepted=True)
    # 2. forward: add the candidate that improves the objective most, until none does
    remaining = [n for n in usable if n not in current]
    while remaining:
        trials = {}
        for name in remaining:
            try:
                trials[name] = run_variant(current + [name], search_win)
            except ValueError as error:
                trials[name] = {"error": str(error)}
            record("add", current + [name], trials[name], tried=name, accepted=False)
        best = max((n for n in remaining if "error" not in trials[n]), key=lambda n: score_of(trials[n]), default=None)
        if best is None or not better(trials[best], current_metrics):
            break
        steps[-len(remaining) + list(remaining).index(best)]["accepted"] = True
        current, current_metrics = current + [best], trials[best]
        remaining = [n for n in remaining if n != best]
    # 3. backward: drop any member whose removal improves the objective
    changed = True
    while changed and len(current) > 1:
        changed = False
        for name in list(current):
            rest = [n for n in current if n != name]
            try:
                trial = run_variant(rest, search_win)
            except ValueError as error:
                trial = {"error": str(error)}
            improves = "error" not in trial and better(trial, current_metrics)
            record("drop", rest, trial, tried=name, accepted=improves)
            if improves:
                current, current_metrics, changed = rest, trial, True
                break
    # 4. the recommendation and the everything-in portfolio, on both windows
    total[0] = done[0] + 3
    recommended = {"members": current, "weights": {n: weights[n] for n in current},
                   "search": run_variant(current, search_win, keep_curve=True),
                   "validation": run_variant(current, valid_win, keep_curve=True)}
    done[0] += 2; progress(done[0], total[0], steps)
    everything = {"members": names, "search": current_metrics if len(current) == len(names) else run_variant(names, search_win, keep_curve=True)}
    try:
        everything["validation"] = run_variant(names, valid_win, keep_curve=True)
    except ValueError as error:
        everything["validation"] = {"error": str(error)}
    done[0] += 1; progress(done[0], total[0], steps)
    return clean({"objective": objective, "windows": {"search": search_win, "validation": valid_win}, "candidates": names,
                  "steps": steps, "recommended": recommended, "everything": everything, "config": config})


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    diagnosing = "--diagnose" in sys.argv[2:]
    searching = "--search" in sys.argv[2:]
    target = folder / ("diagnosis.json" if diagnosing else "result.json")
    try:
        config = validate_config(json.loads((folder / "config.json").read_text()))
        write_json(target, {"status": "running"})
        if diagnosing:
            output = diagnose(config, progress=lambda done, total: write_json(target, {"status": "running", "done": done, "total": total}))
        elif searching:
            output = search(config, progress=lambda done, total, steps: write_json(target, {"status": "running", "done": done, "total": total, "steps": clean(steps)}))
        else:
            output = run(config)
        write_json(target, {"status": "completed", **output})
    except Exception as error:
        traceback.print_exc()
        write_json(target, {"status": "failed", "error": str(error)})
        sys.exit(1)
