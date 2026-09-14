import { describe, expect, it } from "vitest";
import { validateRequest } from "../useBacktests";
import type { BacktestRequest } from "../../api/studio";

const base: BacktestRequest = {
  trace: "t", loop_id: 0, factors: [{ name: "A", weight: 1 }],
  start: "2025-01-01", end: "2025-06-30", market: "csi300",
  topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015,
};

describe("validateRequest", () => {
  it("accepts a valid request", () => expect(validateRequest(base)).toBeNull());
  it("rejects reversed dates", () => expect(validateRequest({ ...base, end: "2024-01-01" })).toMatch("日期"));
  it("rejects n_drop above topk", () => expect(validateRequest({ ...base, n_drop: 11 })).toMatch("n_drop"));
  it("rejects zero total weight", () =>
    expect(validateRequest({ ...base, factors: [{ name: "A", weight: 0 }] })).toMatch("权重"));
  it("rejects no factors", () => expect(validateRequest({ ...base, factors: [] })).toMatch("因子"));
  it("rejects out-of-range costs", () => expect(validateRequest({ ...base, open_cost: 0.5 })).toMatch("费率"));
});
