"""Rule: hold the names just announced as net additions to CSI 300 / 500 / 1000, until index funds have bought them.

The June and December reviews are announced on a Friday after the close and take effect on the trading day after
the second Friday two weeks later; index funds and ETFs must hold the new names by then and trade at that Friday's
close. Pre-registered event study (all A-shares, 15 reviews 2019-06 → 2026-06, 1,556 net additions): from the
Monday's close after the announcement to the second Friday's close the name beats the equal-weight universe by
+1.8% per event (monthly t 3.0, both halves positive; 11 of 15 reviews positive), most of it on the Friday itself;
after the effective day the excess fades. Moves between the three indices and the names dropped carry no long side.

The rule scores a name 1 on the trading days within WINDOW calendar days of the first tradable day after the
announcement (0 = that Monday, 11 = the second Friday), NaN otherwise; the book is otherwise in cash.
"""
import numpy as np
import pandas as pd

WINDOW = 11  # calendar days: the Monday after the announcement through the second Friday, when index funds trade


def main():
    df = pd.read_hdf("daily_pv.h5").sort_index()
    if df.index.names != ["datetime", "instrument"]:
        df.index = df.index.set_names(["datetime", "instrument"])
    if "$index_add_days" not in df.columns:
        raise ValueError("daily_pv.h5 has no $index_add_days column: refresh the extra fields first")
    days = df["$index_add_days"]
    held = (days >= 0) & (days <= WINDOW) & df["$close"].notna()
    score = pd.Series(np.where(held, 1.0, np.nan), index=df.index, name="index_add_window")
    score.to_frame().to_hdf("result.h5", key="data")


if __name__ == "__main__":
    main()
