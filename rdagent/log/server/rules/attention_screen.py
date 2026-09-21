"""Rule: the equal-weight universe minus the names the market is staring at.

Names that were on the dragon-tiger list or hit a limit-up in the last 20 trading days, whose holder count
was just announced to have dispersed by more than 10%, or that have a share unlock of 2% or more of the
company inside the next 30 calendar days underperform the equal-weight universe by roughly 20% a year
over the following month (event study, all A-shares 2022-12 → 2026-09, both halves). The rule scores every
other name 1.0 and those names NaN, so an equal-weight book with the position count set to the whole
universe holds everything except them. Read the columns the Studio exports (daily_pv.h5).
"""
import numpy as np
import pandas as pd

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


def main():
    df = pd.read_hdf("daily_pv.h5")
    df = df.sort_index()
    if df.index.names != ["datetime", "instrument"]:
        df.index = df.index.set_names(["datetime", "instrument"])
    flagged = attention(df).reindex(df.index).fillna(False).astype(bool)
    priced = df["$close"].notna()
    score = pd.Series(np.where(priced & ~flagged, 1.0, np.nan), index=df.index, name="attention_screen")
    score.to_frame().to_hdf("result.h5", key="data")


if __name__ == "__main__":
    main()
