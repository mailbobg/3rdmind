"""Rule: hold the names whose big unlock just happened.

After a share unlock of 2% or more of the company, the name beats the equal-weight universe by about 10% a
year over the next 20 trading days (event study, all A-shares 2022-12 → 2026-09, both halves), about 15% when
the attention list (dragon-tiger, limit-up, holder dispersion, further unlocks ahead) is removed. The rule
scores a name 1.0 on the trading days it has an unlock of 2%+ inside the past 30 calendar days and is not on
the attention list, NaN otherwise; an equal-weight book with the position count set to the whole universe
holds all of them.
"""
import numpy as np
import pandas as pd

# The attention list, kept identical to attention_screen.py (rule files run standalone).
LOOKBACK = 20
DISPERSION = 0.10
UNLOCK_AHEAD = 0.02


def attention(df: pd.DataFrame) -> pd.Series:
    """True on the days a name is on the attention list; expects (datetime, instrument) rows."""
    wide = lambda col: df[col].unstack("instrument").sort_index()  # noqa: E731
    close = wide("$close")
    board = pd.Series([c.startswith(("SZ30", "SH68")) for c in close.columns], index=close.columns)
    limit = close.pct_change(fill_method=None) >= np.where(board, 0.195, 0.095)[None, :]
    recent_limit = limit.astype(float).rolling(LOOKBACK, min_periods=1).max() >= 1
    lhb = wide("$lhb").fillna(0.0) if "$lhb" in df.columns else close * 0
    recent_lhb = lhb.rolling(LOOKBACK, min_periods=1).max() >= 1
    if "$holder_chg" in df.columns and "$holder_ann_days" in df.columns:
        dispersed = (wide("$holder_chg") > DISPERSION) & (wide("$holder_ann_days") <= LOOKBACK)
    else:
        dispersed = close * 0 > 1
    unlock_ahead = wide("$unlock_ratio_30d") >= UNLOCK_AHEAD if "$unlock_ratio_30d" in df.columns else close * 0 > 1
    flagged = recent_limit | recent_lhb | dispersed.fillna(False) | unlock_ahead.fillna(False)
    return flagged.stack()


UNLOCKED = 0.02


def main():
    df = pd.read_hdf("daily_pv.h5").sort_index()
    if df.index.names != ["datetime", "instrument"]:
        df.index = df.index.set_names(["datetime", "instrument"])
    if "$unlock_past_30d" not in df.columns:
        raise ValueError("daily_pv.h5 has no $unlock_past_30d column: fetch the Tushare fields first")
    flagged = attention(df).reindex(df.index).fillna(False).astype(bool)
    held = (df["$unlock_past_30d"] >= UNLOCKED) & df["$close"].notna() & ~flagged
    score = pd.Series(np.where(held, 1.0, np.nan), index=df.index, name="post_unlock_20d")
    score.to_frame().to_hdf("result.h5", key="data")


if __name__ == "__main__":
    main()
