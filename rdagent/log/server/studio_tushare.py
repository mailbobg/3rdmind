"""Paid-tier Tushare fields for A-share factor code: order-size money flow, margin balances, chip
distribution, free-float turnover and market caps, dragon-tiger list, block trades, and point-in-time
fundamentals (financial indicators, earnings forecasts and express reports, holder counts, share unlocks).
Northbound holdings are left out on purpose: HKEX stopped publishing them on 2024-08-16.

Source: two reseller servers of the Tushare Pro API (keys in the environment, see ``servers``). The mirror
speaks the Tushare protocol (``pro_api`` with a redirected URL); the main server is a REST front with the same
interface names, ``limit``/``offset`` pagination and an ``X-API-Key`` header. Both throttle: the mirror
resets the TLS connection after ~20 rapid calls, so every call is paced and failures back off. The two are
used as parallel workers over one task queue; a call the mirror answers with exactly its 6000-row cap is
handed to the main server, which pages.

Cache: one CSV per table per key under ``<traces>/studio_data/extra/tushare/<table>/<key>.csv``:

    day tables      key = trade date          (moneyflow, margin, chips, basic, toplist, block)
    period tables   key = report period       (fina, forecast, express: the *_vip bulk interfaces)
    week tables     key = window start        (holders by announcement week, unlock by unlock-date week)

Files for finished keys are never re-fetched; keys still receiving rows (the current week, report periods
whose announcement season is open, unlock windows in the future) are refreshed on every run.

The fields join onto the OHLCV frames the Studio exports as ordinary ``$`` columns (see COLUMNS and
README_NOTE). Fundamentals are point-in-time: a report is visible from the trading day after its
announcement date, never earlier.

    python studio_tushare.py fetch <cache dir> <calendar file> <start> <end>

``calendar file`` lists trading days (YYYY-MM-DD, one per line). Prints one JSON status line.
"""
import json
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROW_CAP = 5000            # rows per page on the main server
MIRROR_CAP = 6000         # the mirror answers at most this many rows and cannot page
PERIOD_OPEN_DAYS = 150    # a report period keeps receiving announcements this long after it ends
UNLOCK_AHEAD_DAYS = 120   # unlock windows this far ahead are fetched so $unlock_30d is known in advance
MIRROR_PACE = 3.0         # seconds between calls, per server
MAIN_PACE = 1.5
BACKOFFS = (15, 45, 120)  # sleep after the 1st, 2nd, 3rd consecutive failure of a server
REST = 300                # a server that failed every attempt on a task rests this long before the next


@dataclass
class Table:
    api: str
    key: str                       # "day" | "period" | "week"
    params: list = field(default_factory=lambda: [{}])  # one call per entry, results concatenated
    date_params: tuple = ("start_date", "end_date")     # week tables: the range parameter names
    paged: bool = False                                  # answers exceed the mirror's cap: needs the paging server


TABLES = {
    "moneyflow": Table("moneyflow", "day"),
    "margin": Table("margin_detail", "day"),
    "chips": Table("cyq_perf", "day"),
    "basic": Table("daily_basic", "day"),
    "toplist": Table("top_list", "day"),
    "block": Table("block_trade", "day"),
    "fina": Table("fina_indicator_vip", "period"),
    "forecast": Table("forecast_vip", "period"),
    "express": Table("express_vip", "period"),
    "holders": Table("stk_holdernumber", "week"),
    "unlock": Table("share_float", "week", paged=True),  # strategic-placement rows per holder: tens of thousands a week
}

# Output columns by table, in the order they appear in the joined frame.
COLUMNS = {
    "moneyflow": ["$mf_net_xl", "$mf_net_lg", "$mf_net_md", "$mf_net_sm"],
    "margin": ["$rz_bal", "$rz_buy", "$rz_repay", "$rq_bal", "$rq_sell_vol"],
    "chips": ["$winner_rate", "$cost_5pct", "$cost_50pct", "$cost_95pct", "$chip_avg"],
    "basic": ["$turnover_f", "$volume_ratio", "$total_mv", "$circ_mv", "$free_share", "$dv_ttm"],
    "toplist": ["$lhb", "$lhb_net"],
    "block": ["$block_amt", "$block_px"],
    "fina": ["$roe", "$roe_dt", "$np_yoy", "$np_dt_yoy", "$rev_yoy", "$q_rev_yoy", "$gp_margin", "$debt_ratio", "$ocf_ps", "$bps", "$rep_days"],
    "forecast": ["$fc_pchg", "$fc_days"],
    "express": ["$ex_np_yoy", "$ex_days"],
    "holders": ["$holder_num", "$holder_chg"],
    "unlock": ["$unlock_30d", "$unlock_ratio_30d"],
}
EXTRA_COLUMNS = [column for table in TABLES for column in COLUMNS[table]]

README_NOTE = (
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
    " counts: $holder_num, $holder_chg fraction change vs the previous count. Share unlocks known in advance:"
    " $unlock_30d shares unlocking in the next 30 calendar days, $unlock_ratio_30d as a fraction of total"
    " shares. Event columns ($fc_*, $ex_*, $lhb*, $block_*) are sparse by nature.\n"
)


# ---- servers -------------------------------------------------------------------------------------------------

class Capped(Exception):
    """The mirror returned its row cap: the answer is truncated and the main server has to page it."""


class Server:
    """One paced client. ``query(api, params)`` returns a DataFrame or raises."""

    def __init__(self, name, pace):
        self.name, self.pace, self.failures, self.last_call = name, pace, 0, 0.0

    def call(self, api, params):
        wait = self.last_call + self.pace - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            frame = self.query(api, params)
        finally:
            self.last_call = time.time()
        self.failures = 0
        return frame

    def query(self, api, params):  # pragma: no cover - subclasses
        raise NotImplementedError


class Mirror(Server):
    def __init__(self, token, url):
        super().__init__("mirror", MIRROR_PACE)
        import tushare as ts

        self.pro = ts.pro_api(token)
        self.pro._DataApi__http_url = url

    def query(self, api, params):
        frame = self.pro.query(api, **params)
        if len(frame) >= MIRROR_CAP:
            raise Capped(f"{api} {params}: {len(frame)} rows")
        return frame


class Main(Server):
    def __init__(self, key, base):
        super().__init__("main", MAIN_PACE)
        import requests

        self.session = requests.Session()
        self.session.headers["X-API-Key"] = key
        self.base = base.rstrip("/")

    def query(self, api, params):
        import pandas as pd

        rows, fields, offset = [], None, 0
        while True:
            reply = self.session.get(f"{self.base}/{api.replace('_', '-')}", params={**params, "limit": ROW_CAP, "offset": offset}, timeout=60)
            reply.raise_for_status()
            body = reply.json()
            if body.get("code") != 0:
                raise RuntimeError(f"{api}: {body.get('msg') or body.get('code')}")
            data = body["data"]
            fields = fields or data["fields"]
            rows.extend(data["items"])
            if not data.get("has_more") or not data["items"]:
                break
            offset += len(data["items"])
        return pd.DataFrame(rows, columns=fields)


def servers(env=os.environ):
    """The configured servers, mirror first; empty when no key is set."""
    out = []
    if env.get("TUSHARE_MIRROR_TOKEN") and env.get("TUSHARE_MIRROR_URL"):
        out.append(("mirror", lambda: Mirror(env["TUSHARE_MIRROR_TOKEN"], env["TUSHARE_MIRROR_URL"])))
    if env.get("DATAHUB_API_KEY") and env.get("DATAHUB_BASE"):
        out.append(("main", lambda: Main(env["DATAHUB_API_KEY"], env["DATAHUB_BASE"])))
    return out


def configured(env=os.environ):
    return bool(servers(env))


# ---- keys and tasks -----------------------------------------------------------------------------------------

def compact(day):
    """'2025-01-02' or date → '20250102'."""
    return str(day).replace("-", "")[:8]


def periods(start, end):
    """Report periods (quarter ends) that a factor window from ``start`` to ``end`` can see: those ending after
    ``start`` minus a year (so the first days have a filled value) and before ``end``."""
    out = []
    for year in range(date.fromisoformat(start).year - 2, date.fromisoformat(end).year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            period = date(year, month, day)
            if date.fromisoformat(start) - timedelta(days=400) <= period <= date.fromisoformat(end):
                out.append(period)
    return out


def weeks(start, end):
    """Monday-anchored 7-day windows covering ``start``..``end`` (inclusive), as (window start, window end)."""
    first = date.fromisoformat(start)
    first -= timedelta(days=first.weekday())
    last = date.fromisoformat(end)
    out = []
    while first <= last:
        out.append((first, first + timedelta(days=6)))
        first += timedelta(days=7)
    return out


def open_period(period, end):
    return (date.fromisoformat(end) - period).days < PERIOD_OPEN_DAYS


def plan(cache: Path, calendar, start: str, end: str):
    """The (table, key, params) fetches this run needs, in priority order: missing or still-open keys."""
    tasks = []
    days = [d for d in calendar if start <= d <= end]
    for name, table in TABLES.items():
        folder = cache / name
        if table.key == "day":
            for day in days:
                if not (folder / f"{compact(day)}.csv").is_file():
                    tasks.append((name, compact(day), {"trade_date": compact(day)}))
        elif table.key == "period":
            for period in periods(start, end):
                key = compact(period)
                if open_period(period, end) or not (folder / f"{key}.csv").is_file():
                    tasks.append((name, key, {"period": key}))
        else:
            horizon = end if name != "unlock" else str(date.fromisoformat(end) + timedelta(days=UNLOCK_AHEAD_DAYS))
            for first, last in weeks(start, horizon):
                key = compact(first)
                still_open = last >= date.fromisoformat(end) - timedelta(days=7)
                if still_open or not (folder / f"{key}.csv").is_file():
                    tasks.append((name, key, {table.date_params[0]: compact(first), table.date_params[1]: compact(last)}))
    return tasks


def fetch(cache: Path, calendar, start: str, end: str, log=lambda *_: None, env=os.environ) -> dict:
    """Run every planned fetch across the configured servers in parallel; write one CSV per key."""
    import pandas as pd

    available = servers(env)
    if not available:
        raise RuntimeError("no Tushare server configured (TUSHARE_MIRROR_TOKEN/URL or DATAHUB_API_KEY/BASE)")
    tasks = plan(cache, calendar, start, end)
    log(f"{len(tasks)} fetches over {len(available)} server(s)")
    shared = queue.Queue()
    own = {name: queue.Queue() for name, _ in available}  # tasks only this server may take (paged answers)
    for task in tasks:
        target = own["main"] if TABLES[task[0]].paged and "main" in own else shared
        target.put((*task, False))  # the flag: already handed over once after failing
    done, failed, lock = [0], [], threading.Lock()
    total = len(tasks)

    def hand_over(server, name, key, params, error, retried):
        """A failed task goes to the other server once; a capped one only to a server that pages."""
        with lock:
            if isinstance(error, Capped):
                if "main" in own and server.name != "main":
                    own["main"].put((name, key, params, True))
                else:
                    failed.append(f"{name}/{key}: truncated at {MIRROR_CAP} rows and no paging server")
            else:
                others = [other for other in own if other != server.name]
                if retried or not others:
                    failed.append(f"{name}/{key}: {str(error)[:80]}")
                else:
                    own[others[0]].put((name, key, params, True))

    def next_task(server):
        """This server's own queue first, then the shared one; waits while another server may still hand a
        task over (a fetch in flight), returns None once everything is settled."""
        while True:
            for source in (own[server.name], shared):
                try:
                    return source.get_nowait()
                except queue.Empty:
                    continue
            with lock:
                if done[0] + len(failed) >= total:
                    return None
            time.sleep(1)

    def worker(make):
        server = make()
        while True:
            task = next_task(server)
            if task is None:
                return
            name, key, params, retried = task
            table = TABLES[name]
            frames, error = [], None
            for extra in table.params:
                for attempt in range(len(BACKOFFS) + 1):
                    try:
                        frames.append(server.call(table.api, {**params, **extra}))
                        error = None
                        break
                    except Capped as exc:
                        error = exc
                        break
                    except Exception as exc:  # noqa: BLE001 - backed off, then handed to the other server
                        error = exc
                        server.failures += 1
                        if attempt < len(BACKOFFS):
                            time.sleep(BACKOFFS[attempt])
                if error is not None:
                    break
            if error is not None:
                hand_over(server, name, key, params, error, retried)
                if server.failures >= len(BACKOFFS) + 1:
                    time.sleep(REST)  # this server is being throttled hard
                    server.failures = 0
                continue
            frame = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
            folder = cache / name
            folder.mkdir(parents=True, exist_ok=True)
            frame.to_csv(folder / f"{key}.csv", index=False)
            with lock:
                done[0] += 1
                if done[0] % 25 == 0:
                    log(f"{done[0]}/{total} fetches")

    threads = [threading.Thread(target=worker, args=(make,), daemon=True) for _, make in available]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {"planned": total, "done": done[0], "failed": failed[:20], "failed_count": len(failed)}


# ---- loading and joining ------------------------------------------------------------------------------------

def qlib_code(ts_code):
    """000001.SZ → SZ000001; Beijing codes and non-A codes → None."""
    if not isinstance(ts_code, str) or "." not in ts_code:
        return None
    number, exchange = ts_code.split(".", 1)
    return f"{exchange}{number}" if exchange in ("SH", "SZ") else None


def read_table(cache: Path, name, keys=None):
    """All cached rows of a table (optionally only ``keys``), with Qlib instrument codes; None when empty."""
    import pandas as pd

    folder = cache / name
    if not folder.is_dir():
        return None
    paths = sorted(folder.glob("*.csv"))
    if keys is not None:
        wanted = set(keys)
        paths = [p for p in paths if p.stem in wanted]
    frames = []
    for path in paths:
        try:
            frame = pd.read_csv(path, dtype={"ts_code": str, "trade_date": str, "ann_date": str, "end_date": str, "float_date": str, "first_ann_date": str})
        except pd.errors.EmptyDataError:
            continue
        if len(frame):
            frames.append(frame)
    if not frames:
        return None
    raw = pd.concat(frames, ignore_index=True).assign(instrument=lambda f: f["ts_code"].map(qlib_code))
    return raw[raw["instrument"].notna()].copy()


def _daily(raw, date_column="trade_date"):
    import pandas as pd

    raw = raw.copy()
    raw["datetime"] = pd.to_datetime(raw[date_column], format="%Y%m%d")
    return raw


def daily_frames(cache, days):
    """The day tables as (datetime, instrument) frames with their output columns."""
    import numpy as np
    import pandas as pd

    keys = [compact(d) for d in days]
    out = {}
    raw = read_table(cache, "moneyflow", keys)
    if raw is not None:
        raw = _daily(raw)
        out["moneyflow"] = pd.DataFrame({
            "$mf_net_xl": (raw["buy_elg_amount"] - raw["sell_elg_amount"]) * 1e4,
            "$mf_net_lg": (raw["buy_lg_amount"] - raw["sell_lg_amount"]) * 1e4,
            "$mf_net_md": (raw["buy_md_amount"] - raw["sell_md_amount"]) * 1e4,
            "$mf_net_sm": (raw["buy_sm_amount"] - raw["sell_sm_amount"]) * 1e4,
        }).set_index([raw["datetime"], raw["instrument"]])
    raw = read_table(cache, "margin", keys)
    if raw is not None:
        raw = _daily(raw)
        out["margin"] = pd.DataFrame({"$rz_bal": raw["rzye"], "$rz_buy": raw["rzmre"], "$rz_repay": raw["rzche"], "$rq_bal": raw["rqye"], "$rq_sell_vol": raw["rqmcl"]}).set_index([raw["datetime"], raw["instrument"]])
    raw = read_table(cache, "chips", keys)
    if raw is not None:
        raw = _daily(raw)
        out["chips"] = pd.DataFrame({"$winner_rate": raw["winner_rate"] / 100.0, "$cost_5pct": raw["cost_5pct"], "$cost_50pct": raw["cost_50pct"], "$cost_95pct": raw["cost_95pct"], "$chip_avg": raw["weight_avg"]}).set_index([raw["datetime"], raw["instrument"]])
    raw = read_table(cache, "basic", keys)
    if raw is not None:
        raw = _daily(raw)
        out["basic"] = pd.DataFrame({"$turnover_f": raw["turnover_rate_f"] / 100.0, "$volume_ratio": raw["volume_ratio"], "$total_mv": raw["total_mv"] * 1e4, "$circ_mv": raw["circ_mv"] * 1e4, "$free_share": raw["free_share"] * 1e4, "$dv_ttm": raw["dv_ttm"] / 100.0}).set_index([raw["datetime"], raw["instrument"]])
    raw = read_table(cache, "toplist", keys)
    if raw is not None:
        raw = _daily(raw)
        grouped = raw.groupby(["datetime", "instrument"])["net_amount"].sum()  # a name can appear under several reasons
        out["toplist"] = pd.DataFrame({"$lhb": np.ones(len(grouped)), "$lhb_net": grouped.values}, index=grouped.index)
    raw = read_table(cache, "block", keys)
    if raw is not None:
        raw = _daily(raw)
        raw["value"] = raw["amount"] * 1e4
        grouped = raw.groupby(["datetime", "instrument"]).agg(value=("value", "sum"), vol=("vol", "sum"))
        out["block"] = pd.DataFrame({"$block_amt": grouped["value"], "$block_px": grouped["value"] / (grouped["vol"] * 1e4)}, index=grouped.index)
    for name, frame in out.items():
        frame.index = frame.index.set_names(["datetime", "instrument"])
        out[name] = frame[~frame.index.duplicated(keep="last")]
    return out


def as_of(events, grid, columns):
    """Point-in-time forward fill: for every (datetime, instrument) in ``grid`` the latest event row whose
    ``available`` date is ≤ datetime. ``events`` has columns available, instrument, plus ``columns``."""
    import pandas as pd

    events = events.dropna(subset=["available"]).sort_values("available")
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


def event_frames(cache, grid, calendar):
    """The period and week tables, forward-filled point-in-time onto ``grid`` (a (datetime, instrument) index)."""
    import pandas as pd

    out = {}
    dates = grid.get_level_values("datetime")

    def days_since(frame, column):
        today = pd.Series(frame.index.get_level_values("datetime"), index=frame.index)
        return (today - frame[column]).dt.days.astype("float64")

    raw = read_table(cache, "fina")
    if raw is not None:
        raw = raw.copy()
        raw["available"] = next_trading_day(raw["ann_date"], calendar).values
        raw["report"] = pd.to_datetime(raw["ann_date"], format="%Y%m%d", errors="coerce")
        pct = lambda column: raw[column] / 100.0  # noqa: E731
        events = pd.DataFrame({"available": raw["available"], "instrument": raw["instrument"], "report": raw["report"],
                               "$roe": pct("roe"), "$roe_dt": pct("roe_dt"), "$np_yoy": pct("netprofit_yoy"), "$np_dt_yoy": pct("dt_netprofit_yoy"),
                               "$rev_yoy": pct("or_yoy"), "$q_rev_yoy": pct("q_sales_yoy"), "$gp_margin": pct("grossprofit_margin"),
                               "$debt_ratio": pct("debt_to_assets"), "$ocf_ps": raw["ocfps"], "$bps": raw["bps"]})
        filled = as_of(events, grid, [c for c in events.columns if c.startswith("$")] + ["report"])
        filled["$rep_days"] = days_since(filled, "report")
        out["fina"] = filled[COLUMNS["fina"]]
    raw = read_table(cache, "forecast")
    if raw is not None:
        raw = raw.copy()
        raw["available"] = next_trading_day(raw["ann_date"], calendar).values
        raw["report"] = pd.to_datetime(raw["ann_date"], format="%Y%m%d", errors="coerce")
        events = pd.DataFrame({"available": raw["available"], "instrument": raw["instrument"], "report": raw["report"],
                               "$fc_pchg": (raw["p_change_min"].astype(float) + raw["p_change_max"].astype(float)) / 200.0})
        filled = as_of(events, grid, ["$fc_pchg", "report"])
        filled["$fc_days"] = days_since(filled, "report")
        out["forecast"] = filled[COLUMNS["forecast"]]
    raw = read_table(cache, "express")
    if raw is not None:
        raw = raw.copy()
        raw["available"] = next_trading_day(raw["ann_date"], calendar).values
        raw["report"] = pd.to_datetime(raw["ann_date"], format="%Y%m%d", errors="coerce")
        income, base = raw["n_income"].astype(float), raw["yoy_net_profit"].astype(float)  # yoy_net_profit is last year's profit, not a rate
        events = pd.DataFrame({"available": raw["available"], "instrument": raw["instrument"], "report": raw["report"],
                               "$ex_np_yoy": (income / base.where(base > 0) - 1.0)})
        filled = as_of(events, grid, ["$ex_np_yoy", "report"])
        filled["$ex_days"] = days_since(filled, "report")
        out["express"] = filled[COLUMNS["express"]]
    raw = read_table(cache, "holders")
    if raw is not None:
        raw = raw.copy()
        raw["available"] = next_trading_day(raw["ann_date"], calendar).values
        raw = raw.dropna(subset=["available", "holder_num"]).sort_values(["instrument", "end_date", "ann_date"]).drop_duplicates(["instrument", "end_date"], keep="last")
        raw["previous"] = raw.groupby("instrument")["holder_num"].shift(1)
        events = pd.DataFrame({"available": raw["available"], "instrument": raw["instrument"], "$holder_num": raw["holder_num"].astype(float),
                               "$holder_chg": raw["holder_num"].astype(float) / raw["previous"].astype(float) - 1.0})
        out["holders"] = as_of(events, grid, COLUMNS["holders"])[COLUMNS["holders"]]
    raw = read_table(cache, "unlock")
    if raw is not None:
        raw = raw.copy()
        raw["known"] = pd.to_datetime(raw["ann_date"], format="%Y%m%d", errors="coerce")
        raw["unlock"] = pd.to_datetime(raw["float_date"], format="%Y%m%d", errors="coerce")
        raw = raw.dropna(subset=["known", "unlock"])
        # For each grid day t: shares whose unlock date is in (t, t+30d] and whose announcement is ≤ t.
        totals = pd.DataFrame(index=grid, columns=["$unlock_30d", "$unlock_ratio_30d"], dtype="float64")
        per_day = []
        for day in pd.DatetimeIndex(dates.unique()):
            window = raw[(raw["unlock"] > day) & (raw["unlock"] <= day + pd.Timedelta(days=30)) & (raw["known"] <= day)]
            if window.empty:
                continue
            summed = window.groupby("instrument").agg(shares=("float_share", "sum"), ratio=("float_ratio", "sum"))
            summed["datetime"] = day
            per_day.append(summed.reset_index())
        if per_day:
            summed = pd.concat(per_day, ignore_index=True).set_index(["datetime", "instrument"])
            totals["$unlock_30d"] = summed["shares"]
            totals["$unlock_ratio_30d"] = summed["ratio"] / 100.0
        totals[["$unlock_30d", "$unlock_ratio_30d"]] = totals[["$unlock_30d", "$unlock_ratio_30d"]].fillna(0.0)
        out["unlock"] = totals
    return out


def load(cache: Path, grid, calendar):
    """All EXTRA_COLUMNS for the (datetime, instrument) index ``grid``, NaN where the cache has no row (a
    table not fetched yet is all NaN, so the schema never changes between runs); empty when nothing is cached.
    ``calendar`` is the trading calendar as a DatetimeIndex."""
    import pandas as pd

    days = sorted({str(d.date()) for d in grid.get_level_values("datetime").unique()})
    parts = daily_frames(cache, days)
    parts.update(event_frames(cache, grid, calendar))
    if not parts:
        return pd.DataFrame(index=grid)
    out = pd.DataFrame(index=grid)
    for name in TABLES:
        if name in parts:
            out = out.join(parts[name], how="left")
    out = out.reindex(columns=EXTRA_COLUMNS)
    if "toplist" in parts:
        out["$lhb"] = out["$lhb"].fillna(0.0)
    return out.astype("float32")


def attach(frame, cache: Path):
    """Left-join the Tushare fields onto an OHLCV frame indexed (datetime, instrument). Returns (frame, attached)."""
    import pandas as pd

    if not cache.is_dir() or not any(cache.iterdir()):
        return frame, False
    calendar = pd.DatetimeIndex(sorted(frame.index.get_level_values("datetime").unique()))
    extra = load(cache, frame.index, calendar)
    if extra.empty or not len(extra.columns):
        return frame, False
    return frame.join(extra, how="left"), True


def status(cache: Path):
    """Per-table key counts and the last day table date, for the data sheet."""
    tables = {}
    last = ""
    for name, table in TABLES.items():
        folder = cache / name
        keys = sorted(p.stem for p in folder.glob("*.csv")) if folder.is_dir() else []
        tables[name] = len(keys)
        if table.key == "day" and keys:
            last = max(last, keys[-1])
    return {"tables": tables, "last": f"{last[:4]}-{last[4:6]}-{last[6:]}" if last else None, "configured": configured()}


def main(argv):
    if len(argv) != 5 or argv[0] != "fetch":
        raise ValueError("usage: studio_tushare.py fetch <cache dir> <calendar file> <start> <end>")
    cache, calendar_file, start, end = Path(argv[1]), Path(argv[2]), argv[3], argv[4]
    calendar = [line.strip() for line in calendar_file.read_text().splitlines() if line.strip()]
    return fetch(cache, calendar, start, end, log=lambda msg: print(msg, file=sys.stderr, flush=True))


if __name__ == "__main__":
    os.environ.setdefault("NO_PROXY", "*")
    try:
        print(json.dumps({"status": "completed", **main(sys.argv[1:])}, ensure_ascii=False))
    except Exception as error:  # noqa: BLE001 - relayed by the server
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
