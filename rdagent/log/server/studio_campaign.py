"""Campaign memory across research runs.

Three things a research loop forgets between runs and markets, computed here from what the Studio already
stores (single-factor analyses, gate verdicts) and handed to the agent as text:

* **power**: what this universe and sample can certify at all. t = ICIR × √(days ÷ horizon), so the ICIR a
  horizon needs is fixed by the bar and the sample, and the |Rank IC| that ICIR means follows from the
  market's own daily IC dispersion. A horizon whose required |IC| is beyond anything OHLCV factors reach is
  named as such, before the agent spends rounds on it.
* **the tested-mechanism map**: every factor name judged so far, on every universe, with its verdict, so a
  run on one market knows what another market already showed.
* **campaign statistics** over a run's gate verdicts (pass, duplicate, noise, failure rates, re-proposals),
  and the prompt for the reflection memo written on them.

Everything here is pure: callers pass the records in and get lines of text or dicts back.
"""
import math
import re

from rdagent.log.server import studio_gate

HORIZONS = (1, 5, 10, 20)
# |Rank IC| the strongest single OHLCV factors reach on a liquid universe; a horizon that needs more than
# this cannot be certified with this data, whatever the hypothesis.
REACHABLE_IC = 0.04
# Daily Rank IC dispersion when a market has no analysed factor yet: about three times the pure-noise floor
# 1/√N, which is what the analysed A-share and NASDAQ universes show.
NOISE_MULTIPLE = 3.0
LEVEL_LABELS = {**studio_gate.LEVEL_LABELS, "untested": "未检验"}


def market_ic_std(library, market):
    """Median daily std of the size-neutral Rank IC per horizon over the analysed factors of ``market``."""
    by = {}
    for f in library:
        analysis = f.get("analysis")
        if f.get("market") != market or not analysis:
            continue
        for h in analysis.get("horizons") or []:
            std = (h.get("residual_rank_ic") or h.get("rank_ic") or {}).get("std")
            if std:
                by.setdefault(int(h["days"]), []).append(float(std))
    return {h: sorted(v)[len(v) // 2] for h, v in by.items()}


def power_table(days, ic_std, members=None):
    """Per horizon: the ICIR and |Rank IC| the signal bar needs on ``days`` of data, and whether that is reachable."""
    rows = []
    for h in HORIZONS:
        bar = studio_gate.bar(studio_gate.T_SIGNAL_BY_HORIZON, h)
        icir = bar * math.sqrt(h / days) if days else None
        std = ic_std.get(h) or (NOISE_MULTIPLE / math.sqrt(members) if members else None)
        ic = icir * std if icir is not None and std else None
        rows.append({"horizon": h, "t_bar": bar, "icir": icir, "std": std, "ic": ic,
                     "reachable": None if ic is None else ic <= REACHABLE_IC})
    return rows


def power_lines(market, days, members, rows):
    """The power table as two or three lines for a prompt."""
    if not days:
        return []
    parts = []
    for r in rows:
        if r["icir"] is None:
            continue
        piece = f"{r['horizon']} 日 ICIR ≥ {r['icir']:.2f}"
        if r["ic"] is not None:
            piece += f"（|Rank IC| 约 ≥ {r['ic']:.3f}）"
        parts.append(piece)
    head = f"本股票池 {market}（{members} 只、{days} 个交易日）过验收线需要：" if members else f"本股票池 {market}（{days} 个交易日）过验收线需要："
    lines = [head + "；".join(parts) + "。"]
    blocked = [str(r["horizon"]) for r in rows if r["reachable"] is False]
    reachable = [str(r["horizon"]) for r in rows if r["reachable"]]
    if blocked:
        lines.append(f"其中 {'/'.join(blocked)} 日期限要求的 |Rank IC| 超过 {REACHABLE_IC}，价量因子在这个截面和样本上达不到：不要在这些期限上提假设，样本不够不是因子不行。"
                     + (f"可确认的期限：{'/'.join(reachable)} 日。" if reachable else ""))
    return lines


def level_of(analysis):
    """A verdict level from a single-factor analysis alone (no duplicate or replication check):
    signal / weak / noise by the gate's horizon-aware bars, or None without usable statistics."""
    if not analysis:
        return None, None, None, None
    t, horizon, ic = studio_gate.best_stats(analysis)
    if t is None:
        return None, None, None, None
    weak, signal = studio_gate.bar(studio_gate.T_WEAK_BY_HORIZON, horizon), studio_gate.bar(studio_gate.T_SIGNAL_BY_HORIZON, horizon)
    if abs(t) < weak:
        level = "noise"
    elif abs(t) < signal or (ic is not None and abs(ic) < studio_gate.IC_SIGNAL):
        level = "weak"
    else:
        level = "signal"
    return level, t, horizon, ic


def mechanism_map(records):
    """``{name: {market: record}}`` from tested records ``{name, market, level, t, horizon, ic, ...}``: a gate
    verdict for a name on a market wins over an analysis-only level, and a later record over an earlier one."""
    out = {}
    for r in records:
        if not r.get("name") or not r.get("market") or not r.get("level"):
            continue
        slot = out.setdefault(r["name"], {})
        old = slot.get(r["market"])
        if old is None or (r.get("source") == "gate") >= (old.get("source") == "gate"):
            slot[r["market"]] = r
    return out


def _verdict_text(r):
    # A gate pass also cleared duplication and replication; an analysis alone only says the IC is there.
    label = "有信号" if r["level"] == "signal" and r.get("source") != "gate" else LEVEL_LABELS.get(r["level"], r["level"])
    if r.get("t") is not None:
        return f"{label} t {r['t']:.1f}" + (f"（{r['horizon']} 日）" if r.get("horizon") else "")
    return label


def map_lines(mapping, market, limit=80):
    """Two lines: what this market has judged (name: verdict), and what other markets judged on names this
    market has not tried. Strong verdicts come first; the lists are cut at ``limit`` names each."""
    order = {"signal": 0, "unreplicated": 1, "weak": 2, "duplicate": 3, "noise": 4, "error": 5}
    here, elsewhere = [], []
    for name, by_market in mapping.items():
        if market in by_market:
            here.append((order.get(by_market[market]["level"], 9), name, by_market[market]))
        else:
            others = sorted(by_market.items())
            elsewhere.append((min(order.get(r["level"], 9) for _, r in others), name, others))
    lines = []
    if here:
        here.sort(key=lambda x: (x[0], x[1]))
        lines.append(f"本市场（{market}）已检验 {len(here)} 个因子，判定如下，不要重提同名或同定义的：" +
                     "；".join(f"{name}：{_verdict_text(r)}" for _, name, r in here[:limit]) +
                     ("；…" if len(here) > limit else ""))
    if elsewhere:
        elsewhere.sort(key=lambda x: (x[0], x[1]))
        lines.append("其他市场检验过、本市场未试的机制（同一机制跨市场的结论通常一致，噪声的不要再试，通过的可以在本市场复测）：" +
                     "；".join(f"{name}：" + "，".join(f"{m} {_verdict_text(r)}" for m, r in others) for _, name, others in elsewhere[:limit]) +
                     ("；…" if len(elsewhere) > limit else ""))
    return lines


def campaign_stats(gates):
    """Counts over a run's gate verdicts (``gates`` are the studio.gate contents in loop order)."""
    levels = {}
    factors = 0
    rounds_passed = 0
    seen, reproposed = set(), []
    for gate in gates:
        if gate.get("decision"):
            rounds_passed += 1
        for v in gate.get("factors") or []:
            factors += 1
            levels[v["level"]] = levels.get(v["level"], 0) + 1
            if v["name"] in seen:
                reproposed.append(v["name"])
            seen.add(v["name"])
    n = len(gates)
    rate = lambda k: (levels.get(k, 0) / factors) if factors else 0.0  # noqa: E731
    return {"rounds": n, "rounds_passed": rounds_passed, "factors": factors, "levels": levels,
            "pass_rate": rate("signal"), "duplicate_rate": rate("duplicate"), "noise_rate": rate("noise") + rate("weak"),
            "error_rate": rate("error"), "reproposed": reproposed,
            "signals": [v["name"] for g in gates for v in g.get("factors") or [] if v["level"] == "signal"]}


def stats_lines(stats):
    if not stats["rounds"]:
        return []
    levels = "、".join(f"{LEVEL_LABELS.get(k, k)} {v}" for k, v in sorted(stats["levels"].items(), key=lambda kv: -kv[1]))
    line = (f"本次研究至今 {stats['rounds']} 轮、{stats['factors']} 个因子：{levels}；"
            f"通过率 {stats['pass_rate']:.0%}，重复率 {stats['duplicate_rate']:.0%}，噪声率 {stats['noise_rate']:.0%}，实现失败率 {stats['error_rate']:.0%}。")
    if stats["reproposed"]:
        line += "重提过的名字：" + "、".join(sorted(set(stats["reproposed"]))) + "。"
    return [line]


def reflection_prompt(stats, gates, context_lines, direction=""):
    """The user prompt for the reflection memo: verdicts so far, the campaign numbers and the memory lines.
    The memo may only steer the next hypotheses; it never cites backtest returns and never touches thresholds."""
    rounds = []
    for gate in gates:
        loop = gate.get("loop_id")
        rounds.append(f"第 {loop + 1 if isinstance(loop, int) else '?'} 轮：" + "；".join(
            f"{v['name']} {LEVEL_LABELS.get(v['level'], v['level'])}（{'；'.join(v.get('reasons') or [])}）" for v in gate.get("factors") or []))
    body = "\n".join([
        "你是量化因子研究战役的复盘人。下面是一条自动研究的逐轮验收判定（确定性规则：市值中性 Rank IC 的 t 值、与库内因子的相关、第二股票池复现）、战役统计和记忆。",
        "",
        "研究方向：" + (direction or "（未指定）"),
        "",
        "逐轮判定：", *rounds, "",
        "战役统计：", *stats_lines(stats), "",
        "记忆：", *context_lines, "",
        "写一份反思备忘录，三段，各不超过 150 字，用中文：",
        "1. 观察：哪些机制族被证明无效、哪些有产出、Agent 在重复什么错误。",
        "2. 反思：为什么会这样（数据、市场、期限、实现），不要泛泛而谈。",
        "3. 方向：下一轮假设应该转向哪些具体机制（说清机制、期限、为什么可能在这个市场成立），以及明确不要再碰的方向。",
        "约束：只能依据上面的判定和统计，不得引用回测收益；不要建议放宽验收标准；不要提出与库内因子同族的变体。",
    ])
    return body


_LABEL_LEVELS = {v: k for k, v in studio_gate.LEVEL_LABELS.items()}
_ITEM = re.compile(r"([^\s：（）；。]+)：(" + "|".join(map(re.escape, _LABEL_LEVELS)) + r")（")


def parse_gate_summary(text):
    """A gate verdict recovered from the summary the gate wrote into a round's feedback (runs before the
    verdicts were persisted): ``{"decision", "factors": [{name, level, t, horizon, ic, nearest, corr, t2, reasons}]}``
    or None when the text carries no verdict."""
    if not text or "【验收】" not in text:
        return None
    head = re.search(r"【验收】验收（确定性规则，不经 LLM）：(通过|不通过)。", text)
    if head is None:
        return None
    body = text[head.end():].split("\n", 1)[0]
    factors = []
    for m in _ITEM.finditer(body):
        depth, i = 1, m.end()
        while i < len(body) and depth:
            depth += body[i] == "（"
            depth -= body[i] == "）"
            i += 1
        reason = body[m.end():i - 1]
        t = re.search(r"t 值 (-?\d+(?:\.\d+)?)", reason)
        horizon = re.search(r"（(\d+) 日", reason)
        ic = re.search(r"Rank IC (?:只有 )?([+-]?\d+\.\d+)", reason)
        near = re.search(r"与(?:库里的)? (\S+) 相关 ([+-]?\d+\.\d+)", reason)
        t2 = re.search(r"复现（t (-?\d+(?:\.\d+)?)）", reason)
        factors.append({"name": m.group(1), "level": _LABEL_LEVELS[m.group(2)], "t": float(t.group(1)) if t else None,
                        "horizon": int(horizon.group(1)) if horizon else None, "ic": float(ic.group(1)) if ic else None,
                        "nearest": near.group(1) if near else None, "corr": float(near.group(2)) if near else None,
                        "t2": float(t2.group(1)) if t2 else None, "replicated": True if t2 else None,
                        "reasons": [part for part in re.split(r"；(?![^（]*）)", reason) if part]})
    if not factors:
        return None
    return {"decision": head.group(1) == "通过", "factors": factors, "recovered": True}


def gate_records(messages, market=None):
    """A run's gate verdicts in loop order: the persisted studio.gate events, and for rounds that have none, the
    verdict recovered from the feedback text. Each carries ``loop_id`` and ``market``."""
    by_loop = {}
    order = []
    for m in messages:
        loop = m.get("loop_id")
        try:
            loop = int(loop)
        except (TypeError, ValueError):
            continue
        if m.get("tag") == "studio.gate":
            if loop not in by_loop:
                order.append(loop)
            by_loop[loop] = {**m["content"], "loop_id": loop}
        elif m.get("tag") == "feedback.hypothesis_feedback" and loop not in by_loop:
            content = m.get("content") or {}
            parsed = parse_gate_summary(content.get("hypothesis_evaluation") or content.get("reason") or "")
            if parsed:
                order.append(loop)
                by_loop[loop] = {**parsed, "loop_id": loop, "market": market}
    return [by_loop[loop] for loop in sorted(order)]
