"""验收: a deterministic acceptance gate for a research round's factors.

When the loop asks for its feedback to be confirmed, every factor the round produced is judged without an
LLM: analysed on the run's market (size-neutral Rank IC t statistic across horizons), compared with the
library by rank correlation, and, when the region has a second universe, recomputed there to see whether
the signal replicates in the same period. The verdict replaces the agent's accept/reject, and the reasons
go back to the agent as the direction for its next hypothesis.

The Qlib-facing work (analysis, correlation, recomputation) is injected as callables so the judgement
itself can be tested without Qlib.
"""
import math

# |t| of the size-neutral Rank IC needed at each horizon. t is scaled to n / horizon independent observations,
# so a 20-day effect has a fifth of the evidence a 1-day effect has in the same sample; the bar comes down with
# it rather than ruling long horizons out. Longer horizons also carry lower turnover, which is the point of them.
T_SIGNAL_BY_HORIZON = {1: 3.0, 5: 2.5, 10: 2.0, 20: 2.0}
T_WEAK_BY_HORIZON = {1: 2.0, 5: 1.75, 10: 1.5, 20: 1.5}  # below this the factor is indistinguishable from zero
T_REPLICATE_BY_HORIZON = {1: 2.0, 5: 1.75, 10: 1.5, 20: 1.5}  # same sign, at least this |t| on the second market
T_SIGNAL, T_WEAK, T_REPLICATE = T_SIGNAL_BY_HORIZON[1], T_WEAK_BY_HORIZON[1], T_REPLICATE_BY_HORIZON[1]
IC_SIGNAL = 0.02  # |Rank IC| at that horizon: a real but smaller signal cannot pay for its own turnover


def bar(table, horizon):
    """The bar for ``horizon`` (the 1-day bar for horizons the table does not list)."""
    return table.get(horizon, table[1])
DUPLICATE_CORR = 0.7  # rank correlation with a library factor from which it counts as the same signal
RELATED_CORR = 0.5  # from which the overlap is worth mentioning

# The universe a signal is re-checked on, in the same region and period: different names, same years.
SECOND_MARKET = {"csi300": "csi1000", "csi500": "csi1000", "csi1000": "csi300"}

LEVEL_LABELS = {"signal": "通过", "weak": "偏弱", "noise": "噪声", "duplicate": "重复", "unreplicated": "未复现", "error": "未能判断"}


def best_t(analysis, key="residual_rank_ic"):
    """(t, horizon) with the largest |t| across the analysis' horizons.

    Prefers the size-neutral residual Rank IC; falls back to the raw Rank IC of a horizon, then to the
    whole-run ICIR × √days of an analysis without horizons. (None, None) when nothing is usable.
    """
    t, horizon, _ = best_stats(analysis, key)
    return t, horizon


def best_stats(analysis, key="residual_rank_ic"):
    """(t, horizon, mean Rank IC) at the horizon where |t| clears its own bar by the widest margin; see best_t."""
    best, best_ratio = (None, None, None), None
    for horizon in analysis.get("horizons") or []:
        stats = horizon.get(key) or horizon.get("rank_ic") or {}
        t = stats.get("t")
        if t is None:
            continue
        ratio = abs(t) / bar(T_SIGNAL_BY_HORIZON, int(horizon["days"]))
        if best_ratio is None or ratio > best_ratio:
            best, best_ratio = (float(t), int(horizon["days"]), stats.get("mean")), ratio
    if best[0] is None:
        stats = analysis.get("rank_ic") or {}
        if stats.get("t") is not None:
            best = (float(stats["t"]), 1, stats.get("mean"))
        elif stats.get("ir") is not None and analysis.get("days"):
            best = (float(stats["ir"]) * math.sqrt(int(analysis["days"])), 1, stats.get("mean"))
    return best


def judge_factor(name, path, market, library, *, analyze, correlate, replicate):
    """One factor's verdict.

    ``analyze(path, market)`` returns a single-factor analysis; ``correlate([(name, path), ...])`` the
    correlation matrix ``{"names", "matrix"}``; ``replicate(name, path, market)`` the analysis of the same
    code recomputed on another market. ``library`` is ``[(name, path), ...]`` of the factors already kept.
    """
    out = {"name": name, "level": "noise", "t": None, "horizon": None, "ic": None, "nearest": None, "corr": None,
           "second_market": SECOND_MARKET.get(market), "t2": None, "replicated": None, "reasons": []}
    try:
        analysis = analyze(path, market)
    except Exception as error:  # noqa: BLE001 - the message is the diagnosis
        out.update(level="error", reasons=[f"分析失败：{error}"])
        return out
    t, horizon, ic = best_stats(analysis)
    out.update(t=t, horizon=horizon, ic=ic)
    # A copy of a library factor is not new information, however strong it is; check that first.
    others = [(n, p) for n, p in library if n != name]
    if others:
        try:
            corr = correlate([(name, path)] + others)
            names, matrix = corr["names"], corr["matrix"]
            i = names.index(name)
            nearest = max(((abs(matrix[i][j]), names[j], matrix[i][j]) for j in range(len(names)) if j != i), default=None)
            if nearest is not None:
                out["nearest"], out["corr"] = nearest[1], nearest[2]
                if nearest[0] >= DUPLICATE_CORR:
                    out["level"] = "duplicate"
                    out["reasons"].append(f"与库里的 {nearest[1]} 相关 {nearest[2]:+.2f}，是同一个信号的变体")
                    return out
                if nearest[0] >= RELATED_CORR:
                    out["reasons"].append(f"与 {nearest[1]} 相关 {nearest[2]:+.2f}，增量有限")
        except Exception as error:  # noqa: BLE001
            out["reasons"].append(f"相关性未算：{error}")
    if t is None:
        out["reasons"].append("没有可用的 IC")
        return out
    t_weak, t_signal = bar(T_WEAK_BY_HORIZON, horizon), bar(T_SIGNAL_BY_HORIZON, horizon)
    if abs(t) < t_weak:
        out["reasons"].append(f"市值中性 Rank IC 的 t 值 {t:.2f}（{horizon} 日，线 {t_weak:g}），与零区分不开")
        return out
    if abs(t) < t_signal:
        out["level"] = "weak"
        out["reasons"].append(f"t 值 {t:.2f}（{horizon} 日），在 {t_weak:g} 到 {t_signal:g} 之间，样本不足以确认")
        return out
    if ic is not None and abs(ic) < IC_SIGNAL:
        out["level"] = "weak"
        out["reasons"].append(f"t 值 {t:.2f}（{horizon} 日）但 Rank IC 只有 {ic:+.4f}，量级不到 {IC_SIGNAL}，付不起自己的换手")
        return out
    out["reasons"].append(f"t 值 {t:.2f}，Rank IC {ic:+.4f}（{horizon} 日）" if ic is not None else f"t 值 {t:.2f}（{horizon} 日）")
    second = out["second_market"]
    if second:
        try:
            other = replicate(name, path, second)
            t2, _ = best_t(other)
            out["t2"] = t2
            if t2 is not None and (t2 > 0) == (t > 0) and abs(t2) >= bar(T_REPLICATE_BY_HORIZON, horizon):
                out["replicated"] = True
                out["reasons"].append(f"在 {second} 上复现（t {t2:.2f}）")
            else:
                out["replicated"] = False
                out["level"] = "unreplicated"
                out["reasons"].append(f"在 {second} 上没有复现（t {t2:.2f}）" if t2 is not None else f"在 {second} 上算不出 IC")
                return out
        except Exception as error:  # noqa: BLE001 - a missing second universe must not block the verdict
            out["reasons"].append(f"{second} 上未能检验：{error}")
    out["level"] = "signal"
    return out


def family_representatives(library, correlate, threshold=DUPLICATE_CORR):
    """One name per family: walk ``library`` (strongest first) and keep a factor unless it correlates at
    ``threshold`` or more with one already kept. Falls back to the full list when the correlation fails."""
    if len(library) < 2:
        return [n for n, _ in library]
    try:
        corr = correlate(library)
    except Exception:  # noqa: BLE001
        return [n for n, _ in library]
    index = {n: i for i, n in enumerate(corr["names"])}
    kept = []
    for name, _ in library:
        i = index.get(name)
        if i is None:
            continue
        if any(abs(corr["matrix"][i][index[k]]) >= threshold for k in kept if k in index):
            continue
        kept.append(name)
    return kept


def gate_round(factors, market, library, *, analyze, correlate, replicate, families=None, existing=None):
    """Judge every factor of a round; the round is accepted when at least one passes.

    ``factors`` is ``[(name, path), ...]``. ``families`` are the library's family representatives and
    ``existing`` every library factor's name, both only for the hint. Returns the per-factor verdicts, the
    decision, a one-paragraph summary for the feedback's reason, and a hint for the next hypothesis.
    """
    verdicts = [judge_factor(name, path, market, library, analyze=analyze, correlate=correlate, replicate=replicate) for name, path in factors]
    decision = any(v["level"] == "signal" for v in verdicts)
    parts = [f"{v['name']}：{LEVEL_LABELS[v['level']]}（{'；'.join(v['reasons'])}）" for v in verdicts]
    summary = f"验收（确定性规则，不经 LLM）：{'通过' if decision else '不通过'}。" + "；".join(parts) + "。"
    hint = next_hint(verdicts, families if families is not None else [n for n, _ in library], existing)
    return {"factors": verdicts, "decision": decision, "summary": summary, "hint": hint, "market": market,
            "second_market": SECOND_MARKET.get(market), "families": families,
            "thresholds": {"t_signal": T_SIGNAL_BY_HORIZON, "t_weak": T_WEAK_BY_HORIZON, "t_replicate": T_REPLICATE_BY_HORIZON, "ic_signal": IC_SIGNAL, "duplicate_corr": DUPLICATE_CORR}}


def next_hint(verdicts, families, existing=None):
    """What the agent should stop proposing, from this round's verdicts, the library's families and its names."""
    lines = []
    duplicates = [v for v in verdicts if v["level"] == "duplicate"]
    if duplicates:
        lines.append("这些是库里已有信号的变体，不要再提类似的：" + "；".join(f"{v['name']} ≈ {v['nearest']}" for v in duplicates))
    noise = [v["name"] for v in verdicts if v["level"] in ("noise", "weak")]
    if noise:
        lines.append("这些的 IC 与零区分不开或太弱，不要在它们上面微调参数：" + "、".join(noise))
    failed = [v for v in verdicts if v["level"] == "unreplicated"]
    if failed:
        lines.append("这些在本市场有信号但在 " + failed[0]["second_market"] + " 上没有复现，可能是本市场特有或样本内偶然：" + "、".join(v["name"] for v in failed))
    broken = [v["name"] for v in verdicts if v["level"] == "error"]
    if broken:
        lines.append("这些没有产出可用的值（窗口长于可用数据、全为 NaN，或结果无法读取），不算被检验过；若要重提，窗口不得超过 120 日并设 min_periods：" + "、".join(broken))
    if families:
        lines.append("库里已有的独立信号族（各列一个代表；新假设与它们的相关要低于 0.5）：" + "、".join(families[:12]))
    if existing:
        lines.append(f"库里已有 {len(existing)} 个因子，不要再提同名或同定义的：" + "、".join(existing))
    lines.append("验收标准：市值中性 Rank IC 在 1/5/10/20 日中最有说服力的期限上 |t| 过线（1 日 ≥ 3，5 日 ≥ 2.5，10/20 日 ≥ 2）且 |Rank IC| ≥ 0.02，与库里任一因子的秩相关 < 0.7，并在同区域另一个股票池上同号复现（1 日 |t| ≥ 2，10/20 日 ≥ 1.5）。10–20 日期限的机制换手低、门槛也低，优先考虑。请提出机制不同的假设，而不是同一族的新参数。")
    return "\n".join(lines)
