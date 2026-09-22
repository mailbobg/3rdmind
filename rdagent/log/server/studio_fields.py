"""Extra A-share fields for factor code, beyond OHLCV, read from the shared quantdb store.

quantdb (a separate project, ``pip install -e <quantdb repo>``) owns fetching and storage; its location is
``QUANTDB_HOME`` (default ``~/.quantdb``). This module only knows which of its tables the Studio uses and how
their rows become ``$`` columns on the (datetime, instrument) frames the Studio exports:

    cn.baostock   $turnover $pe_ttm $pb $ps_ttm $pcf_ttm $float_cap $amount $is_st
    cn.moneyflow  $mf_net_xl $mf_net_lg $mf_net_md $mf_net_sm            (net buy by order size, yuan)
    cn.margin     $rz_bal $rz_buy $rz_repay $rq_bal $rq_sell_vol
    cn.chips      $winner_rate $cost_5pct $cost_50pct $cost_95pct $chip_avg
    cn.basic      $turnover_f $volume_ratio $total_mv $circ_mv $free_share $dv_ttm
    cn.toplist    $lhb $lhb_net          cn.block  $block_amt $block_px
    cn.fina       $roe … $rep_days       cn.forecast $fc_pchg $fc_days     cn.express $ex_np_yoy $ex_days
    cn.holders    $holder_num $holder_chg $holder_ann_days
    cn.unlock     $unlock_30d $unlock_ratio_30d $unlock_past_30d
    cn.insider    $insider_buy_days   (days since an officer's own open-market buy was announced)

Report-dated tables are laid on point-in-time: visible from the trading day after the announcement, forward
filled. Refreshing runs as a subprocess so the Flask server never imports the fetch clients:

    python studio_fields.py refresh <baostock|tushare> <start> <end> [codes file]

(``tushare`` also brings the FTShare event tables along; quantdb picks each table's own source.)
"""
import json
import os
import sys
from pathlib import Path

BAOSTOCK_COLUMNS = ["$turnover", "$pe_ttm", "$pb", "$ps_ttm", "$pcf_ttm", "$float_cap", "$amount", "$is_st"]
TUSHARE_TABLES = ["moneyflow", "margin", "chips", "basic", "toplist", "block", "fina", "forecast", "express", "holders", "unlock"]
EVENT_TABLES = ["insider"]  # other event tables (FTShare), laid on point-in-time like the report tables
COLUMNS = {
    "baostock": BAOSTOCK_COLUMNS,
    "moneyflow": ["$mf_net_xl", "$mf_net_lg", "$mf_net_md", "$mf_net_sm"],
    "margin": ["$rz_bal", "$rz_buy", "$rz_repay", "$rq_bal", "$rq_sell_vol"],
    "chips": ["$winner_rate", "$cost_5pct", "$cost_50pct", "$cost_95pct", "$chip_avg"],
    "basic": ["$turnover_f", "$volume_ratio", "$total_mv", "$circ_mv", "$free_share", "$dv_ttm"],
    "toplist": ["$lhb", "$lhb_net"],
    "block": ["$block_amt", "$block_px"],
    "fina": ["$roe", "$roe_dt", "$np_yoy", "$np_dt_yoy", "$rev_yoy", "$q_rev_yoy", "$gp_margin", "$debt_ratio", "$ocf_ps", "$bps", "$rep_days"],
    "forecast": ["$fc_pchg", "$fc_days"],
    "express": ["$ex_np_yoy", "$ex_days"],
    "holders": ["$holder_num", "$holder_chg", "$holder_ann_days"],
    "unlock": ["$unlock_30d", "$unlock_ratio_30d", "$unlock_past_30d"],
    "insider": ["$insider_buy_days"],
}
TUSHARE_COLUMNS = [column for table in TUSHARE_TABLES for column in COLUMNS[table]]
EVENT_COLUMNS = [column for table in EVENT_TABLES for column in COLUMNS[table]]
EXTRA_COLUMNS = BAOSTOCK_COLUMNS + TUSHARE_COLUMNS + EVENT_COLUMNS
TABLES = ["cn.baostock"] + [f"cn.{name}" for name in TUSHARE_TABLES + EVENT_TABLES]
DAY_TABLES = {"cn.moneyflow", "cn.margin", "cn.chips", "cn.basic", "cn.toplist", "cn.block"}  # their end date is "data through"

BAOSTOCK_NOTE = (
    "\nExtra columns (from baostock, joined by date and instrument; NaN where the source has no row):"
    " $turnover = daily turnover rate as a fraction of float shares; $pe_ttm, $pb, $ps_ttm, $pcf_ttm = valuation"
    " ratios (price over trailing-12-month earnings / most-recent-quarter book / TTM sales / TTM operating cash"
    " flow, negative when the denominator is negative); $float_cap = float market cap in yuan; $amount = traded"
    " value in yuan; $is_st = 1 on days the name carried an ST flag. These open turnover-structure, valuation"
    " and size mechanisms that OHLCV alone cannot express; treat $pe_ttm and friends as slow-moving (they change"
    " with price daily and with earnings quarterly).\n"
)
TUSHARE_NOTE = (
    "\nTushare columns (joined by date and instrument; NaN where the source has no row, e.g. names outside the"
    " margin list). Money flow by order size, net buy in yuan: $mf_net_xl (extra"
    " large), $mf_net_lg, $mf_net_md, $mf_net_sm. Margin trading in yuan: $rz_bal financing balance, $rz_buy"
    " financing purchases, $rz_repay repayments, $rq_bal securities-lending balance, $rq_sell_vol shares sold"
    " short. Chip distribution: $winner_rate fraction of holders in profit, $cost_5pct / $cost_50pct / $cost_95pct"
    " cost percentiles (price), $chip_avg weighted average cost. $turnover_f free-float turnover fraction,"
    " $volume_ratio volume vs the 5-day average, $total_mv / $circ_mv total and float market cap in yuan,"
    " $free_share free-float shares, $dv_ttm trailing dividend yield fraction. Dragon-tiger list: $lhb = 1 on"
    " listed days, $lhb_net net buy of the listed seats in yuan. Block trades: $block_amt total value in yuan,"
    " $block_px volume-weighted block price. Fundamentals are POINT-IN-TIME (a report is visible from the"
    " trading day after its announcement; forward-filled until the next): $roe, $roe_dt (deducted) fractions,"
    " $np_yoy / $np_dt_yoy net profit growth, $rev_yoy revenue growth, $q_rev_yoy single-quarter revenue"
    " growth, $gp_margin gross margin, $debt_ratio debt to assets, $ocf_ps operating cash flow per share, $bps"
    " book per share, $rep_days days since the latest report. Earnings forecasts: $fc_pchg forecast profit"
    " change (fraction, midpoint), $fc_days days since it; express reports: $ex_np_yoy, $ex_days. Holder"
    " counts: $holder_num, $holder_chg fraction change vs the previous count, $holder_ann_days days since the"
    " latest count was announced. Share unlocks known in advance: $unlock_30d shares unlocking in the next 30"
    " calendar days, $unlock_ratio_30d as a fraction of total shares; $unlock_past_30d the fraction of total"
    " shares unlocked in the past 30 calendar days. Event columns ($fc_*, $ex_*, $lhb*, $block_*) are sparse"
    " by nature.\n"
)
INSIDER_NOTE = (
    "\n$insider_buy_days (Eastmoney 董监高持股变动 via FTShare): calendar days since the latest announcement that an"
    " officer or director bought shares of the company in the open market with their own money (增持, 本人, 竞价 /"
    " 二级市场买卖; not incentive grants, block or negotiated transfers), POINT-IN-TIME (counted from the trading day"
    " after the announcement; 0 on that day), NaN before the first such buy. Event study (all A-shares 2023-01 →"
    " 2026-09, 8,379 announcements): the name beats the equal-weight universe by about 11% a year over the next 20"
    " trading days (t 4.3, both halves positive); large buys and related-party buys do not, and sells carry no"
    " information.\n"
)


# ---- the store -----------------------------------------------------------------------------------------------

SETTINGS_PATH = None  # <traces>/studio_data/quantdb.json: {"home": "..."}; empty means quantdb's default (~/.quantdb)


def configure(settings_path: Path) -> None:
    """Remember where the setting lives and apply a saved store location to this process (children inherit it)."""
    global SETTINGS_PATH
    SETTINGS_PATH = Path(settings_path)
    home = saved_home()
    if home:
        os.environ["QUANTDB_HOME"] = home


def saved_home() -> str:
    if SETTINGS_PATH is None or not SETTINGS_PATH.is_file():
        return ""
    try:
        return str(json.loads(SETTINGS_PATH.read_text()).get("home") or "")
    except ValueError:
        return ""


def save_home(home: str) -> str:
    """Point the Studio at a quantdb store: empty restores quantdb's default. The folder is created if needed
    (quantdb does that on open), but its parent must exist, so a typo does not create a tree somewhere odd."""
    home = (home or "").strip()
    if home:
        path = Path(home).expanduser()
        if not path.parent.is_dir():
            raise ValueError(f"目录不存在：{path.parent}")
        home = str(path)
        os.environ["QUANTDB_HOME"] = home
    else:
        os.environ.pop("QUANTDB_HOME", None)
    if SETTINGS_PATH is not None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps({"home": home}, ensure_ascii=False))
    return home


def installed() -> bool:
    try:
        import quantdb  # noqa: F401
    except ImportError:
        return False
    return True


def store():
    """The quantdb store, or None when the package is not installed."""
    if not installed():
        return None
    import quantdb

    return quantdb.open()


def has(db, name) -> bool:
    return db is not None and db.table_path(name).is_file()


def status(exports=lambda column: {}) -> dict:
    """What the data sheet shows: where the store is, per-table coverage, whether the Tushare servers are
    configured, which universe exports already carry the columns."""
    db = store()
    out = {"installed": db is not None, "home": str(db.root) if db else None, "home_setting": saved_home(), "configured": False, "tables": {}, "last": None,
           "settings": {}, "columns": list(EXTRA_COLUMNS), "baostock_exports": exports(BAOSTOCK_COLUMNS[0]), "tushare_exports": exports(TUSHARE_COLUMNS[0])}
    if db is None:
        return out
    from quantdb.cli import SETTINGS
    from quantdb.sources.base import Config

    config = Config(db.root)
    out["settings"] = {key: bool(config.get(key)) for key in SETTINGS}  # which keys .env (or the environment) provides, never the values
    out["configured"] = bool((config.get("TUSHARE_MIRROR_TOKEN") and config.get("TUSHARE_MIRROR_URL")) or (config.get("DATAHUB_API_KEY") and config.get("DATAHUB_BASE")))
    last = ""
    for name in TABLES:
        if not has(db, name):
            continue
        meta = db.meta(name)
        out["tables"][name] = {"rows": meta.get("rows", 0), "symbols": meta.get("symbols", 0), "end": meta.get("end"), "keys": len(meta.get("done", [])), "updated": meta.get("updated")}
        if name in DAY_TABLES and meta.get("end"):
            last = max(last, meta["end"])
    out["last"] = last or None
    return out


# ---- joining -------------------------------------------------------------------------------------------------

def _read(db, name, start=None, end=None):
    """Rows of ``cn.<name>`` with the Studio's column names: ``instrument`` plus YYYYMMDD strings in the date
    columns (what the derivations below expect)."""
    import pandas as pd

    if not has(db, name):
        return None
    where = None
    if start is not None and end is not None:
        where = f"date >= '{pd.Timestamp(start).date()}' AND date <= '{pd.Timestamp(end).date()}'"
    raw = db.read(name, where=where)
    if raw.empty:
        return None
    raw = raw.rename(columns={"symbol": "instrument"})
    for column in ("trade_date", "ann_date", "end_date", "float_date"):
        if column in raw.columns:
            values = raw[column]
            if pd.api.types.is_numeric_dtype(values):
                values = values.round().astype("Int64").astype(str).replace("<NA>", None)
            raw[column] = values.astype("string").str.replace("-", "", regex=False).str[:8]
    return raw[raw["instrument"].str[:2].isin(["SH", "SZ"])].reset_index(drop=True)


def baostock_frame(db, start, end):
    import numpy as np
    import pandas as pd

    raw = _read(db, "cn.baostock", start, end)
    if raw is None:
        return None
    turn = raw["turn"] / 100.0
    out = pd.DataFrame({"datetime": raw["date"], "instrument": raw["instrument"], "$turnover": turn,
                        "$pe_ttm": raw["peTTM"], "$pb": raw["pbMRQ"], "$ps_ttm": raw["psTTM"], "$pcf_ttm": raw["pcfNcfTTM"],
                        "$float_cap": np.where(turn > 0, raw["close"] * raw["volume"] / turn.where(turn > 0), np.nan),
                        "$amount": raw["amount"], "$is_st": raw["isST"].fillna(0).astype(float)})
    return out.set_index(["datetime", "instrument"]).sort_index()


def daily_frames(db, start, end):
    """The day tables as (datetime, instrument) frames with their output columns."""
    import numpy as np
    import pandas as pd

    out = {}
    raw = _read(db, "cn.moneyflow", start, end)
    if raw is not None:
        out["moneyflow"] = pd.DataFrame({
            "$mf_net_xl": (raw["buy_elg_amount"] - raw["sell_elg_amount"]) * 1e4, "$mf_net_lg": (raw["buy_lg_amount"] - raw["sell_lg_amount"]) * 1e4,
            "$mf_net_md": (raw["buy_md_amount"] - raw["sell_md_amount"]) * 1e4, "$mf_net_sm": (raw["buy_sm_amount"] - raw["sell_sm_amount"]) * 1e4,
        }).set_index([raw["date"], raw["instrument"]])
    raw = _read(db, "cn.margin", start, end)
    if raw is not None:
        out["margin"] = pd.DataFrame({"$rz_bal": raw["rzye"], "$rz_buy": raw["rzmre"], "$rz_repay": raw["rzche"], "$rq_bal": raw["rqye"], "$rq_sell_vol": raw["rqmcl"]}).set_index([raw["date"], raw["instrument"]])
    raw = _read(db, "cn.chips", start, end)
    if raw is not None:
        out["chips"] = pd.DataFrame({"$winner_rate": raw["winner_rate"] / 100.0, "$cost_5pct": raw["cost_5pct"], "$cost_50pct": raw["cost_50pct"], "$cost_95pct": raw["cost_95pct"], "$chip_avg": raw["weight_avg"]}).set_index([raw["date"], raw["instrument"]])
    raw = _read(db, "cn.basic", start, end)
    if raw is not None:
        out["basic"] = pd.DataFrame({"$turnover_f": raw["turnover_rate_f"] / 100.0, "$volume_ratio": raw["volume_ratio"], "$total_mv": raw["total_mv"] * 1e4, "$circ_mv": raw["circ_mv"] * 1e4, "$free_share": raw["free_share"] * 1e4, "$dv_ttm": raw["dv_ttm"] / 100.0}).set_index([raw["date"], raw["instrument"]])
    raw = _read(db, "cn.toplist", start, end)
    if raw is not None:
        grouped = raw.groupby(["date", "instrument"])["net_amount"].sum()  # a name can appear under several reasons
        out["toplist"] = pd.DataFrame({"$lhb": np.ones(len(grouped)), "$lhb_net": grouped.values}, index=grouped.index)
    raw = _read(db, "cn.block", start, end)
    if raw is not None:
        raw["value"] = raw["amount"] * 1e4
        grouped = raw.groupby(["date", "instrument"]).agg(value=("value", "sum"), vol=("vol", "sum"))
        out["block"] = pd.DataFrame({"$block_amt": grouped["value"], "$block_px": grouped["value"] / (grouped["vol"] * 1e4)}, index=grouped.index)
    for name, frame in out.items():
        frame.index = frame.index.set_names(["datetime", "instrument"])
        out[name] = frame[~frame.index.duplicated(keep="last")]
    return out


def as_of(events, grid, columns):
    """Point-in-time forward fill: for every (datetime, instrument) in ``grid`` the latest event row whose
    ``available`` date is ≤ datetime; same-day ties keep the caller's order (last wins)."""
    import pandas as pd

    events = events.dropna(subset=["available"]).sort_values("available", kind="stable")
    events["available"] = events["available"].astype("datetime64[ns]")
    frame = grid.to_frame(index=False)
    frame["datetime"] = frame["datetime"].astype("datetime64[ns]")
    frame = frame.sort_values("datetime")
    merged = pd.merge_asof(frame, events[["available", "instrument", *columns]], left_on="datetime", right_on="available", by="instrument", direction="backward")
    return merged.set_index(["datetime", "instrument"]).sort_index()


def next_trading_day(values, calendar):
    """The first trading day strictly after each YYYYMMDD announcement date (a report published on day t is
    tradable from t+1). ``calendar`` is a sorted DatetimeIndex."""
    import numpy as np
    import pandas as pd

    stamps = pd.to_datetime(values, format="%Y%m%d", errors="coerce").astype("datetime64[ns]")
    calendar = pd.DatetimeIndex(calendar).astype("datetime64[ns]")
    positions = np.searchsorted(calendar.values, stamps.values, side="right")
    out = pd.Series(pd.NaT, index=range(len(stamps)), dtype="datetime64[ns]")
    valid = (positions < len(calendar)) & stamps.notna().values
    out[valid] = calendar.values[positions[valid]]
    return out


def latest_last(raw):
    """Order report rows so that, when several become available the same day (a restatement, or two periods
    announced together), the later period and the updated version come last and win the point-in-time fill."""
    by = [c for c in ("ann_date", "end_date", "update_flag") if c in raw.columns]
    return raw.sort_values(by, kind="stable").reset_index(drop=True)


def event_frames(db, grid, calendar):
    """The period and week tables, forward-filled point-in-time onto ``grid`` (a (datetime, instrument) index)."""
    import pandas as pd

    out = {}
    dates = grid.get_level_values("datetime")

    def days_since(frame, column):
        today = pd.Series(frame.index.get_level_values("datetime"), index=frame.index)
        return (today - frame[column]).dt.days.astype("float64")

    def report_events(name, build):
        raw = _read(db, f"cn.{name}")
        if raw is None:
            return
        raw = latest_last(raw)
        raw["available"] = next_trading_day(raw["ann_date"], calendar).values
        raw["report"] = pd.to_datetime(raw["ann_date"], format="%Y%m%d", errors="coerce")
        events = pd.DataFrame({"available": raw["available"], "instrument": raw["instrument"], "report": raw["report"], **build(raw)})
        filled = as_of(events, grid, [c for c in events.columns if c.startswith("$")] + ["report"])
        filled[COLUMNS[name][-1]] = days_since(filled, "report")
        out[name] = filled[COLUMNS[name]]

    pct = lambda raw, column: raw[column] / 100.0  # noqa: E731
    report_events("fina", lambda raw: {"$roe": pct(raw, "roe"), "$roe_dt": pct(raw, "roe_dt"), "$np_yoy": pct(raw, "netprofit_yoy"), "$np_dt_yoy": pct(raw, "dt_netprofit_yoy"),
                                       "$rev_yoy": pct(raw, "or_yoy"), "$q_rev_yoy": pct(raw, "q_sales_yoy"), "$gp_margin": pct(raw, "grossprofit_margin"),
                                       "$debt_ratio": pct(raw, "debt_to_assets"), "$ocf_ps": raw["ocfps"], "$bps": raw["bps"]})
    report_events("forecast", lambda raw: {"$fc_pchg": (raw["p_change_min"].astype(float) + raw["p_change_max"].astype(float)) / 200.0})
    # express: yoy_net_profit is last year's profit, not a rate
    report_events("express", lambda raw: {"$ex_np_yoy": raw["n_income"].astype(float) / raw["yoy_net_profit"].astype(float).where(raw["yoy_net_profit"].astype(float) > 0) - 1.0})
    raw = _read(db, "cn.holders")
    if raw is not None:
        raw["available"] = next_trading_day(raw["ann_date"], calendar).values
        raw = raw.dropna(subset=["available", "holder_num"]).sort_values(["instrument", "end_date", "ann_date"]).drop_duplicates(["instrument", "end_date"], keep="last")
        raw["previous"] = raw.groupby("instrument")["holder_num"].shift(1)
        events = pd.DataFrame({"available": raw["available"], "instrument": raw["instrument"], "report": raw["available"],
                               "$holder_num": raw["holder_num"].astype(float), "$holder_chg": raw["holder_num"].astype(float) / raw["previous"].astype(float) - 1.0})
        filled = as_of(events, grid, ["$holder_num", "$holder_chg", "report"])
        filled["$holder_ann_days"] = days_since(filled, "report")
        out["holders"] = filled[COLUMNS["holders"]]
    raw = _read(db, "cn.unlock")
    if raw is not None:
        raw["known"] = pd.to_datetime(raw["ann_date"], format="%Y%m%d", errors="coerce")
        raw["unlock"] = pd.to_datetime(raw["float_date"], format="%Y%m%d", errors="coerce")
        raw = raw.dropna(subset=["known", "unlock"])
        # For each grid day t: shares whose unlock date is in (t, t+30d] and whose announcement is ≤ t (ahead),
        # and the share of the company unlocked in (t-30d, t] (behind).
        totals = pd.DataFrame(index=grid, columns=COLUMNS["unlock"], dtype="float64")
        ahead, behind = [], []
        for day in pd.DatetimeIndex(dates.unique()):
            window = raw[(raw["unlock"] > day) & (raw["unlock"] <= day + pd.Timedelta(days=30)) & (raw["known"] <= day)]
            if not window.empty:
                summed = window.groupby("instrument").agg(shares=("float_share", "sum"), ratio=("float_ratio", "sum"))
                summed["datetime"] = day
                ahead.append(summed.reset_index())
            past = raw[(raw["unlock"] <= day) & (raw["unlock"] > day - pd.Timedelta(days=30))]
            if not past.empty:
                summed = past.groupby("instrument").agg(ratio=("float_ratio", "sum"))
                summed["datetime"] = day
                behind.append(summed.reset_index())
        if ahead:
            summed = pd.concat(ahead, ignore_index=True).set_index(["datetime", "instrument"])
            totals["$unlock_30d"] = summed["shares"]
            totals["$unlock_ratio_30d"] = summed["ratio"] / 100.0
        if behind:
            summed = pd.concat(behind, ignore_index=True).set_index(["datetime", "instrument"])
            totals["$unlock_past_30d"] = summed["ratio"] / 100.0
        totals[COLUMNS["unlock"]] = totals[COLUMNS["unlock"]].fillna(0.0)
        out["unlock"] = totals
    raw = _read(db, "cn.insider")
    if raw is not None:
        own = (raw["change_direction"] == "增持") & (raw["relation"] == "本人") & raw["change_reason"].astype(str).str.contains("竞价|二级市场", regex=True)
        buys = raw[own].copy()
        announced = pd.to_datetime(buys["notice_date"], errors="coerce").fillna(pd.to_datetime(buys["date"], errors="coerce"))
        buys["available"] = next_trading_day(announced.dt.strftime("%Y%m%d"), calendar).values
        events = pd.DataFrame({"available": buys["available"], "instrument": buys["instrument"], "report": buys["available"]}).drop_duplicates()
        filled = as_of(events, grid, ["report"])
        filled["$insider_buy_days"] = days_since(filled, "report")
        out["insider"] = filled[COLUMNS["insider"]]
    return out


def attach(frame):
    """Left-join every extra column onto an OHLCV frame indexed (datetime, instrument). Columns whose table has
    no data yet are all NaN, so the schema never changes between runs. Returns (frame, note): ``note`` is the
    README text for the columns that were attached, empty when quantdb is missing or holds none of the tables."""
    import pandas as pd

    db = store()
    if db is None or not any(has(db, name) for name in TABLES):
        return frame, ""
    dates = frame.index.get_level_values("datetime")
    start, end = dates.min(), dates.max()
    calendar = pd.DatetimeIndex(sorted(dates.unique()))
    parts = {}
    bs = baostock_frame(db, start, end)
    if bs is not None:
        parts["baostock"] = bs
    parts.update(daily_frames(db, start, end))
    parts.update(event_frames(db, frame.index, calendar))
    extra = pd.DataFrame(index=frame.index)
    for name in COLUMNS:
        if name in parts:
            extra = extra.join(parts[name], how="left")
    extra = extra.reindex(columns=EXTRA_COLUMNS)
    if "toplist" in parts:
        extra["$lhb"] = extra["$lhb"].fillna(0.0)
    note = (BAOSTOCK_NOTE if "baostock" in parts else "") + (TUSHARE_NOTE if any(t in parts for t in TUSHARE_TABLES) else "") + (INSIDER_NOTE if "insider" in parts else "")
    return frame.join(extra.astype("float32"), how="left"), note


# ---- refreshing ---------------------------------------------------------------------------------------------

def refresh(kind, start, end, codes=None, log=lambda *_: None) -> dict:
    """Bring the Studio's tables up to ``end`` through quantdb's recorder: ``baostock`` for the given instrument
    codes, ``tushare`` for the eleven market-wide tables."""
    import quantdb
    from quantdb.recorders import Recorder

    def report(event):
        if event["event"] == "key" and (event["i"] % 10 == 0 or event["i"] == event["n"]):
            log(f"{event['table']} {event['i']}/{event['n']} {event['key']}")
        elif event["event"] == "fail":
            log(f"{event['table']} {event['key']} 失败: {event['error'][:80]}")

    recorder = Recorder(quantdb.open(), report=report)
    planned, done, failed = 0, 0, []
    tables = ["cn.baostock"] if kind == "baostock" else [f"cn.{name}" for name in TUSHARE_TABLES + EVENT_TABLES]
    for name in tables:
        summary = recorder.refresh(name, start=start, end=end, symbols=codes if kind == "baostock" else None)
        planned += summary["keys"]; done += summary["done"]
        failed.extend(f"{name}/{key}: {error[:80]}" for key, error in summary["failed"])
    return {"planned": planned, "done": done, "failed": failed[:20], "failed_count": len(failed)}


def main(argv):
    if len(argv) < 4 or argv[0] != "refresh" or argv[1] not in ("baostock", "tushare"):
        raise ValueError("usage: studio_fields.py refresh <baostock|tushare> <start> <end> [codes file]")
    codes = [line.strip() for line in Path(argv[4]).read_text().splitlines() if line.strip()] if len(argv) > 4 else None
    return refresh(argv[1], argv[2], argv[3], codes, log=lambda msg: print(msg, file=sys.stderr, flush=True))


if __name__ == "__main__":
    os.environ.setdefault("NO_PROXY", "*")
    try:
        print(json.dumps({"status": "completed", **main(sys.argv[1:])}, ensure_ascii=False))
    except Exception as error:  # noqa: BLE001 - relayed by the server
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
