"""Weekly forward-tracking report for the strategies in docs/research/forward/tracked.json.

For each tracked strategy it runs the strategy's own recipe (members, model, params) through the Studio from the
day tracking began to the latest trading day, and compares it with the equal-weight universe and the index. The
exit rules below are fixed in advance; the report only states whether one has been hit, it never changes a
strategy.

    python rd-agent/scripts/forward_report.py [--base http://127.0.0.1:19899]

Writes docs/research/forward/<date>.md and prints it.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
TRACKED = HERE / "docs" / "research" / "forward" / "tracked.json"
OUT = HERE / "docs" / "research" / "forward"

# Exit rules, fixed 2026-09-22 before any forward data was seen; never adjusted afterwards.
EXCESS_DRAWDOWN_LIMIT = -0.10  # the strategy's cumulative return minus the equal-weight universe's falls 10 points below its best
REVIEW_AFTER_DAYS = 365        # after a year of tracking, a cumulative excess below zero ends it


def call(base, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as reply:
        return json.load(reply)


def run(base, strategy, start, end):
    params = dict(strategy["params"])
    body = {**params, "factors": [{k: v for k, v in f.items() if k in ("name", "kind", "trace", "loop_id", "weight")} for f in strategy["factors"]],
            "model": strategy.get("model") or {"method": "rank"}, "start": start, "end": end}
    return call(base, "/studio/backtests", body)["id"]


def wait(base, ids, limit=3600):
    deadline, results = time.time() + limit, {}
    while len(results) < len(ids) and time.time() < deadline:
        for bid in ids:
            if bid in results:
                continue
            record = call(base, f"/studio/backtests/{bid}")
            if record.get("status") in ("completed", "failed"):
                results[bid] = record
        if len(results) < len(ids):
            time.sleep(15)
    return results


def excess_path(record):
    """Daily cumulative return of the strategy minus that of the equal-weight universe."""
    rows = record.get("rows") or []
    base = dict(record.get("baseline", {}).get("equity") or [])
    path = []
    for row in rows:
        if row["date"] in base:
            path.append((row["date"], row["equity"] - base[row["date"]]))
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:19899")
    args = parser.parse_args()
    try:
        latest = call(args.base, "/studio/data/sync")["local"]["calendar_end"]
    except (urllib.error.URLError, OSError) as error:
        print(f"Studio backend not reachable at {args.base}: {error}", file=sys.stderr)
        return 2
    tracked = json.loads(TRACKED.read_text())["strategies"]
    launched = {}
    for sid, info in tracked.items():
        strategy = call(args.base, f"/studio/strategies/{sid}")
        launched[run(args.base, strategy, info["from"], latest)] = (sid, info, strategy)
    results = wait(args.base, list(launched))

    lines = [f"# 前向跟踪 {date.today()}", "", f"数据到 {latest}。每条策略按自己的配方从跟踪开始日回测到最新交易日；退出规则事先写死（相对全池等权的累计超额从最高点回撤超过 10 个点，或跟踪满一年累计超额为负），只报告是否触发，不改策略。", "",
             "| 策略 | 跟踪起点 | 交易日 | 策略 | 全池等权 | 沪深300 | 超额 vs 等权 | 超额最大回撤 | 退出规则 |", "|---|---|---|---|---|---|---|---|---|"]
    flags = []
    for bid, (sid, info, strategy) in launched.items():
        record = results.get(bid)
        if not record or record.get("status") != "completed":
            lines.append(f"| {info['label']} | {info['from']} | — | 回测失败：{(record or {}).get('error') or '超时'} | | | | | |")
            continue
        m, b = record["metrics"], record.get("baseline") or {}
        path = excess_path(record)
        peak, worst = 0.0, 0.0
        for _, value in path:
            peak = max(peak, value)
            worst = min(worst, value - peak)
        excess = b.get("selection_return")
        days_tracked = (datetime.fromisoformat(latest) - datetime.fromisoformat(info["from"])).days
        hit = []
        if worst <= EXCESS_DRAWDOWN_LIMIT:
            hit.append("超额回撤超过 10 个点")
        if days_tracked >= REVIEW_AFTER_DAYS and excess is not None and excess < 0:
            hit.append("满一年累计超额为负")
        verdict = "；".join(hit) if hit else "未触发"
        if hit:
            flags.append(f"{info['label']}：{verdict}")
        fills = (strategy.get("params") or {}).get("fills", "ideal")
        lines.append(f"| {info['label']}{'（真实成交）' if fills == 'real' else '（理想成交）'} | {info['from']} | {m.get('days')} | {m['total_return']:+.2%} | {b.get('universe_return', float('nan')):+.2%} | "
                     f"{m.get('benchmark_return', float('nan')):+.2%} | {excess:+.2%} | {worst:+.2%} | {verdict} |")
    lines += ["", "触发退出规则的：" + ("；".join(flags) if flags else "无。"), ""]
    text = "\n".join(lines)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{date.today()}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
