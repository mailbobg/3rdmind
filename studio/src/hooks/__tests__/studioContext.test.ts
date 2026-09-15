import { describe, expect, it } from "vitest";
import { capitalize, shortName } from "../studioContext";

describe("display names", () => {
  it("upper-cases the first Latin letter and leaves the rest alone", () => {
    expect(capitalize("undirected-joist-resume")).toBe("Undirected-joist-resume");
    expect(capitalize("risk_adjusted_momentum_20d")).toBe("Risk_adjusted_momentum_20d");
    expect(capitalize("STR_5")).toBe("STR_5");
    expect(capitalize("第 1 轮")).toBe("第 1 轮");
    expect(capitalize("回测 f8b91c9a")).toBe("回测 f8b91c9a");
    expect(capitalize("")).toBe("");
  });
  it("shows the experiment name after the scenario prefix, capitalised", () => {
    expect(shortName("Finance Data Building/undirected-joist-resume")).toBe("Undirected-joist-resume");
    expect(shortName("bare-id")).toBe("Bare-id");
  });
});
