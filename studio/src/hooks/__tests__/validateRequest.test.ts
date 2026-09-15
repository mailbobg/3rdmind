import { describe, expect, it } from "vitest";
import { validateRequest } from "../validateRequest";
import type { BacktestRequest } from "../../api/studio";

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

describe("validateRequest with a trained model", () => {
  const lgbm = { method: "lgbm" as const, train: ["2023-01-01", "2023-12-31"] as [string, string], valid: ["2024-01-01", "2024-12-31"] as [string, string] };
  it("accepts ordered windows", () => expect(validateRequest({ ...base, model: lgbm })).toBeNull());
  it("rejects a validation window overlapping training", () =>
    expect(validateRequest({ ...base, model: { ...lgbm, valid: ["2023-06-01", "2024-12-31"] } })).toMatch("验证"));
  it("rejects a validation window reaching into the backtest", () =>
    expect(validateRequest({ ...base, model: { ...lgbm, valid: ["2024-01-01", "2025-03-01"] } })).toMatch("回测"));
});
