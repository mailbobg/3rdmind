"""Rule: hold the names whose company just announced a share buyback plan.

A buyback plan (回购预案) usually follows a fall: the name trails the equal-weight universe by about 15% a year
over the 20 trading days before the announcement. Afterwards it beats it by about 5% a year over the next 20
trading days (pre-registered event test, all A-shares 2019-01 → 2026-09, 10,545 first plans, t 2.5, both halves
positive; docs/research/2026-09-23-buyback-holder-preregistration.md).

The rule scores a name 2→1 (newest first) on the trading days that fall within WINDOW calendar days (about 20 trading days) of the
first tradable day after a plan announcement, NaN otherwise; an equal-weight book with the position count set to
the whole universe holds all of them.
"""
import numpy as np
import pandas as pd

WINDOW = 27  # calendar days after the first tradable day ≈ 20 trading days


def main():
    df = pd.read_hdf("daily_pv.h5").sort_index()
    if df.index.names != ["datetime", "instrument"]:
        df.index = df.index.set_names(["datetime", "instrument"])
    if "$buyback_plan_days" not in df.columns:
        raise ValueError("daily_pv.h5 has no $buyback_plan_days column: refresh the extra fields first")
    days = df["$buyback_plan_days"]
    held = (days >= 0) & (days <= WINDOW) & df["$close"].notna()
    # The score carries freshness (2 on the first tradable day, falling to 1 at the window's end): the book buys
    # in score order, so a cash-constrained account fills the newest announcements first, where the effect is strongest.
    score = pd.Series(np.where(held, 2.0 - days / WINDOW, np.nan), index=df.index, name="buyback_plan_20d")
    score.to_frame().to_hdf("result.h5", key="data")


if __name__ == "__main__":
    main()
