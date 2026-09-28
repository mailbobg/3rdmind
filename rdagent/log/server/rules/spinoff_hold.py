"""Rule: hold spun-off companies from their second month of trading to the end of their first year (US).

Index funds and mandate-bound institutions that receive a spin-off's shares must sell them; once that is done the
price is set by the holders who chose to stay. Pre-registered test (docs/research/2026-09-28-spinoff-preregistration.md,
141 spin-offs 2008–2025 from EDGAR Form 10-12B filings): from the 21st to the 252nd trading day after listing the
spin-off beats the Russell 2000 by +15.8% (median +15.6%, t 3.5, 67% positive, both halves positive); the first
month is flat, the second year adds little. Survivorship bias (only still-listed tickers) is not resolved.

The score is 1 on the trading days that fall between WINDOW_FROM and WINDOW_TO calendar days after the listing day
(``$spinoff_days``, 0 on the listing day), NaN otherwise; an equal-weight book holds every scored name and is in
cash when nothing is scored.
"""
import numpy as np
import pandas as pd

WINDOW_FROM, WINDOW_TO = 30, 365  # calendar days ≈ trading days 21 … 252


def main():
    df = pd.read_hdf("daily_pv.h5").sort_index()
    if df.index.names != ["datetime", "instrument"]:
        df.index = df.index.set_names(["datetime", "instrument"])
    if "$spinoff_days" not in df.columns:
        raise ValueError("daily_pv.h5 has no $spinoff_days column: rebuild the US data with the spin-off list")
    days = df["$spinoff_days"]
    held = (days >= WINDOW_FROM) & (days <= WINDOW_TO) & df["$close"].notna()
    score = pd.Series(np.where(held, 1.0, np.nan), index=df.index, name="spinoff_hold")
    score.to_frame().to_hdf("result.h5", key="data")


if __name__ == "__main__":
    main()
