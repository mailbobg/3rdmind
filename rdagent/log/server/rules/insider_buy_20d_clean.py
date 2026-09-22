"""Rule: officers' own open-market buys, minus the attention list.

The insider rule (insider_buy_20d) holds a name for about 20 trading days after an officer or director bought
its shares in the open market with their own money. This variant also drops the names on the attention list
(dragon-tiger, limit-up, holder dispersion, big unlock ahead, kept identical to attention_screen.py), so the
two rule strategies stack: the insider event picks the names, the attention screen removes the crowded ones.
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


WINDOW = 27  # calendar days after the first tradable day ≈ 20 trading days


def main():
    df = pd.read_hdf("daily_pv.h5").sort_index()
    if df.index.names != ["datetime", "instrument"]:
        df.index = df.index.set_names(["datetime", "instrument"])
    if "$insider_buy_days" not in df.columns:
        raise ValueError("daily_pv.h5 has no $insider_buy_days column: refresh the extra fields first")
    flagged = attention(df).reindex(df.index).fillna(False).astype(bool)
    days = df["$insider_buy_days"]
    held = (days >= 0) & (days <= WINDOW) & df["$close"].notna() & ~flagged
    score = pd.Series(np.where(held, 1.0, np.nan), index=df.index, name="insider_buy_20d_clean")
    score.to_frame().to_hdf("result.h5", key="data")


if __name__ == "__main__":
    main()
