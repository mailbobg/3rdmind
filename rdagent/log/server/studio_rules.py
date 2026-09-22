"""Rule strategies: hand-written signals beside the researched factors.

A rule is a factor.py under ``rules/`` written by hand from an event study rather than proposed by the
agent. It reads the same daily_pv.h5 the factors read and writes a result.h5, so downstream nothing changes:
it is recomputed on a universe's latest data by studio_refresh (``rule_dir`` is where the copy lives), joined
into a backtest like any signal, and can be a strategy member (``kind: "rule"``). Rules skip the gate and the
single-factor analysis: a screen that scores every kept name 1.0 has no IC to judge; its evidence is the
event study it came from and the backtest it goes into.
"""
import hashlib
from pathlib import Path

RULES_DIR = Path(__file__).with_name("rules")

RULES = {
    "attention_screen": {
        "label": "关注度回避名单",
        "description": "等权持有全池，剔除近 20 个交易日上过龙虎榜或涨停、户数公告分散超过 10%、以及未来 30 天有 2% 以上解禁的股票。"
                       "事件研究（全 A，2022-12 → 2026-09）：被剔除的名字之后一个月跑输等权全池约 20%/年，剔除后的书多约 5–6%/年，两半段同号。",
        "book": {"topk": 6000, "n_drop": 6000, "horizon": 20, "rebalance": 5, "neutral": "none", "book": "equal"},
        "markets": ["all", "csi1000", "csi500", "csi300"],
    },
    "post_unlock_20d": {
        "label": "大比例解禁后 20 日",
        "description": "持有过去 30 天里有 2% 以上股本解禁、且不在关注度名单上的股票，等权。"
                       "事件研究：解禁后 1–20 日跑赢等权全池约 10%/年，剔除关注度名单后约 15%/年（t 4），每天 70–90 只。",
        "book": {"topk": 6000, "n_drop": 6000, "horizon": 20, "rebalance": 5, "neutral": "none", "book": "equal"},
        "markets": ["all", "csi1000", "csi500"],
    },
    "insider_buy_20d": {
        "label": "高管本人二级市场增持后 20 日",
        "description": "持有公告后 20 个交易日内有董监高本人在二级市场（竞价交易 / 二级市场买卖）增持的股票，等权；"
                       "股权激励、大宗、协议转让和亲属、受控法人的增持不算。"
                       "事件研究（全 A，2023-01 → 2026-09，8,379 次公告）：公告后 1–20 日跑赢等权全池约 11%/年（t 4.3），两半段同号，每天约 80 只。",
        "book": {"topk": 6000, "n_drop": 6000, "horizon": 20, "rebalance": 5, "neutral": "none", "book": "equal"},
        "markets": ["all", "csi1000", "csi500"],
    },
    "insider_buy_20d_clean": {
        "label": "高管本人增持后 20 日 · 去关注度名单",
        "description": "高管本人二级市场增持后 20 日的股票，再剔除关注度名单（近 20 日龙虎榜或涨停、户数分散、未来 30 天大解禁），等权。两条规则的叠加。",
        "book": {"topk": 6000, "n_drop": 6000, "horizon": 20, "rebalance": 5, "neutral": "none", "book": "equal"},
        "markets": ["all", "csi1000", "csi500"],
    },
}


def rule_file(name: str) -> Path:
    if name not in RULES:
        raise ValueError(f"Unknown rule {name!r}")
    return RULES_DIR / f"{name}.py"


def rule_dir(refresh_root: Path, name: str, market: str) -> Path:
    """Where a rule's signal on ``market`` lives (beside the recomputed factors)."""
    return refresh_root / hashlib.sha1(f"rule#{name}@{market}".encode()).hexdigest()[:16]


def listing():
    return [{"name": name, **meta} for name, meta in RULES.items()]
