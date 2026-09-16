import { describe, expect, it } from "vitest";
import { mergeExperiments, shortTime } from "../experiments";
import type { ExperimentSummary } from "../../api/studio";

const summary = (over: Partial<ExperimentSummary>): ExperimentSummary =>
  ({ id: "S/x", scenario: "S", rounds: 1, accepted: 0, status: "completed", updated: "2026-09-01T00:00:00", hypothesis: null, messages: 1, ...over });

describe("mergeExperiments", () => {
  it("puts live runs first, then by last update, and unloaded traces last", () => {
    const rows = mergeExperiments(["S/old", "S/live", "S/new", "S/unknown"], [
      summary({ id: "S/old", updated: "2026-09-01T00:00:00" }),
      summary({ id: "S/new", updated: "2026-09-03T00:00:00" }),
      summary({ id: "S/live", status: "running", updated: "2026-08-01T00:00:00" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["S/live", "S/new", "S/old", "S/unknown"]);
    expect(rows[3]).toMatchObject({ status: "unloaded", rounds: null, scenario: "S" });
  });
  it("keeps every id the server lists even without a summary", () => {
    expect(mergeExperiments(["A/b"], []).map((r) => r.status)).toEqual(["unloaded"]);
  });
});

describe("shortTime", () => {
  it("keeps month, day and local time", () => {
    expect(shortTime("2026-09-02T12:00:00.123")).toBe("09-02 12:00"); // no zone: read as local time
    expect(shortTime(null)).toBe("—");
    expect(shortTime("t")).toBe("t");
  });
});
