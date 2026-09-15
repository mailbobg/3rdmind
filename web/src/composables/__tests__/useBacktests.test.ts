import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBacktests, validateRequest } from "../useBacktests";
import type { BacktestRequest } from "../../api/studio";

vi.mock("../../api/studio", () => ({
  backtests: vi.fn(),
  backtest: vi.fn(),
  runBacktest: vi.fn(),
}));

import * as studio from "../../api/studio";

const factor = { name: "A", weight: 1, trace: "t", loop_id: 0 };
const base: BacktestRequest = {
  factors: [factor],
  start: "2025-01-01", end: "2025-06-30", market: "csi300", benchmark: "SH000300",
  topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015,
};

describe("validateRequest", () => {
  it("accepts a valid request", () => expect(validateRequest(base)).toBeNull());
  it("rejects reversed dates", () => expect(validateRequest({ ...base, end: "2024-01-01" })).toMatch("日期"));
  it("rejects n_drop above topk", () => expect(validateRequest({ ...base, n_drop: 11 })).toMatch("n_drop"));
  it("rejects zero total weight", () =>
    expect(validateRequest({ ...base, factors: [{ ...factor, weight: 0 }] })).toMatch("权重"));
  it("rejects factors without a source round", () =>
    expect(validateRequest({ ...base, factors: [{ ...factor, trace: "" }] })).toMatch("轮次"));
  it("rejects an empty benchmark", () => expect(validateRequest({ ...base, benchmark: " " })).toMatch("基准"));
  it("rejects no factors", () => expect(validateRequest({ ...base, factors: [] })).toMatch("因子"));
  it("rejects out-of-range costs", () => expect(validateRequest({ ...base, open_cost: 0.5 })).toMatch("费率"));
});

describe("useBacktests lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(studio.backtests).mockReset();
    vi.mocked(studio.backtest).mockReset();
    vi.mocked(studio.runBacktest).mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls after a successful run until completion, then stops", async () => {
    vi.mocked(studio.runBacktest).mockResolvedValue({ id: "j1" });
    vi.mocked(studio.backtests).mockResolvedValue([]);
    vi.mocked(studio.backtest)
      .mockResolvedValueOnce({ id: "j1", status: "running", config: base })
      .mockResolvedValueOnce({ id: "j1", status: "completed", config: base });

    const bt = useBacktests();
    await bt.run(base);

    await vi.advanceTimersByTimeAsync(3000);
    await vi.advanceTimersByTimeAsync(3000);

    expect(bt.result.value?.status).toBe("completed");
    expect(studio.backtest).toHaveBeenCalledTimes(2);
    expect(studio.backtests).toHaveBeenCalledTimes(2); // once in run(), once after completion

    const callsBefore = vi.mocked(studio.backtest).mock.calls.length;
    await vi.advanceTimersByTimeAsync(3000);
    expect(vi.mocked(studio.backtest).mock.calls.length).toBe(callsBefore);

    bt.dispose();
  });

  it("does not schedule polling when run() fails", async () => {
    vi.mocked(studio.runBacktest).mockRejectedValue(new Error("boom"));

    const bt = useBacktests();
    await bt.run(base);

    expect(bt.error.value).toBe("boom");
    expect(studio.backtest).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);

    bt.dispose();
  });

  it("keeps only the latest select() result when responses resolve out of order", async () => {
    let resolveA: (v: any) => void;
    let resolveB: (v: any) => void;
    const pendingA = new Promise((r) => { resolveA = r; });
    const pendingB = new Promise((r) => { resolveB = r; });
    vi.mocked(studio.backtest).mockImplementation((id: string) => (id === "a" ? pendingA : pendingB) as any);

    const bt = useBacktests();
    const selectA = bt.select("a");
    const selectB = bt.select("b");

    resolveA!({ id: "a", status: "completed", config: base });
    resolveB!({ id: "b", status: "completed", config: base });
    await selectA;
    await selectB;

    expect(bt.result.value?.id).toBe("b");

    bt.dispose();
  });
});

describe("validateRequest with a trained model", () => {
  const lgbm = { method: "lgbm" as const, train: ["2023-01-01", "2023-12-31"] as [string, string], valid: ["2024-01-01", "2024-12-31"] as [string, string] };
  it("accepts ordered windows", () => expect(validateRequest({ ...base, model: lgbm })).toBeNull());
  it("rejects a validation window overlapping training", () =>
    expect(validateRequest({ ...base, model: { ...lgbm, valid: ["2023-06-01", "2024-12-31"] } })).toMatch("验证"));
  it("rejects a validation window reaching into the backtest", () =>
    expect(validateRequest({ ...base, model: { ...lgbm, valid: ["2024-01-01", "2025-03-01"] } })).toMatch("回测"));
});
