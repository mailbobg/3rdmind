"""Isolated Qlib factor-portfolio worker for the local research studio.

Reads each selected factor workspace's ``result.h5`` file, combines the
factors into a single ranked signal, and runs a TopkDropoutStrategy backtest
over the requested date range.
"""
import json
import re
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
        ("topk", 10, 1, 6000), ("n_drop", 2, 0, 6000),  # 6000: "every name the rule keeps" on all A-shares
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
    # horizon: days the label looks ahead (LightGBM target and reported IC); rebalance: trading days between
    # signal refreshes, also the minimum holding period. Both default to the daily setup.
    # neutral: what the portfolio score is purged of before ranking. "none" trades the raw blend (the way
    # every strategy before 2026-09-19 was run); "size" regresses out log traded value each day; "size_industry"
    # also removes industry means. The gate certifies size-neutral IC, so "size" is what matches it.
    # stagger: how many tranches the book is split into, each refreshed on its own cadence within the rebalance
    # interval (1 = the whole book turns on one day, and the result depends on which day the run started).
    stagger = int(result.get("stagger") or 1)
    if not 1 <= stagger <= 20:
        raise ValueError("stagger must be between 1 and 20")
    result["stagger"] = stagger
    neutral = str(result.get("neutral") or "none")
    if neutral not in NEUTRAL_MODES:
        raise ValueError("neutral must be none, size or size_industry")
    result["neutral"] = neutral
    # book: how the score becomes positions. "equal" (default) puts the top names at equal weight on every
    # rebalance day and lets them drift in between; "topk" is Qlib's TopkDropout, whose positions are sized by
    # the cash of that day's swaps, so a name bought on a quiet day can grow to a quarter of the book (the
    # 2026-09-20 finding: strategy III's +96% was three such names).
    book = str(result.get("book") or "equal")
    if book not in BOOKS:
        raise ValueError("book must be equal or topk")
    result["book"] = book
    # execution: when the equal book buys. "close" (default) trades at the close of the day after the signal;
    # "open" buys at that day's open and sells at its close (A-share overnight returns are negative).
    execution = str(result.get("execution") or "close")
    if execution not in ("close", "open"):
        raise ValueError("execution must be close or open")
    if execution == "open" and book != "equal":
        raise ValueError("open execution is only available with the equal-weight book")
    result["execution"] = execution
    fills = str(result.get("fills") or "ideal")
    if fills not in FILLS:
        raise ValueError("fills must be ideal or real")
    if fills == "real" and book != "equal":
        raise ValueError("real fills are only available with the equal-weight book (TopkDropout has its own exchange rules)")
    result["fills"] = fills
    for key in ("horizon", "rebalance"):
        value = float(1 if result.get(key) is None else result[key])
        if not math.isfinite(value) or not value.is_integer() or not 1 <= value <= 20:
            raise ValueError(f"{key} must be a whole number of trading days between 1 and 20")
        result[key] = int(value)
    if not isinstance(result.get("market"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", result["market"]):
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
        # The server's pre-search filter rides along so the result shows what was screened out.
        if isinstance(search.get("prefilter"), dict):
            result["search"]["prefilter"] = search["prefilter"]
    if result.get("walkforward") is not None:
        wf = result["walkforward"] if isinstance(result["walkforward"], dict) else {}
        fold = int(wf.get("fold_days", 63))
        train = int(wf.get("train_days", 252))
        select_t = float(wf.get("select_t", 2.0))
        max_factors = int(wf.get("max_factors", 8))
        select_by = str(wf.get("select_by") or "book")
        if select_by not in ("ic", "book"):
            raise ValueError("select_by must be ic or book")
        if not 20 <= fold <= 252:
            raise ValueError("fold_days must be between 20 and 252 trading days")
        if not 120 <= train <= 1000:
            raise ValueError("train_days must be between 120 and 1000 trading days")
        if not 0 <= select_t <= 10:
            raise ValueError("select_t must be between 0 and 10")
        if not 1 <= max_factors <= 80:
            raise ValueError("max_factors must be between 1 and 80")
        # select_by: how a fold picks its parts from the training window. "ic": the size-neutral 1-day Rank IC t
        # (the gate's criterion); "book" (default): the t of the part's own equal-weight book over the window's
        # holding periods (the portfolio's criterion; 2026-09-20).
        result["walkforward"] = {"fold_days": fold, "train_days": train, "select_t": select_t, "max_factors": max_factors, "select_by": select_by}
    factors = result.get("factors", [])
    # A trained model (零件组合) takes many signals; the greedy search is quadratic in them and stays small.
    limit = MAX_SEARCH_FACTORS if "search" in result else MAX_FACTORS
    if not isinstance(factors, list) or not 1 <= len(factors) <= limit:
        raise ValueError(f"Select 1 to {limit} factors")
    names = [f.get("name") for f in factors if isinstance(f, dict)]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"篮子里有同名因子 {', '.join(map(str, duplicates))}（来自不同轮次），请只保留一个")
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


NEUTRAL_MODES = ("none", "size", "size_industry")
MAX_FACTORS = 80  # signals one backtest may combine
MAX_SEARCH_FACTORS = 20  # candidates one greedy search may walk
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


def daily_ic(score, label):
    """Per-day Pearson and Spearman IC between a score and the forward-return label; (None, None) with no overlap."""
    frame = score.rename("score").to_frame().join(label.rename("label"), how="inner").dropna()
    if frame.empty:
        return None, None
    by_day = frame.groupby(level="datetime")
    ic = by_day.apply(lambda d: d["score"].corr(d["label"]) if len(d) > 2 else float("nan")).dropna()
    rank_ic = by_day.apply(lambda d: d["score"].corr(d["label"], method="spearman") if len(d) > 2 else float("nan")).dropna()
    return ic, rank_ic


def information_coefficient(score, label):
    """Mean daily Pearson and Spearman IC between a score and the forward-return label."""
    ic, rank_ic = daily_ic(score, label)
    if ic is None:
        return None, None
    return (float(ic.mean()) if len(ic) else None, float(rank_ic.mean()) if len(rank_ic) else None)


def ic_rows(ic, rank_ic):
    """The daily IC series as rows the recent-performance read-out compares against history."""
    if ic is None:
        return []
    days = sorted(set(ic.index) | set(rank_ic.index))
    return [{"date": str(day.date()), "ic": float(ic[day]) if day in ic.index else None,
             "rank_ic": float(rank_ic[day]) if day in rank_ic.index else None} for day in days]


SUMMARY_KEYS = ("status", "error", "metrics", "baseline", "lottery", "notes", "method", "recommended", "windows", "walk", "fixed", "walkforward")


def summary_of(result):
    """The part of a result the list views need (status, metrics, verdict blocks); the daily rows, trade log
    and per-name tables stay in result.json. Curves inside the kept blocks are dropped too."""
    out = {}
    for key in SUMMARY_KEYS:
        if key not in result:
            continue
        value = result[key]
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if not isinstance(v, list) or len(v) < 200}
        out[key] = value
    return out


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


def read_result(path):
    """The frame in a result.h5, taking the first dataset when the file holds several (a factor.py that saved twice)."""
    import pandas as pd

    try:
        return pd.read_hdf(path)
    except ValueError:
        with pd.HDFStore(path, mode="r") as store:
            return store[store.keys()[0]]


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
        frame = read_result(source)
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


def unadjust_book(trades, holdings, factors):
    """Turn Qlib's adjusted prices and share counts into real ones for the trade log and the closing book.

    Qlib backtests in adjusted prices (``$close`` is the raw close times ``$factor``, and shares are counted
    in the same adjusted units), so a position's value is right but its price and share count are not what a
    broker shows. ``factors`` maps (instrument, date) -> $factor; a row whose factor is missing is left as
    it is. Values are unchanged: real price × real shares equals adjusted price × adjusted shares.
    """
    def fix(row, day):
        factor = factors.get((row["instrument"], day))
        if factor and factor == factor:  # present and not NaN
            row["price"] = row["price"] / factor
            row["amount"] = row["amount"] * factor
        return row

    for trade in trades:
        fix(trade, trade["date"])
    if holdings.get("as_of"):
        for row in holdings["positions"]:
            fix(row, holdings["as_of"])
    return trades, holdings


def load_factors(instruments, start, end):
    """(instrument, date) -> $factor from the initialised Qlib provider, for unadjust_book()."""
    from qlib.data import D

    if not instruments:
        return {}
    frame = D.features(sorted(set(instruments)), ["$factor"], start_time=start, end_time=end, freq="day")
    return {(str(inst), str(day.date())): float(v) for (inst, day), v in frame["$factor"].items()}


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
    qlib.init(provider_uri=str(provider), region=config.get("region") or "cn")
    calendar = D.calendar(freq="day")
    if pd.Timestamp(config["end"]) > calendar[-1] or pd.Timestamp(config["start"]) < calendar[0]:
        raise ValueError(f"Requested dates outside data coverage: {calendar[0]} to {calendar[-1]}")
    notes = []
    # Qlib's TopkDropoutStrategy looks up the trading day after each step, so a backtest cannot end on the
    # calendar's very last day; end one day earlier and say so.
    if pd.Timestamp(config["end"]) >= calendar[-1]:
        clamped = str(pd.Timestamp(calendar[-2]).date())
        notes.append(f"结束日 {config['end']} 是数据的最后一个交易日，回测需要再往后一天的数据，已改为 {clamped}")
        config = {**config, "end": clamped}
        if pd.Timestamp(config["start"]) >= pd.Timestamp(config["end"]):
            raise ValueError("Start date must be earlier than the last usable backtest day " + clamped)
    # TopkDropoutStrategy reads the previous trading day's prediction.
    prior = calendar[calendar < pd.Timestamp(config["start"])]
    if not len(prior):
        raise ValueError("At least one trading day of signal history is required")
    factors = config["factors"]
    model = config.get("model") or {"method": "rank"}
    # A trained model needs its training history as well; the rank blend only needs the backtest window.
    feature_start = pd.Timestamp(model["train"][0]) if model["method"] == "lgbm" else prior[-1]
    if config.get("feature_start"):
        feature_start = min(feature_start, pd.Timestamp(config["feature_start"]))
    frames = [load_factor_frame(f, feature_start, config["end"]) for f in factors]
    features = pd.concat(frames, axis=1).sort_index()
    if features.empty:
        raise ValueError("No factor observations for this date range")
    # Point-in-time membership: a name only carries a signal on the days it belonged to the universe, so
    # the book never holds a name because it was a member a year earlier (or later).
    spans = D.list_instruments(D.instruments(config["market"]), start_time=feature_start, end_time=config["end"], as_list=False)
    features = members_only(features, spans, calendar)
    if (config.get("region") or "cn") == "cn":
        features = features[~features.index.get_level_values("instrument").str.startswith("BJ")]  # see studio_universe
    if features.empty:
        raise ValueError("No factor observations inside the selected universe")
    # Cross-sectional percentile ranks per signal. Rows are not dropped here: a variant only needs its own
    # columns, so combine() drops incomplete rows for the columns it uses. Otherwise one factor that stops
    # early (not yet 重算到最新) would cut every other candidate short with it.
    ranks = features.groupby(level="datetime").rank(pct=True)
    # Forward close-to-close return over ``horizon`` days from the next close; at 1 this is the label Qlib's
    # templates use with close execution.
    horizon = int(config.get("horizon", 1))
    label_raw = D.features(D.instruments(config["market"]), [f"Ref($close, -{horizon + 1})/Ref($close, -1) - 1"],
                           start_time=feature_start, end_time=config["end"], freq="day").iloc[:, 0]
    if label_raw.index.names[0] == "instrument":  # Qlib returns (instrument, datetime); signals are (datetime, instrument)
        label_raw = label_raw.swaplevel(0, 1)
    label = cross_sectional_zscore(label_raw.sort_index())
    size, industry = None, None
    if config.get("neutral", "none") != "none":
        # The same size measure the single-factor analysis residualises on, so the portfolio trades what the
        # gate certified: log of the trailing 20-day mean traded value, known the day before.
        size_raw = D.features(D.instruments(config["market"]), ["Log(Ref(Mean($close*$volume, 20), 1))"],
                              start_time=feature_start, end_time=config["end"], freq="day").iloc[:, 0]
        if size_raw.index.names[0] == "instrument":
            size_raw = size_raw.swaplevel(0, 1)
        size = size_raw.sort_index()
        if config["neutral"] == "size_industry":
            industry = industry_map(config)
            if not industry:
                notes.append("行业中性未做：没有行业表（instrument_names.json），只做了规模中性")
    return {"calendar": calendar, "prior_day": prior[-1], "end_day": trading_day_on_or_before(calendar, config["end"]), "config": config, "notes": notes,
            "factors": factors, "model": model, "ranks": ranks, "label": label, "size": size, "industry": industry}


def members_only(frame, spans, calendar):
    """Keep the rows of a (datetime, instrument) frame whose date falls inside one of the instrument's
    membership spans (Qlib's ``list_instruments(as_list=False)``: code → [(start, end), ...])."""
    import numpy as np
    import pandas as pd

    cal = pd.DatetimeIndex(calendar)
    keep = []
    for code, ranges in spans.items():
        for start, end in ranges:
            days = cal[(cal >= pd.Timestamp(start)) & (cal <= pd.Timestamp(end))]
            if len(days):
                keep.append(pd.MultiIndex.from_arrays([days, np.repeat(code, len(days))], names=["datetime", "instrument"]))
    if not keep:
        return frame.iloc[0:0]
    member = keep[0].append(keep[1:]) if len(keep) > 1 else keep[0]
    return frame.loc[frame.index.isin(member)]


def industry_map(config):
    """Instrument → industry from the Studio's name table beside the traces (A-shares; empty elsewhere)."""
    path = Path(config.get("names_path") or "")
    if not path.is_file():
        return {}
    try:
        names = json.loads(path.read_text()).get("names") or {}
    except ValueError:
        return {}
    return {code: (entry or {}).get("industry") for code, entry in names.items() if (entry or {}).get("industry")}


def scored(prepared, columns, weights, model, log=lambda *_: None):
    """combine() followed by the configured neutralisation: the score every backtest, search variant and
    diagnosis actually trades."""
    score, report = combine(prepared, columns, weights, model, log=log)
    if prepared.get("size") is not None:
        score = neutralize(score, prepared["size"], prepared.get("industry"))
    return score, report


def neutralize(score, size, industry):
    """Per day, the residual of the score's cross-sectional rank after removing log size (and industry means):
    what is left is the factor's view on a name relative to names of the same size and trade."""
    import numpy as np
    import pandas as pd

    frame = score.rename("score").to_frame().join(size.rename("size"), how="left")
    frame["score"] = frame.groupby(level="datetime")["score"].rank(pct=True)
    frame = frame.dropna(subset=["size"])
    if industry:
        frame["industry"] = frame.index.get_level_values("instrument").map(lambda c: industry.get(c, "其他"))
        frame["score"] = frame["score"] - frame.groupby([frame.index.get_level_values("datetime"), "industry"])["score"].transform("mean")
        frame["size"] = frame["size"] - frame.groupby([frame.index.get_level_values("datetime"), "industry"])["size"].transform("mean")
    def residual(day):
        x = day["size"].to_numpy(dtype=float)
        y = day["score"].to_numpy(dtype=float)
        if len(day) < 5 or np.nanstd(x) == 0:
            return pd.Series(y - np.nanmean(y), index=day.index)
        beta = np.cov(x, y, bias=True)[0, 1] / np.var(x)
        return pd.Series(y - np.mean(y) - beta * (x - np.mean(x)), index=day.index)
    out = frame.groupby(level="datetime", group_keys=False).apply(residual)
    return out.sort_index()


def combine(prepared, columns, weights, model, log=print):
    """Score a subset of the ranked signals: weighted rank blend, or a LightGBM fit on just those columns.

    Returns ``(score restricted to the backtest window, model report or None)``.
    """
    import numpy as np

    # Require every selected signal on a row; missing data is never treated as zero.
    ranks = prepared["ranks"][list(columns)].dropna()
    if model["method"] == "lgbm":
        score, report = train_lgbm_signal(ranks, prepared["label"], model, log=log)
        score = score[score.index.get_level_values("datetime") >= prepared["prior_day"]]
    else:
        w = np.array([float(x) for x in weights])
        score, report = ranks.mul(w, axis=1).sum(axis=1) / abs(w).sum(), None
    score = score.dropna().sort_index()
    if score.empty:
        raise ValueError("Selected factors have no complete observations")
    try:
        require_signal_coverage(score.index.get_level_values("datetime"), prepared["prior_day"], prepared["end_day"])
    except ValueError as error:
        raise ValueError(f"{signal_shortfall(prepared['ranks'][list(columns)], prepared['end_day'])} {error}") from None
    return score, report


def signal_shortfall(ranks, end_day):
    """Name the signals that stop before ``end_day`` and say what to do about it, for the coverage error."""
    import pandas as pd

    short = []
    for column in ranks.columns:
        dates = ranks[column].dropna().index.get_level_values("datetime")
        if len(dates) and dates.max() < pd.Timestamp(end_day):
            short.append(f"{column}（到 {dates.max().date()}）")
    if not short:
        return ""
    return f"信号 {'、'.join(short)} 没有覆盖到 {pd.Timestamp(end_day).date()}：把它重算到最新（因子库 → 重算到最新），或把结束日改到它的最后一天之前。"


def hold_scores(score, every, offset=0):
    """Refresh the signal only every ``every`` trading days: each day inside a block repeats the block's first
    cross-section. TopkDropout then finds nothing to swap on the other days, so the book turns over once per
    block instead of daily. ``offset`` shifts the block boundaries (days before the first boundary hold the
    first day's cross-section)."""
    if every <= 1:
        return score
    import pandas as pd

    days = score.index.get_level_values("datetime").unique().sort_values()
    pieces = []
    starts = list(range(offset % every if offset else 0, len(days), every))
    if not starts or starts[0] != 0:
        starts = [0] + starts
    for n, i in enumerate(starts):
        block = days[i:starts[n + 1]] if n + 1 < len(starts) else days[i:]
        first = score.xs(block[0], level="datetime")
        for day in block:
            pieces.append(pd.Series(first.values, index=pd.MultiIndex.from_arrays([[day] * len(first), first.index], names=["datetime", "instrument"])))
    return pd.concat(pieces).sort_index()


def staggered_scores(score, every, tranches):
    """``tranches`` held signals with evenly spaced refresh days, averaged: a fifth of the book refreshes every
    four days instead of all of it every twenty, so the result no longer hinges on which day the run began."""
    if tranches <= 1 or every <= 1:
        return hold_scores(score, every)
    import pandas as pd

    step = max(1, every // tranches)
    held = [hold_scores(score, every, k * step) for k in range(tranches)]
    return pd.concat(held, axis=1).mean(axis=1).sort_index()


BOOKS = ("equal", "topk")
# fills: how the equal-weight book's orders are filled. "ideal" trades any fraction of a share at a proportional
# fee with no price limits (the book the early evidence was built on); "real" follows A-share rules: 100-share
# lots (科创板 200 minimum, then any whole share), a minimum fee per order, no buying a name at its up-limit or
# selling one at its down-limit, no trading a suspended name, and real cash (an order larger than the cash left
# is cut). Blocked orders are retried every day until the next refresh.
FILLS = ("ideal", "real")
LOT = 100
STAR_MIN = 200
REBALANCE_BAND = 0.25  # real fills: a kept name is traded back to equal weight only when this far off target
TRADE_LOG_LIMIT = 5000  # trades kept in result.json; a whole-universe book turns over ~100k lines a year
LOTTERY_TOP10_SHARE = 0.5   # more than half the P&L from ten names: the result is a few stocks, not a selection edge
LOTTERY_WITHOUT_TOP3 = 0.5  # or losing the best three names removes more than half of the return
LOTTERY_MIN_NAMES = 60      # below this many traded names the shares are not judged (ten names is most of the book)


def daily_closes(instruments, start, end, field="$close"):
    """Adjusted prices (closes by default) as a (datetime × instrument) frame, suspended days forward-filled."""
    from qlib.data import D

    frame = D.features(sorted(set(instruments)), [field], start_time=start, end_time=end, freq="day")[field]
    if frame.index.names[0] == "instrument":
        frame = frame.swaplevel(0, 1)
    return frame.unstack("instrument").sort_index().ffill()


def universe_score(config):
    """A constant score over every priced member of the universe on every day of the window: run through
    equal_book it is the equal-weight universe, the baseline any selection (or screen) has to beat. Membership
    is point-in-time; Beijing names are left out of A-share universes (see studio_universe)."""
    import pandas as pd
    from qlib.data import D

    calendar = pd.DatetimeIndex(D.calendar(freq="day"))
    start = calendar[max(0, calendar.searchsorted(pd.Timestamp(config["start"])) - 2)]
    frame = D.features(D.instruments(config["market"]), ["$close"], start_time=start, end_time=config["end"], freq="day")["$close"]
    if frame.index.names[0] == "instrument":
        frame = frame.swaplevel(0, 1)
    frame = frame.dropna().sort_index()
    frame.index = frame.index.set_names(["datetime", "instrument"])
    spans = D.list_instruments(D.instruments(config["market"]), start_time=start, end_time=config["end"], as_list=False)
    frame = members_only(frame.to_frame("$close"), spans, calendar)["$close"]
    if (config.get("region") or "cn") == "cn":
        frame = frame[~frame.index.get_level_values("instrument").str.startswith("BJ")]
    return pd.Series(1.0, index=frame.index)


def equal_book(score, config, universe=None):
    """The equal-weight book: on the trading day after each signal refresh, hold the top ``topk`` names by the
    previous day's score at equal weight; positions drift with prices until the next refresh. Returns the daily
    report Qlib's would (return, cost, bench, turnover, account), the trade log, the closing book, the
    per-block membership, and the per-instrument P&L.

    ``universe=True`` holds every name that has a score that day instead of the top names (used with
    universe_score() for the equal-weight universe baseline, which stays an ideal-fill benchmark). With
    ``fills: "real"`` the orders follow A-share trading rules (see real_book); otherwise limit-up/down and lot
    sizes are ignored.
    """
    if config.get("fills", "ideal") == "real" and not universe:
        return real_book(score, config)
    import numpy as np
    import pandas as pd
    from qlib.data import D

    rebalance = int(config.get("rebalance", 1))
    held = hold_scores(score, rebalance)
    start, end = pd.Timestamp(config["start"]), pd.Timestamp(config["end"])
    calendar = pd.DatetimeIndex(D.calendar(freq="day"))
    trade_days = calendar[(calendar >= start) & (calendar <= end)]
    # The score arrives without NaN rows, so a sparse rule has no row at all on the days it is out of the market;
    # the refresh cadence therefore runs on the trading calendar, and a day without a score means cash.
    scored_days = set(held.index.get_level_values("datetime").unique())
    days = calendar[(calendar >= min(scored_days)) & (calendar <= end)]
    refresh_days = set(days[::rebalance])  # the block starts hold_scores() uses
    names = held.index.get_level_values("instrument").unique()
    first = calendar[max(0, calendar.searchsorted(start) - 1)]
    closes = daily_closes(names, first, end)
    # execution "open": names entering the book are bought at the trading day's open and marked to its close, so
    # the book earns that day's open→close on them (A-share overnight returns are negative, intraday positive;
    # see the review doc §21). Names leaving are still sold at the close. Default "close" buys at the close.
    at_open = config.get("execution", "close") == "open"
    opens = daily_closes(names, first, end, "$open") if at_open else None
    bench = D.features([config.get("benchmark", "SH000300")], ["$close"], start_time=trade_days[0], end_time=end, freq="day")["$close"].droplevel(0).reindex(trade_days).ffill()
    bench_ret = bench.pct_change().fillna(0.0)
    topk = int(config["topk"])
    account = float(config["account"])
    open_cost, close_cost = float(config["open_cost"]), float(config["close_cost"])
    value, weights = account, pd.Series(dtype=float)  # weights: instrument -> value held
    rows, trades, blocks, pnl = [], [], [], {}
    previous_day, current_set = None, None
    for day in trade_days:
        value_open, gained_today = value, 0.0  # the day's return is everything earned today over the value it started with
        # Mark to market from the previous close.
        if previous_day is not None and len(weights):
            ratio = (closes.loc[day, weights.index] / closes.loc[previous_day, weights.index]).fillna(1.0)
            gained = weights * (ratio - 1.0)
            for inst, g in gained.items():
                pnl[inst] = pnl.get(inst, 0.0) + float(g)
            weights = weights * ratio
            gained_today += float(gained.sum())
            value += float(gained.sum())
        # Yesterday's score decides today's book (Qlib's TopkDropout reads the previous day's prediction).
        signal_day = calendar[calendar.searchsorted(day) - 1]
        cost, turnover = 0.0, 0.0
        if signal_day in refresh_days or (current_set is None and signal_day in days):
            cross = held.xs(signal_day, level="datetime").dropna() if signal_day in scored_days else pd.Series(dtype="float64")
            priced = cross.index.intersection(closes.columns[closes.loc[day].notna()])
            cross = cross.reindex(priced)
            chosen = set(cross.index) if universe else set(cross.nlargest(topk).index)
            if chosen != current_set:  # an empty cross-section means cash: the book sells what it holds
                target = pd.Series(value / len(chosen), index=sorted(chosen)) if chosen else pd.Series(dtype="float64")
                merged = pd.concat([weights.rename("now"), target.rename("target")], axis=1).fillna(0.0)
                delta = merged["target"] - merged["now"]
                sold, bought = float(-delta[delta < 0].sum()), float(delta[delta > 0].sum())
                cost = sold * close_cost + bought * open_cost
                turnover = (sold + bought) / 2 / value if value else 0.0
                for inst, d in delta[delta.abs() > 1e-9].items():
                    price = float(opens.loc[day, inst]) if at_open and d > 0 and pd.notna(opens.loc[day, inst]) else float(closes.loc[day, inst])
                    trades.append({"date": str(day.date()), "instrument": str(inst), "direction": "buy" if d > 0 else "sell",
                                   "amount": abs(float(d)) / price, "price": price, "value": abs(float(d)),
                                   "cost": abs(float(d)) * (open_cost if d > 0 else close_cost)})
                for inst in delta.index:
                    pnl[inst] = pnl.get(inst, 0.0) - abs(float(delta[inst])) * (open_cost if delta[inst] > 0 else close_cost)
                value -= cost
                weights = target * (value / target.sum()) if target.sum() else target
                if at_open and len(weights):
                    # Amounts bought at the open are worth open→close more (or less) by this close.
                    bought_now = delta[delta > 1e-9].index.intersection(weights.index)
                    if len(bought_now):
                        ratio = (closes.loc[day, bought_now] / opens.loc[day, bought_now]).fillna(1.0)
                        share = (delta[bought_now] / target[bought_now]).clip(upper=1.0)  # the part of the position bought today
                        gain = weights[bought_now] * share * (ratio - 1.0)
                        for inst, g in gain.items():
                            pnl[inst] = pnl.get(inst, 0.0) + float(g)
                        weights[bought_now] = weights[bought_now] + gain
                        gained_today += float(gain.sum())
                        value += float(gain.sum())
                current_set = chosen
                blocks.append({"date": str(day.date()), "names": len(chosen)})
        day_return = gained_today / value_open if value_open else 0.0
        rows.append({"date": day, "return": day_return, "cost": cost / value_open if value_open else 0.0, "bench": float(bench_ret.loc[day]), "turnover": turnover, "account": value})
        previous_day = day
    report = pd.DataFrame(rows).set_index("date")  # return is gross of cost, as in Qlib's report
    positions = [{"instrument": str(inst), "amount": float(v / closes.loc[previous_day, inst]), "price": float(closes.loc[previous_day, inst]), "value": float(v), "weight": float(v / value)}
                 for inst, v in weights.sort_values(ascending=False).items()] if len(weights) else []
    holdings = {"positions": positions, "cash": 0.0, "total": float(value), "as_of": str(previous_day.date()) if previous_day is not None else None}
    instruments = sorted(({"instrument": inst, "pnl": float(p), "held": inst in weights.index, "trades": sum(1 for t in trades if t["instrument"] == inst),
                           "holding_value": float(weights.get(inst, 0.0))} for inst, p in pnl.items()), key=lambda r: -r["pnl"])
    return report, trades, holdings, instruments, blocks


def lot_shares(instrument, value, raw_price):
    """Whole shares an order of ``value`` yuan buys at ``raw_price`` under A-share lot rules; 0 below one lot."""
    import math

    if not raw_price or not math.isfinite(raw_price) or raw_price <= 0 or value <= 0:
        return 0
    shares = value / raw_price
    if instrument.startswith("SH68"):
        return int(shares) if shares >= STAR_MIN else 0
    return int(shares // LOT) * LOT


def price_limit(instrument, config):
    """The daily price limit as a fraction: 20% on ChiNext and STAR, the market's configured limit elsewhere."""
    return 0.195 if instrument.startswith(("SZ30", "SH68")) else float(config.get("limit_threshold", 0.095))


def real_book(score, config):
    """The equal-weight book filled the way an A-share account is. Holds cash and positions in adjusted units
    (value = units × adjusted price; raw shares = units × factor). On the trading day after each signal refresh it
    sells what left the book and trims or tops up kept names that drifted more than REBALANCE_BAND from equal
    weight, then buys the new names, all at one price point (the open with ``execution: "open"``, else the close):

    - orders are rounded down to whole lots on the raw price; a name whose single lot costs more than its share
      of the book is not bought (counted as unaffordable)
    - every order pays max(value × rate, min_cost)
    - a name trading at or beyond its up-limit cannot be bought, at or beyond its down-limit cannot be sold, and a
      suspended name cannot be traded; those orders wait and are retried each day until the next refresh
    - buys are cut to the cash left

    Same return shape as equal_book; ``holdings`` also carries the cash and a ``fills`` tally.
    """
    import numpy as np
    import pandas as pd
    from qlib.data import D

    rebalance = int(config.get("rebalance", 1))
    held = hold_scores(score, rebalance)
    start, end = pd.Timestamp(config["start"]), pd.Timestamp(config["end"])
    calendar = pd.DatetimeIndex(D.calendar(freq="day"))
    trade_days = calendar[(calendar >= start) & (calendar <= end)]
    scored_days = set(held.index.get_level_values("datetime").unique())  # see equal_book: no score on a day means cash
    days = calendar[(calendar >= min(scored_days)) & (calendar <= end)]
    refresh_days = set(days[::rebalance])
    names = held.index.get_level_values("instrument").unique()
    first = calendar[max(0, calendar.searchsorted(start) - 1)]
    closes = daily_closes(names, first, end)
    at_open = config.get("execution", "close") == "open"
    opens = daily_closes(names, first, end, "$open") if at_open else closes
    factors = daily_closes(names, first, end, "$factor")
    volume = D.features(sorted(set(names)), ["$volume"], start_time=first, end_time=end, freq="day")["$volume"]
    if volume.index.names[0] == "instrument":
        volume = volume.swaplevel(0, 1)
    traded = volume.unstack("instrument").reindex(index=closes.index, columns=closes.columns).fillna(0.0) > 0
    bench = D.features([config.get("benchmark", "SH000300")], ["$close"], start_time=trade_days[0], end_time=end, freq="day")["$close"].droplevel(0).reindex(trade_days).ffill()
    bench_ret = bench.pct_change().fillna(0.0)
    topk = int(config["topk"])
    open_cost, close_cost = float(config["open_cost"]), float(config["close_cost"])
    min_cost = float(config.get("min_cost", 5))

    cash = float(config["account"])
    units = pd.Series(dtype=float)
    pending = {}  # instrument -> target value still to buy (> 0) or units still to sell (as a negative number)
    invested, returned = {}, {}
    rows, trades, blocks = [], [], []
    tally = {"orders": 0, "filled": 0, "blocked_limit": 0, "blocked_suspended": 0, "unaffordable": 0, "cash_short": 0}
    previous_day, current_set, value_prev = None, None, cash

    def fee(amount, rate):
        return max(amount * rate, min_cost) if amount > 0 else 0.0

    def blocked(inst, day, price, buying):
        if not bool(traded.at[day, inst]):
            return "blocked_suspended"
        prev = closes.at[calendar[calendar.searchsorted(day) - 1], inst] if calendar.searchsorted(day) > 0 else np.nan
        if pd.notna(prev) and prev > 0:
            move = price / prev - 1.0
            limit = price_limit(inst, config)
            if (buying and move >= limit) or (not buying and move <= -limit):
                return "blocked_limit"
        return None

    for day in trade_days:
        cost_today, turnover_value = 0.0, 0.0
        price_row, factor_row = opens.loc[day], factors.loc[day]

        def sell(inst, sell_units, day=day, price_row=price_row, factor_row=factor_row):
            nonlocal cash, units, cost_today, turnover_value
            price = float(price_row.get(inst, np.nan))
            reason = blocked(inst, day, price, buying=False) if pd.notna(price) else "blocked_suspended"
            if reason:
                tally[reason] += 1
                return False
            have = float(units.get(inst, 0.0))
            sell_units = min(sell_units, have)
            if sell_units < have - 1e-9:  # a partial sell goes in whole lots of raw shares
                factor = float(factor_row.get(inst, 1.0)) or 1.0
                raw = sell_units * factor
                raw = int(raw) if inst.startswith("SH68") else int(raw // LOT) * LOT
                sell_units = raw / factor
                if sell_units <= 0:
                    return True
            proceeds = sell_units * price
            charge = fee(proceeds, close_cost)
            cash += proceeds - charge
            cost_today += charge
            turnover_value += proceeds
            returned[inst] = returned.get(inst, 0.0) + proceeds - charge
            units[inst] = have - sell_units
            if units[inst] <= 1e-9:
                units = units.drop(inst)
            trades.append({"date": str(day.date()), "instrument": str(inst), "direction": "sell", "amount": float(sell_units),
                           "price": price, "value": float(proceeds), "cost": float(charge)})
            tally["filled"] += 1
            return True

        def buy(inst, value, day=day, price_row=price_row, factor_row=factor_row):
            """Buy up to ``value`` yuan of ``inst``; returns the value still wanted (0 when done or not possible)."""
            nonlocal cash, units, cost_today, turnover_value
            price = float(price_row.get(inst, np.nan))
            reason = blocked(inst, day, price, buying=True) if pd.notna(price) else "blocked_suspended"
            if reason:
                tally[reason] += 1
                return value
            factor = float(factor_row.get(inst, 1.0)) or 1.0
            raw_price = price / factor
            spend = min(value, cash)
            shares = lot_shares(inst, spend, raw_price)
            while shares > 0 and shares * raw_price + fee(shares * raw_price, open_cost) > cash:
                shares -= 1 if inst.startswith("SH68") else LOT
                if inst.startswith("SH68") and shares < STAR_MIN:
                    shares = 0
            if shares <= 0:
                tally["unaffordable" if value <= cash else "cash_short"] += 1
                return 0.0
            amount = shares * raw_price
            charge = fee(amount, open_cost)
            cash -= amount + charge
            cost_today += charge
            turnover_value += amount
            invested[inst] = invested.get(inst, 0.0) + amount + charge
            bought_units = shares / factor
            units[inst] = float(units.get(inst, 0.0)) + bought_units
            trades.append({"date": str(day.date()), "instrument": str(inst), "direction": "buy", "amount": float(bought_units),
                           "price": price, "value": float(amount), "cost": float(charge)})
            tally["filled"] += 1
            return 0.0

        signal_day = calendar[calendar.searchsorted(day) - 1]
        refreshed = signal_day in refresh_days or (current_set is None and signal_day in days)
        if refreshed:
            cross = held.xs(signal_day, level="datetime").dropna() if signal_day in scored_days else pd.Series(dtype="float64")
            priced = cross.index.intersection(closes.columns[closes.loc[day].notna()])
            cross = cross.reindex(priced)
            chosen = set(cross.nlargest(topk).index)
            if chosen or len(units):  # an empty cross-section means cash: the book sells what it holds
                pending = {}
                marks = price_row.reindex(units.index).fillna(closes.loc[day].reindex(units.index))
                book_value = cash + float((units * marks).sum())
                target = book_value / len(chosen) if chosen else 0.0
                for inst in sorted(set(units.index) - chosen):  # leavers: sell everything
                    tally["orders"] += 1
                    if not sell(inst, float(units[inst])):
                        pending[inst] = -float(units.get(inst, 0.0))
                for inst in sorted(chosen & set(units.index)):  # kept names: trim when far above target
                    now = float(units[inst] * marks[inst])
                    if now > target * (1 + REBALANCE_BAND):
                        tally["orders"] += 1
                        excess_units = (now - target) / float(marks[inst])
                        if not sell(inst, excess_units):
                            pending[inst] = -excess_units
                wants = {}
                # Buy in score order (a rule's score carries the signal's freshness), so when cash runs out it is the
                # weakest names that go unbought rather than whichever sort last by code.
                for inst in sorted(chosen, key=lambda i: (-float(cross.get(i, 0.0)), i)):
                    now = float(units.get(inst, 0.0)) * float(marks.get(inst, np.nan)) if inst in units.index else 0.0
                    if inst not in units.index or now < target * (1 - REBALANCE_BAND):
                        wants[inst] = target - now
                for inst, want in wants.items():
                    tally["orders"] += 1
                    left = buy(inst, want)
                    if left > 0:
                        pending[inst] = left
                current_set = chosen
                blocks.append({"date": str(day.date()), "names": len(chosen)})
        elif pending:
            for inst, amount in list(pending.items()):
                if amount < 0:
                    if sell(inst, -amount):
                        pending.pop(inst)
                else:
                    left = buy(inst, amount)
                    if left > 0:
                        pending[inst] = left
                    else:
                        pending.pop(inst)

        marks_close = closes.loc[day].reindex(units.index)
        value = cash + float((units * marks_close.fillna(0.0)).sum())
        gross = value + cost_today - value_prev
        rows.append({"date": day, "return": gross / value_prev if value_prev else 0.0, "cost": cost_today / value_prev if value_prev else 0.0,
                     "bench": float(bench_ret.loc[day]), "turnover": turnover_value / 2 / value_prev if value_prev else 0.0, "account": value})
        value_prev, previous_day = value, day

    report = pd.DataFrame(rows).set_index("date")
    last = closes.loc[previous_day] if previous_day is not None else pd.Series(dtype=float)
    positions = [{"instrument": str(inst), "amount": float(u), "price": float(last[inst]), "value": float(u * last[inst]), "weight": float(u * last[inst] / value_prev)}
                 for inst, u in units.items() if pd.notna(last.get(inst))]
    positions.sort(key=lambda r: -r["value"])
    holdings = {"positions": positions, "cash": float(cash), "total": float(value_prev), "as_of": str(previous_day.date()) if previous_day is not None else None, "fills": tally}
    names_seen = set(invested) | set(returned)
    instruments = sorted(({"instrument": inst, "pnl": float(returned.get(inst, 0.0) - invested.get(inst, 0.0) + (float(units[inst] * last[inst]) if inst in units.index and pd.notna(last.get(inst)) else 0.0)),
                           "held": inst in units.index, "trades": sum(1 for t in trades if t["instrument"] == inst),
                           "holding_value": float(units[inst] * last[inst]) if inst in units.index and pd.notna(last.get(inst)) else 0.0}
                          for inst in names_seen), key=lambda r: -r["pnl"])
    return report, trades, holdings, instruments, blocks


def lottery_diagnosis(instruments, total_return, max_weight=None):
    """Is the return a selection edge or a few names? Shares of the total P&L held by the best names, the
    return left when the best three are taken out, and how many names made money at all."""
    pnls = sorted((float(r["pnl"]) for r in instruments), reverse=True)
    total = sum(pnls)
    if not pnls or total <= 0:
        return {"names": len(pnls), "top10_share": None, "top3_share": None, "return_without_top3": None,
                "positive_share": float(sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None, "max_weight": max_weight, "lottery": False}
    top3, top10 = sum(pnls[:3]) / total, sum(pnls[:10]) / total
    without = total_return * (1 - top3)
    # Ten names are a third of a 30-name book: the shares only say something about a book of some breadth.
    judged = len(pnls) >= LOTTERY_MIN_NAMES
    return {"names": len(pnls), "top10_share": top10, "top3_share": top3, "return_without_top3": without,
            "positive_share": float(sum(1 for p in pnls if p > 0) / len(pnls)), "max_weight": max_weight,
            "lottery": bool(judged and (top10 > LOTTERY_TOP10_SHARE or (total_return > 0 and without < LOTTERY_WITHOUT_TOP3 * total_return)))}


def book_report(score, config):
    """The daily report of the configured book: Qlib's TopkDropout or the equal-weight book."""
    if config.get("book", "equal") == "topk":
        return backtest_score(score, config)[0]
    return equal_book(score, config)[0]


def backtest_score(score, config):
    """Run Qlib's TopkDropout backtest on ``score``; returns the daily report and Qlib's positions/indicators."""
    from qlib.backtest import backtest

    rebalance = int(config.get("rebalance", 1))
    tranches = int(config.get("stagger", 1) or 1)
    strategy = {"class": "TopkDropoutStrategy", "module_path": "qlib.contrib.strategy",
                "kwargs": {"signal": staggered_scores(score, rebalance, tranches), "topk": config["topk"], "n_drop": config["n_drop"],
                           "hold_thresh": max(1, rebalance // tranches)}}
    portfolios, indicators = backtest(
        start_time=config["start"], end_time=config["end"], strategy=strategy,
        executor={"class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
                  "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True}},
        account=config["account"], benchmark=config.get("benchmark", "SH000300"),
        # Exchange rules come from the universe's market (A-shares: 9.5% limit, min 5; US: no limit, min 1).
        exchange_kwargs={"freq": "day", "limit_threshold": config.get("limit_threshold", 0.095), "deal_price": "close",
                         "open_cost": config["open_cost"], "close_cost": config["close_cost"], "min_cost": config.get("min_cost", 5)},
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
    window = prepared["ranks"][prepared["ranks"].index.get_level_values("datetime") >= prepared["prior_day"]].dropna()
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


def latest_scores(score, topk):
    """The last signal day's ranking: what the strategy would buy next, for the signal export."""
    last = score.index.get_level_values("datetime").max()
    day = score.xs(last, level="datetime").sort_values(ascending=False)
    keep = max(2 * int(topk), 20)
    return {"date": str(last.date()), "universe": int(len(day)),
            "scores": [{"instrument": str(inst), "score": float(v), "rank": i + 1} for i, (inst, v) in enumerate(day.head(keep).items())]}


# Style spreads: what a plain price-based tilt earned each day, from the previous close's information.
# The recent-performance read-out regresses the strategy's daily return on the benchmark and these four
# to say how much of a bad week was the market, a style the strategy leans on, or its own picks.
STYLES = {
    "momentum": "Ref($close, 1) / Ref($close, 21) - 1",        # 20-day return
    "reversal": "Ref($close, 6) / Ref($close, 1) - 1",          # minus the 5-day return: high = fell lately
    "volatility": "Ref(Std($close / Ref($close, 1) - 1, 20), 1)",
    "liquidity": "Ref(Mean($close * $volume, 20), 1)",          # traded value, a size proxy
}


def load_style_frame(market, start, end):
    """(datetime, instrument) rows of the day's return and each style's prior-close value over the universe."""
    from qlib.data import D

    frame = D.features(D.instruments(market), ["$close / Ref($close, 1) - 1", *STYLES.values()], start_time=start, end_time=end, freq="day")
    frame.columns = ["ret", *STYLES]
    if frame.index.names[0] == "instrument":
        frame = frame.swaplevel(0, 1)
    return frame.sort_index()


def style_spreads(frame, quantile=0.2, min_names=10):
    """Daily top-minus-bottom quintile return of each style, as rows; a style with too few names that day is null."""
    rows = []
    for day, cross in frame.groupby(level="datetime"):
        row = {"date": str(day.date())}
        for name in STYLES:
            pairs = cross[[name, "ret"]].dropna()
            if len(pairs) < min_names:
                row[name] = None
                continue
            k = max(1, int(len(pairs) * quantile))
            ordered = pairs.sort_values(name)["ret"]
            row[name] = float(ordered.iloc[-k:].mean() - ordered.iloc[:k].mean())
        rows.append(row)
    return rows


def bench_returns(rows):
    """Daily benchmark returns recovered from the cumulative benchmark curve in the report rows."""
    out, prev = [], 1.0
    for row in rows:
        out.append(row["benchmark"] / prev - 1)
        prev = row["benchmark"]
    return out


def fit_exposures(rows, styles, min_days=30):
    """OLS of the daily net return on the benchmark and the style spreads over the whole run.

    Returns ``{"betas": {"alpha", "market", <styles>}, "r2", "days"}`` or None when too few days line up.
    """
    import numpy as np

    by_date = {s["date"]: s for s in styles}
    bench = bench_returns(rows)
    X, y = [], []
    for row, b in zip(rows, bench):
        s = by_date.get(row["date"])
        if not s or any(s.get(name) is None for name in STYLES):
            continue
        X.append([1.0, b, *(s[name] for name in STYLES)])
        y.append(row["return"])
    if len(y) < min_days:
        return None
    X, y = np.array(X), np.array(y)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    fitted = X @ beta
    total = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(((y - fitted) ** 2).sum()) / total if total > 0 else None
    return {"betas": dict(zip(["alpha", "market", *STYLES], (float(v) for v in beta))), "r2": r2, "days": int(len(y))}


HORIZONS = (("week", 5), ("month", 21))


def _compound(values):
    total = 1.0
    for v in values:
        total *= 1 + v
    return total - 1


def _percentile(population, value):
    """Share of the population below ``value`` (ties count half), 0…1."""
    below = sum(1 for v in population if v < value)
    ties = sum(1 for v in population if v == value)
    return (below + ties / 2) / len(population)


def _quantile(sorted_values, q):
    pos = q * (len(sorted_values) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _reading(horizon):
    """One word on what the recent window looks like, from the numbers already in ``horizon``."""
    if horizon["percentile"] >= 0.10:
        return "normal"
    ic, attribution = horizon.get("ic"), horizon.get("attribution")
    if ic is not None and ic["percentile"] < 0.10:
        return "drift"
    if attribution is None:
        return "needs_update" if ic is None else "specific"
    explained = attribution["market"] + sum(attribution["styles"].values())
    if abs(explained) >= abs(attribution["residual"]):
        return "market" if abs(attribution["market"]) >= abs(sum(attribution["styles"].values())) else "style"
    return "specific"


def recent_context(result):
    """近期表现在历史中的位置: the last week and month of a finished run against the run's own history.

    For each horizon: compounded net and benchmark return, where the net return sits among every rolling
    window of the same length in the run (percentile, spread), the same for the signal's mean IC when the
    run stored daily IC, and, when it stored style spreads and exposures, the arithmetic split of the
    window's return into alpha drift, market, styles and residual. ``reading`` names the picture.
    """
    rows = result.get("rows") or []
    if len(rows) < 2 * HORIZONS[0][1]:
        return None
    net = [r["return"] for r in rows]
    bench = bench_returns(rows)
    ic_by_date = {r["date"]: r["ic"] for r in result.get("ic_rows") or [] if r.get("ic") is not None}
    ics = [ic_by_date.get(r["date"]) for r in rows]
    styles_by_date = {s["date"]: s for s in result.get("style_rows") or []}
    betas = (result.get("attribution") or {}).get("betas")
    out = {"as_of": rows[-1]["date"], "start": rows[0]["date"], "days": len(rows), "horizons": []}
    for key, n in HORIZONS:
        if len(rows) < 2 * n:
            continue
        windows = [_compound(net[i - n:i]) for i in range(n, len(rows) + 1)]
        ordered = sorted(windows)
        ret = windows[-1]
        horizon = {"key": key, "days": n, "start": rows[-n]["date"], "end": rows[-1]["date"],
                   "return": ret, "benchmark": _compound(bench[-n:]), "excess": ret - _compound(bench[-n:]),
                   "percentile": _percentile(windows, ret), "windows": len(windows),
                   "low": ordered[0], "p10": _quantile(ordered, 0.1), "median": _quantile(ordered, 0.5), "p90": _quantile(ordered, 0.9), "high": ordered[-1]}
        ic_windows = []
        for i in range(n, len(rows) + 1):
            values = [v for v in ics[i - n:i] if v is not None]
            ic_windows.append(sum(values) / len(values) if len(values) >= (n + 1) // 2 else None)
        # A signal predicting h-day returns has no IC for the last h days (the label is not complete yet), so
        # the newest complete window is used and dated; the reading then judges the signal as of that day.
        last = max((i for i, v in enumerate(ic_windows) if v is not None), default=None)
        if last is not None and sum(v is not None for v in ic_windows) >= 2:
            population = [v for v in ic_windows if v is not None]
            all_ic = [v for v in ics if v is not None]
            # ``end`` is the last day that actually has an IC inside that window (the label horizon leaves
            # the newest days empty), ``lag`` how many trading days the window trails the return window.
            last_ic_day = max(i for i in range(last, last + n) if ics[i] is not None)
            horizon["ic"] = {"recent": ic_windows[last], "percentile": _percentile(population, ic_windows[last]), "mean": sum(all_ic) / len(all_ic),
                             "end": rows[last_ic_day]["date"], "lag": len(rows) - 1 - last_ic_day}
        recent_styles = [styles_by_date.get(r["date"]) for r in rows[-n:]]
        if betas and all(s and all(s.get(name) is not None for name in STYLES) for s in recent_styles):
            market = betas["market"] * sum(bench[-n:])
            styles = {name: betas[name] * sum(s[name] for s in recent_styles) for name in STYLES}
            alpha = betas["alpha"] * n
            actual = sum(net[-n:])
            horizon["attribution"] = {"actual": actual, "alpha": alpha, "market": market, "styles": styles,
                                      "residual": actual - alpha - market - sum(styles.values())}
        horizon["reading"] = _reading(horizon)
        out["horizons"].append(horizon)
    return clean(out) if out["horizons"] else None


def run(config):
    prepared = prepare(config)
    config = prepared["config"]  # possibly with the end day clamped; see prepare()
    factors, model = prepared["factors"], prepared["model"]
    score, model_report = scored(prepared, [f["name"] for f in factors], [f["weight"] for f in factors], model, log=print)
    if prepared.get("size") is not None:
        prepared["notes"].append("打分已做" + ("规模 + 行业" if prepared.get("industry") else "规模") + "中性化，再进选股")
    ic, rank_ic = daily_ic(score, prepared["label"])
    test_ic, test_rank_ic = (float(ic.mean()) if ic is not None and len(ic) else None, float(rank_ic.mean()) if rank_ic is not None and len(rank_ic) else None)
    signal = latest_scores(score, config["topk"])
    baseline = None
    if config.get("book", "equal") == "topk":
        report, positions, indicator = backtest_score(score, config)
        trades = trades_from_indicator(getattr(indicator, "order_indicator_his", {}))
        last_day = max(positions) if positions else None
        holdings = holdings_from_position(positions[last_day]) if last_day is not None else {"positions": [], "cash": None, "total": None}
        max_weight = max((float(positions[d].get_stock_weight(i)) for d in positions for i in positions[d].get_stock_list()), default=None)
        if last_day is not None:
            holdings["as_of"] = str(getattr(last_day, "date", lambda: last_day)())
            traded = {t["instrument"] for t in trades} | {r["instrument"] for r in holdings["positions"]}
            trades, holdings = unadjust_book(trades, holdings, load_factors(traded, config["start"], holdings["as_of"]))
        instruments = instrument_summary(trades, holdings)
    else:
        report, trades, holdings, instruments, _ = equal_book(score, config)
        max_weight = max((r["weight"] for r in holdings["positions"]), default=None)
        traded = {t["instrument"] for t in trades} | {r["instrument"] for r in holdings["positions"]}
        trades, holdings = unadjust_book(trades, holdings, load_factors(traded, config["start"], holdings["as_of"]))
        # The equal-weight universe on the same days and cadence: what holding every member would have made.
        universe_report = equal_book(universe_score(config), config, universe=True)[0]
        universe_metrics, universe_rows = summarize_report(universe_report)
        baseline = {"universe_return": universe_metrics["total_return"], "universe_sharpe": universe_metrics["sharpe"],
                    "equity": [[r["date"], round(r["equity"], 6)] for r in universe_rows]}
    metrics, rows = summarize_report(report)
    lottery = lottery_diagnosis(instruments, metrics["total_return"], max_weight)
    trades_total = len(trades)
    if trades_total > TRADE_LOG_LIMIT:
        trades = trades[-TRADE_LOG_LIMIT:]  # the most recent ones; the per-instrument P&L keeps the whole picture
    if baseline is not None:
        baseline["selection_return"] = metrics["total_return"] - baseline["universe_return"]
        net = (report["return"] - report["cost"]) - (universe_report["return"] - universe_report["cost"])
        monthly = net.groupby(net.index.to_period("M")).sum()
        baseline["selection_t"] = float(monthly.mean() / monthly.std(ddof=1) * (len(monthly) ** 0.5)) if len(monthly) > 2 and monthly.std(ddof=1) > 0 else None
    if lottery["lottery"]:
        prepared["notes"].append(f"彩票结构：前 10 只股票占盈亏 {lottery['top10_share']:.0%}，去掉前 3 只后收益 {lottery['return_without_top3']:+.1%}（原 {metrics['total_return']:+.1%}）")
    # Style spreads and exposures feed the recent-performance read-out; they are a side dish, so a failure
    # here is noted rather than failing the backtest.
    try:
        style_rows = style_spreads(load_style_frame(config["market"], config["start"], config["end"]))
        attribution = fit_exposures(rows, style_rows)
    except Exception as error:  # noqa: BLE001
        style_rows, attribution = [], None
        prepared["notes"].append(f"风格归因未计算：{error}")
    return clean({"metrics": {**metrics, "signal_ic": test_ic, "signal_rank_ic": test_rank_ic},
                  "model": model_report, "lottery": lottery, "baseline": baseline,
                  "rows": rows, "config": config,
                  "ic_rows": ic_rows(ic, rank_ic), "style_rows": style_rows, "attribution": attribution,
                  "trades": trades, "trades_total": trades_total, "holdings": holdings, "instruments": instruments, "latest_signal": signal,
                  "diagnosis": signal_diagnosis(prepared, score) if len(factors) > 1 else None,
                  "notes": prepared["notes"],
                  "method": ("Equal-weight book: top names at equal weight on the day after each signal refresh, drifting in between; "
                             + ("buys at the open, sells at the close; " if config.get("execution") == "open" else "")
                             + ("A-share fills: 100-share lots, minimum fee per order, no buying at the up-limit or selling at the down-limit, suspended names untradable, real cash. "
                                if config.get("fills") == "real" else "no lot sizes or price limits. ") if config.get("book", "equal") == "equal" else "Qlib TopkDropout book. ")
                            + "Net-of-cost compounded returns; 252 trading days; Sharpe risk-free rate = 0. Previous-day signals, close execution."})


def diagnose(config, progress=lambda *_: None):
    """Take the portfolio apart: every signal alone, and the portfolio without each signal, on the same window.

    Each variant is scored the same way the portfolio was (rank blend with the configured weights, or a
    LightGBM refit on the remaining columns) and put through the same backtest. ``progress`` is called
    with (done, total) after each variant.
    """
    prepared = prepare(config)
    config = prepared["config"]
    factors, model = prepared["factors"], prepared["model"]
    if len(factors) < 2:
        raise ValueError("Diagnosis needs at least two signals")
    names = [f["name"] for f in factors]
    weights = {f["name"]: f["weight"] for f in factors}

    def variant(columns):
        score, _ = scored(prepared, columns, [weights[c] for c in columns], model)
        ic, rank_ic = information_coefficient(score, prepared["label"])
        metrics, rows = summarize_report(book_report(score, config))
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


def singles_failure(singles):
    """The message when no candidate could be backtested alone: each distinct cause with the names it hit."""
    by_cause = {}
    for name, metrics in singles.items():
        by_cause.setdefault(str(metrics.get("error", "unknown error")), []).append(name)
    detail = "；".join(f"{'、'.join(names)}：{cause}" for cause, names in by_cause.items())
    return f"No candidate could be backtested alone on the search window. {detail}"


def walkforward(config, progress=lambda *_: None):
    """走前向: re-select the factor set every fold from the training window before it, hold it through the
    fold, and judge the strategy on the folds strung together.

    At each fold start the candidates are scored on the ``train_days`` trading days ending ``horizon + 1``
    days before it (so no label reaches into the fold): size-neutral daily Rank IC of the factor against the
    1-day label, t = mean / std × √n. Factors with |t| ≥ ``select_t`` enter, signed by the IC, at most
    ``max_factors`` of them (strongest first); a fold with no admitted factor stays in cash. The portfolio is
    the same rank blend, neutralised as configured, backtested inside the fold. A fixed-set baseline (every
    candidate with its given weight, never re-selected) runs beside it.
    """
    import numpy as np
    import pandas as pd
    from qlib.data import D

    wf = config["walkforward"]
    # Features must reach back one training window (plus the label gap) before the first fold.
    import qlib
    provider = Path(config["provider_uri"]).expanduser().resolve()
    qlib.init(provider_uri=str(provider), region=config.get("region") or "cn")
    calendar = D.calendar(freq="day")
    first_fold = pd.Timestamp(config["start"])
    before = calendar[calendar < first_fold]
    if len(before) < wf["train_days"] + config["horizon"] + 2:
        raise ValueError(f"Not enough history before {config['start']} for a {wf['train_days']}-day training window")
    feature_start = before[-(wf["train_days"] + config["horizon"] + 1)]
    prepared = prepare({**config, "feature_start": str(feature_start.date()), "neutral": config.get("neutral", "none")})
    config = prepared["config"]
    calendar = prepared["calendar"]
    ranks, size, industry = prepared["ranks"], prepared.get("size"), prepared.get("industry")
    # 1-day label for selection (the gate's dominant horizon), z-scored per day like the portfolio label.
    label1 = D.features(D.instruments(config["market"]), ["Ref($close, -2)/Ref($close, -1) - 1"],
                        start_time=str(feature_start.date()), end_time=config["end"], freq="day").iloc[:, 0]
    if label1.index.names[0] == "instrument":
        label1 = label1.swaplevel(0, 1)
    label1 = cross_sectional_zscore(label1.sort_index())
    if size is None:
        # Selection is always size-neutral, whatever the portfolio does, so it matches the gate.
        size_raw = D.features(D.instruments(config["market"]), ["Log(Ref(Mean($close*$volume, 20), 1))"],
                              start_time=str(feature_start.date()), end_time=config["end"], freq="day").iloc[:, 0]
        if size_raw.index.names[0] == "instrument":
            size_raw = size_raw.swaplevel(0, 1)
        size = size_raw.sort_index()
    names = [f["name"] for f in prepared["factors"]]
    given = {f["name"]: float(f["weight"]) for f in prepared["factors"]}
    days = calendar[(calendar >= pd.Timestamp(config["start"])) & (calendar <= pd.Timestamp(config["end"]))]
    folds = [(days[i], days[min(i + wf["fold_days"], len(days)) - 1]) for i in range(0, len(days), wf["fold_days"])]
    if len(folds) > 1 and (folds[-1][1] - folds[-1][0]).days < 20:
        folds[-2] = (folds[-2][0], folds[-1][1])
        folds.pop()
    dates = ranks.index.get_level_values("datetime")

    def factor_t(name, train_start, train_end):
        window = ranks[name][(dates >= train_start) & (dates <= train_end)].dropna()
        if window.empty:
            return None, None
        neutral = neutralize(window, size, industry)
        if wf.get("select_by", "book") == "book":
            return factor_book_t(neutral)
        ic, rank_ic = daily_ic(neutral, label1)
        if len(rank_ic) < 40 or rank_ic.std() == 0:
            return None, None
        return float(rank_ic.mean() / rank_ic.std() * np.sqrt(len(rank_ic))), float(rank_ic.mean())

    def factor_book_t(neutral):
        """The part's own book over the training window: every ``rebalance`` days, the top ``topk`` names by the
        neutral score held ``horizon`` days at equal weight, minus every scored name; both directions are
        tried and the better one is reported with its sign. Returns (t, mean excess in label units)."""
        try:
            from studio_analysis import book_series
        except ImportError:  # imported as a package module (tests)
            from rdagent.log.server.studio_analysis import book_series

        best = (None, None)
        for sign in (1.0, -1.0):
            series = book_series(neutral * sign, prepared["label"], int(config["topk"]), int(config.get("rebalance", 1)))
            if len(series) < 6 or series.std(ddof=1) == 0:
                continue
            t = float(series.mean() / series.std(ddof=1) * np.sqrt(len(series)))
            if t <= 0:
                continue
            if best[0] is None or t > best[0]:
                best = (t * sign, float(series.mean()) * sign)
        return best

    # Each fold's selection scores its own dates; the pieces are stitched into one signal and backtested once,
    # so the book carries over between folds (restarting it every fold resets the rebalance cadence, which
    # alone moves a monthly strategy's result by tens of points).
    results, pieces, previous = [], [], None
    for k, (fold_start, fold_end) in enumerate(folds):
        train_end_i = int(np.searchsorted(calendar, fold_start)) - config["horizon"] - 1
        train_end = calendar[train_end_i]
        train_start = calendar[max(0, train_end_i - wf["train_days"] + 1)]
        judged = []
        for name in names:
            t, ic = factor_t(name, train_start, train_end)
            judged.append({"name": name, "t": t, "ic": ic})
        admitted = sorted([j for j in judged if j["t"] is not None and abs(j["t"]) >= wf["select_t"]], key=lambda j: -abs(j["t"]))[:wf["max_factors"]]
        selected = [{"name": j["name"], "weight": 1.0 if j["t"] > 0 else -1.0, "t": round(j["t"], 2), "ic": round(j["ic"], 4)} for j in admitted]
        fold = {"start": str(fold_start.date()), "end": str(fold_end.date()), "train": [str(train_start.date()), str(train_end.date())],
                "selected": selected, "judged": [{**j, "t": None if j["t"] is None else round(j["t"], 2), "ic": None if j["ic"] is None else round(j["ic"], 4)} for j in judged]}
        if selected:
            score, _ = scored(prepared, [s_["name"] for s_ in selected], [s_["weight"] for s_ in selected], prepared["model"])
            # The fold's dates plus the day before it (TopkDropout reads the previous day's signal).
            lo = calendar[max(0, int(np.searchsorted(calendar, fold_start)) - 1)]
            sd = score.index.get_level_values("datetime")
            pieces.append(score[(sd >= lo) & (sd <= fold_end)])
        current = {s_["name"] for s_ in selected}
        fold["turnover_of_set"] = None if previous is None else round(1 - len(current & previous) / max(1, len(current | previous)), 2)
        previous = current
        results.append(fold)
        progress(k + 1, len(folds) + 2)

    def window_metrics(rows, a, b):
        part = [r for r in rows if a <= r["date"] <= b]
        if not part:
            return None
        rets = pd.Series([r["return"] for r in part])
        eq = float((1 + rets).prod())
        bench = pd.Series([r["benchmark"] for r in part])
        vol = rets.std(ddof=1) if len(rets) > 1 else 0.0
        curve = (1 + rets).cumprod()
        # rows carry the benchmark's cumulative level; its return inside the window is level end over level
        # the day before the window (or the first day's level when the window opens the run).
        before = [r for r in rows if r["date"] < a]
        base = before[-1]["benchmark"] if before else bench.iloc[0]
        return {"total_return": eq - 1, "benchmark_return": float(bench.iloc[-1] / base - 1),
                "sharpe": float(rets.mean() / vol * np.sqrt(252)) if vol > 0 else None, "max_drawdown": float((curve / curve.cummax() - 1).min()), "days": len(part)}

    def track(score_series, fold_list, with_selection):
        if score_series is None or score_series.empty:
            return None
        metrics, rows = summarize_report(book_report(score_series, config))
        per_fold = []
        for f in fold_list:
            m = window_metrics(rows, f["start"], f["end"])
            per_fold.append({"start": f["start"], "end": f["end"], "return": m and m["total_return"], "benchmark": m and m["benchmark_return"],
                             "sharpe": m and m["sharpe"], "max_drawdown": m and m["max_drawdown"],
                             "selected": [s_["name"] for s_ in f.get("selected", [])] if with_selection else None})
        excess = [(pf["return"] or 0) - (pf["benchmark"] or 0) for pf in per_fold if pf["return"] is not None]
        fold_returns = [pf["return"] for pf in per_fold if pf["return"] is not None]
        return {**metrics, "folds": per_fold, "median_fold_return": float(np.median(fold_returns)) if fold_returns else None,
                "worst_fold_return": float(min(fold_returns)) if fold_returns else None,
                "median_fold_excess": float(np.median(excess)) if excess else None, "worst_fold_excess": float(min(excess)) if excess else None,
                "hit_rate": float(np.mean([x > 0 for x in excess])) if excess else None,
                "equity": [[r["date"], round(r["equity"], 6)] for r in rows], "benchmark_equity": [[r["date"], round(r["benchmark"], 6)] for r in rows]}

    stitched_score = pd.concat(pieces).sort_index() if pieces else None
    if stitched_score is not None:
        stitched_score = stitched_score[~stitched_score.index.duplicated(keep="last")]
    walk = track(stitched_score, results, True)
    progress(len(folds) + 1, len(folds) + 2)
    fixed_score, _ = scored(prepared, names, [given[n] for n in names], prepared["model"])
    # Same first day as the stitched score, so both books start their rebalance cadence on the same day.
    fd = fixed_score.index.get_level_values("datetime")
    fixed_score = fixed_score[fd >= calendar[max(0, int(np.searchsorted(calendar, folds[0][0])) - 1)]]
    fixed = track(fixed_score, results, False)
    progress(len(folds) + 2, len(folds) + 2)
    if walk is not None:
        walk["set_turnover"] = [f["turnover_of_set"] for f in results]
        walk["empty_folds"] = sum(1 for f in results if not f["selected"])
    return clean({"walkforward": {**wf, "folds": len(folds)}, "selected_by_fold": [{"start": f["start"], "end": f["end"], "train": f["train"], "selected": f["selected"], "judged": f["judged"]} for f in results],
                  "walk": walk, "fixed": fixed, "config": {k: v for k, v in config.items() if k != "factors"} | {"factors": [{k: v for k, v in f.items() if k != "path"} for f in config["factors"]]},
                  "notes": prepared["notes"],
                  "method": "Each fold re-selects factors on the training window before it (size-neutral 1-day Rank IC t, strongest first, signed by the IC); the fold's dates take that set's score; the stitched score is backtested once so the book carries over. Fixed = every candidate with its given weight, never re-selected."})


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
    config = prepared["config"]  # possibly with the end day clamped; see prepare()
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
        score, _ = scored(prepared, columns, [weights[c] for c in columns], model)
        report = book_report(score, {**config, "start": window[0], "end": window[1]})
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
        raise ValueError(singles_failure(singles))
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
                  "prefilter": (config.get("search") or {}).get("prefilter"),
                  "steps": steps, "recommended": recommended, "everything": everything, "config": config})


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    diagnosing = "--diagnose" in sys.argv[2:]
    searching = "--search" in sys.argv[2:]
    walking = "--walkforward" in sys.argv[2:]
    target = folder / ("diagnosis.json" if diagnosing else "result.json")
    try:
        config = validate_config(json.loads((folder / "config.json").read_text()))
        write_json(target, {"status": "running"})
        if diagnosing:
            output = diagnose(config, progress=lambda done, total: write_json(target, {"status": "running", "done": done, "total": total}))
        elif searching:
            output = search(config, progress=lambda done, total, steps: write_json(target, {"status": "running", "done": done, "total": total, "steps": clean(steps)}))
        elif walking:
            output = walkforward(config, progress=lambda done, total: write_json(target, {"status": "running", "done": done, "total": total}))
        else:
            output = run(config)
        write_json(target, {"status": "completed", **output})
        write_json(folder / "summary.json", summary_of({"status": "completed", **output}))
    except Exception as error:
        traceback.print_exc()
        write_json(target, {"status": "failed", "error": str(error)})
        write_json(folder / "summary.json", {"status": "failed", "error": str(error)})
        sys.exit(1)
