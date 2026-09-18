import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, stdoutUrl } from "./studio";

function mockFetch(status: number, body: string) {
  globalThis.fetch = vi.fn(async () => new Response(body, { status })) as never;
}
afterEach(() => vi.restoreAllMocks());

describe("api", () => {
  it("returns parsed json", async () => {
    mockFetch(200, '{"ok":1}');
    expect(await api("/x")).toEqual({ ok: 1 });
  });
  it("throws the backend error field", async () => {
    mockFetch(400, '{"error":"bad"}');
    await expect(api("/x", {})).rejects.toMatchObject({ message: "bad", status: 400 });
  });
  it("names an unreachable backend", async () => {
    mockFetch(502, "");
    await expect(api("/x")).rejects.toBeInstanceOf(ApiError);
    await expect(api("/x")).rejects.toThrow("后端未连接");
  });
  it("posts FormData without a json header", async () => {
    mockFetch(200, "{}");
    await api("/upload", new FormData());
    const init = (globalThis.fetch as never as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(init.headers).toEqual({});
  });
});

it("builds stdout url", () => {
  expect(stdoutUrl("a/b c")).toBe("/stdout?id=a%2Fb+c");
});
