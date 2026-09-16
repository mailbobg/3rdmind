import { describe, expect, it } from "vitest";
import { pickByCorrelation, rankCandidates } from "../autoPick";
import type { LibraryFactor } from "../../api/studio";

const factor = (name: string, rankIc: number, icir: number | null, trace = "S/a"): LibraryFactor => ({
  trace, loop_id: 0, name, description: null, formulation: null, variables: null, hypothesis: null, decision: null, reason: null,
  metrics: {}, code: null, refreshed: null, coverage: null,
  analysis: icir === undefined ? null : { coverage: { start: "2023-01-01", end: "2025-12-31" }, days: 700, rows: 1, monthly: [],
    ic: { mean: rankIc, std: 0.1, ir: icir, positive_ratio: 0.5 }, rank_ic: { mean: rankIc, std: 0.1, ir: icir, positive_ratio: 0.5 } },
} as unknown as LibraryFactor);

describe("rankCandidates", () => {
  it("drops noise and unanalysed factors, keeps the stronger of duplicate names, orders by |ICIR|", () => {
    const all = [factor("weak", 0.001, 0.4), factor("flat", 0.02, 0.01), factor("neg", -0.02, -0.3), factor("pos", 0.03, 0.2),
                 factor("pos", 0.04, 0.5, "S/b"), { ...factor("none", 0.02, 0.2), analysis: null } as LibraryFactor];
    const { ranked, noise, unanalyzed } = rankCandidates(all);
    expect(noise.map((f) => f.name)).toEqual(["weak", "flat"]);
    expect(unanalyzed.map((f) => f.name)).toEqual(["none"]);
    expect(ranked.map((r) => [r.factor.name, r.factor.trace])).toEqual([["pos", "S/b"], ["neg", "S/a"]]);
  });
});

describe("pickByCorrelation", () => {
  it("skips near-duplicates of already kept factors and signs weights by Rank IC", () => {
    const { ranked } = rankCandidates([factor("a", 0.03, 0.5), factor("b", 0.02, 0.4), factor("c", -0.02, -0.3)]);
    const corr = { names: ["a", "b", "c"], days: 10, matrix: [[1, 0.8, 0.1], [0.8, 1, 0.2], [0.1, 0.2, 1]] };
    const { picked, duplicates } = pickByCorrelation(ranked, corr, 8);
    expect(picked.map((p) => [p.name, p.weight])).toEqual([["a", 1], ["c", -1]]);
    expect(duplicates).toEqual([{ name: "b", of: "a", rho: 0.8 }]);
  });
  it("stops at the maximum", () => {
    const { ranked } = rankCandidates([factor("a", 0.03, 0.5), factor("b", 0.02, 0.4)]);
    const corr = { names: ["a", "b"], days: 10, matrix: [[1, 0], [0, 1]] };
    expect(pickByCorrelation(ranked, corr, 1).picked.map((p) => p.name)).toEqual(["a"]);
  });
});
