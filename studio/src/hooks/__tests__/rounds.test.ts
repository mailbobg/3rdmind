import { describe, expect, it } from "vitest";
import { events } from "./fixtures/trace";
import { groupRounds, traceStatus } from "../rounds";

describe("groupRounds", () => {
  it("groups events by loop_id in order", () => {
    const rounds = groupRounds(events);
    expect(rounds.map((r) => r.id)).toEqual(["0", "1"]);
  });
  it("assembles a complete round", () => {
    const [round] = groupRounds(events);
    expect(round.hypothesis.hypothesis).toBe("Short-term reversal");
    expect(round.tasks).toEqual([{ name: "STR_5", description: "d" }]);
    expect(round.files).toEqual([{ name: "factor.py", code: "print(1)", task: "STR_5", loop: "0" }]);
    expect(round.metrics).toEqual({ IC: 0.01 });
    expect(round.factors).toEqual(["STR_5"]);
    expect(round.chartHtml).toBe("<html/>");
    expect(round.feedback?.decision).toBe(true);
    expect(round.status).toBe("接受");
  });
  it("labels an unfinished round", () => {
    const [, second] = groupRounds(events);
    expect(second.status).toBe("假设待验证");
    expect(second.metrics).toBeNull();
    expect(second.factors).toEqual([]);
  });
  it("ignores events without loop_id", () => {
    expect(groupRounds([{ tag: "END", timestamp: "1", content: {} }])).toEqual([]);
  });
});

describe("traceStatus", () => {
  it("reads the END code", () => {
    expect(traceStatus(events)).toBe("已完成");
    expect(traceStatus([{ tag: "END", timestamp: "1", content: { end_code: -1 } }])).toBe("已停止");
    expect(traceStatus([{ tag: "END", timestamp: "1", content: { end_code: 2 } }])).toBe("执行失败");
    expect(traceStatus(events.slice(0, 3))).toBe("运行中");
    expect(traceStatus([])).toBe("未加载");
    expect(traceStatus([], "alive")).toBe("启动中");
    expect(traceStatus([], "dead")).toBe("已结束");
  });
});
