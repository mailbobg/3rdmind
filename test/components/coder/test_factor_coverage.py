"""The deterministic coverage check the factor coder runs before any LLM review."""
import pandas as pd
import pytest

from rdagent.components.coder.factor_coder.eva_utils import FactorCoverageEvaluator


class FakeWorkspace:
    def __init__(self, frame):
        self.frame = frame

    def execute(self):
        return "", self.frame


def frame(values, days=60, stocks=5):
    index = pd.MultiIndex.from_product([pd.bdate_range("2023-01-02", periods=days), [f"S{i}" for i in range(stocks)]],
                                       names=["datetime", "instrument"])
    return pd.DataFrame({"f": values(index)}, index=index)


@pytest.mark.offline
def test_all_nan_output_fails_with_the_cause() -> None:
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(frame(lambda i: [float("nan")] * len(i))), None)
    assert ok is False and "All 300 values are NaN over 60 dates" in text and "min_periods" in text


@pytest.mark.offline
def test_a_window_that_eats_the_data_fails_and_a_long_window_is_only_noted() -> None:
    # A 252-day window on 60 days of debug data: only the last few dates carry values.
    late = frame(lambda i: [float("nan") if d < pd.Timestamp("2023-03-20") else k for k, d in enumerate(i.get_level_values("datetime"))])
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(late), None)
    assert ok is False and "Fewer than 10 dates carry values" in text
    # A 45-day window leaves 15 of 60 dates: thin on the debug span, but the full data is longer, so it is noted, not failed.
    long_window = frame(lambda i: [float("nan") if d < pd.Timestamp("2023-03-06") else float(k % 7) for k, d in enumerate(i.get_level_values("datetime"))])
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(long_window), None)
    assert ok is None and "Only 25% of the dates carry values" in text
    # A 20-day warm-up leaves 40 of 60 dates: fine.
    warm = frame(lambda i: [float("nan") if d < pd.Timestamp("2023-01-30") else float(k % 7) for k, d in enumerate(i.get_level_values("datetime"))])
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(warm), None)
    assert ok is True and "values on 40 of 60 dates" in text and "20 warm-up dates" in text


@pytest.mark.offline
def test_constant_output_fails_and_sparse_or_subset_output_is_noted() -> None:
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(frame(lambda i: [1.0] * len(i))), None)
    assert ok is False and "constant" in text
    sparse = frame(lambda i: [float(k) if k % 7 == 0 else float("nan") for k in range(len(i))])  # every name carries a value now and then
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(sparse), None)
    assert ok is None and "NaN after warm-up" in text
    # Defined for one name of five: dense within that name, so no sparsity note.
    subset = frame(lambda i: [float(k) if inst == "S0" else float("nan") for k, inst in enumerate(i.get_level_values("instrument"))])
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(subset), None)
    assert ok is True and "1 of 5 names" in text
    text, ok = FactorCoverageEvaluator().evaluate(FakeWorkspace(frame(lambda i: [1.0] * len(i)).iloc[:, :0]), None)
    assert ok is False and "no columns" in text
