import { describe, expect, it } from "vitest";
import { fmtDuration, medianRoundMs, progressLine, roundProgress } from "../progress";
import type { TraceEvent } from "../../api/studio";

const ev = (tag: string, timestamp: string, loop_id: number, evo_id?: number): TraceEvent => ({ tag, timestamp, loop_id, evo_id, content: {} });
const T = (m: number) => `2026-09-16T14:${String(m).padStart(2, "0")}:00`;

describe("roundProgress", () => {
  it("derives step states and durations from the events of a finished round", () => {
    const rounds = roundProgress([
      ev("research.hypothesis", T(0), 0), ev("research.tasks", T(1), 0),
      ev("evolving.feedbacks", T(3), 0, 0), ev("evolving.codes", T(3), 0, 0), ev("evolving.codes", T(5), 0, 1),
      ev("feedback.return_chart", T(6), 0), ev("feedback.metric", T(6), 0), ev("feedback.hypothesis_feedback", T(9), 0),
    ], false);
    expect(rounds).toHaveLength(1);
    const [r] = rounds;
    expect(r.finished).toBe(true);
    expect(r.steps.map((s) => s.state)).toEqual(["done", "done", "done", "done"]);
    expect(r.steps[1].iterations).toBe(2);
    expect(r.elapsed).toBe(9 * 60_000);
    expect(r.steps[2].startedAt).toBe(new Date(T(5)).getTime());
  });
  it("marks the first unfinished step of the last round as current while running", () => {
    const rounds = roundProgress([
      ev("research.hypothesis", T(0), 0), ev("feedback.hypothesis_feedback", T(8), 0),
      ev("research.hypothesis", T(10), 1), ev("research.tasks", T(11), 1), ev("evolving.codes", T(13), 1, 0),
    ], true, new Date(T(20)).getTime());
    expect(rounds[1].steps.map((s) => s.state)).toEqual(["done", "done", "current", "pending"]);
    expect(rounds[1].elapsed).toBe(10 * 60_000);
    expect(progressLine(rounds, new Date(T(20)).getTime())).toBe("第 2 轮 · Qlib 评估 · 已 7 分");
    // Not running: nothing is current even if unfinished.
    expect(roundProgress([ev("research.hypothesis", T(0), 0)], false)[0].steps[1].state).toBe("pending");
  });
  it("estimates from finished rounds and formats durations", () => {
    const rounds = roundProgress([
      ev("research.hypothesis", T(0), 0), ev("feedback.hypothesis_feedback", T(8), 0),
      ev("research.hypothesis", T(10), 1), ev("feedback.hypothesis_feedback", T(22), 1),
      ev("research.hypothesis", T(30), 2),
    ], true);
    expect(medianRoundMs(rounds)).toBe(10 * 60_000);
    expect(fmtDuration(45_000)).toBe("45 秒");
    expect(fmtDuration(6 * 60_000)).toBe("6 分");
    expect(fmtDuration(72 * 60_000)).toBe("1 小时 12 分");
  });
});
