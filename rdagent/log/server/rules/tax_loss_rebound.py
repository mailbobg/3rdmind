"""Rule: hold the year's worst-performing decile through the tax-loss rebound window (US).

Taxable investors sell their losers in December to realise losses and buy back in January. Pre-registered test
(docs/research/2026-09-28-us-quick-batch-preregistration.md, US large/mid caps 2008–2025, 18 years): the worst
year-to-date decile, held from the last close before December 15 to the last close before January 16, beats the
equal-weight universe by +2.0% per year (t 2.6, 14 of 18 years positive; both halves positive), and earns +4.8%
net per event on its own (t 3.1). The effect has weakened since 2021.

Ranking day = the last trading day on or before December 14 (year-to-date return from the previous year's last
close). The score is 1 for the worst decile on the ranking day and every trading day up to two days before the
last trading day on or before January 15, NaN otherwise; with open execution the book buys at the next open and
sells at the close of the last trading day before January 16. Cash the rest of the year.
"""
import numpy as np
import pandas as pd


def main():
    df = pd.read_hdf("daily_pv.h5").sort_index()
    if df.index.names != ["datetime", "instrument"]:
        df.index = df.index.set_names(["datetime", "instrument"])
    close = df["$close"].unstack("instrument")
    days = close.index
    score = pd.DataFrame(np.nan, index=days, columns=close.columns)
    for year in sorted({d.year for d in days}):
        prior = days[days <= pd.Timestamp(f"{year - 1}-12-31")]
        rank_days = days[days <= pd.Timestamp(f"{year}-12-14")]
        exit_days = days[days <= pd.Timestamp(f"{year + 1}-01-15")]
        if len(prior) == 0 or len(rank_days) == 0 or rank_days[-1].year != year:
            continue
        p0, p1 = prior[-1], rank_days[-1]
        ytd = (close.loc[p1] / close.loc[p0] - 1).dropna()
        if len(ytd) < 20:
            continue
        worst = ytd.index[ytd.rank(pct=True) <= 0.1]
        start = days.get_loc(p1)
        exit_boundary = pd.Timestamp(f"{year + 1}-01-15")
        if days[-1] < exit_boundary:
            end = len(days)  # the data has not reached the exit yet (a daily recompute inside the window): keep holding
        else:
            end = days.get_loc(exit_days[-1]) - 1  # the signal ends two days before the exit close (trade day = signal day + 1)
        held_days = days[start:end]
        score.loc[held_days, worst] = 1.0
    out = score.stack(future_stack=True).rename("tax_loss_rebound")
    out.to_frame().to_hdf("result.h5", key="data")


if __name__ == "__main__":
    main()
