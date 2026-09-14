import { describe, expect, it, vi } from "vitest";
import type { TraceEvent } from "../../api/studio";
import { events } from "./fixtures/trace";

vi.mock("../../api/studio", () => ({
  traceSnapshot: vi.fn(),
  traces: vi.fn(),
  stopResearch: vi.fn(),
  submitInteraction: vi.fn(),
}));

const { groupRounds, traceStatus, useTrace } = await import("../useTrace");
const studio = await import("../../api/studio");

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
  });
});

describe("useTrace", () => {
  function deferred<T>() {
    let resolve!: (v: T) => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
  }

  it("a stale select() response never clobbers a later selection", async () => {
    const a = deferred<TraceEvent[]>();
    const b = deferred<TraceEvent[]>();
    const snapshot = studio.traceSnapshot as unknown as ReturnType<typeof vi.fn>;
    snapshot.mockImplementation((id: string) => (id === "a" ? a.promise : b.promise));

    const trace = useTrace();
    const p1 = trace.select("a");
    const p2 = trace.select("b");

    a.resolve([{ tag: "research.hypothesis", timestamp: "1", loop_id: 0, content: {} }]);
    await p1;
    b.resolve([{ tag: "research.hypothesis", timestamp: "2", loop_id: 0, content: { hypothesis: "b" } }]);
    await p2;

    expect(trace.traceId.value).toBe("b");
    expect(trace.events.value).toEqual([{ tag: "research.hypothesis", timestamp: "2", loop_id: 0, content: { hypothesis: "b" } }]);

    trace.dispose();
  });

  it("select() surfaces an error and leaves events empty when the fetch rejects", async () => {
    const snapshot = studio.traceSnapshot as unknown as ReturnType<typeof vi.fn>;
    snapshot.mockRejectedValueOnce(new Error("boom"));

    const trace = useTrace();
    await trace.select("a");

    expect(trace.error.value).toBe("boom");
    expect(trace.events.value).toEqual([]);

    trace.dispose();
  });
});
