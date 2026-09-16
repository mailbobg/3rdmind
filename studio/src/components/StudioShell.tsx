import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Chip } from "@heroui/react";
import * as studio from "../api/studio";
import type { RegionInfo } from "../api/studio";
import { StudioContext } from "../hooks/studioContext";
import type { Workspace } from "../hooks/studioContext";
import { setStorageWorkspace } from "../hooks/studioStorage";
import { useEnvironment } from "../hooks/useEnvironment";
import { useTrace } from "../hooks/useTrace";
import { useBacktests } from "../hooks/useBacktests";
import { useFactorBasket } from "../hooks/useFactorBasket";
import { useLayoutState } from "../hooks/useLayoutState";
import { DataSync } from "./DataSync";
import { DataBuild } from "./DataBuild";
import { LlmSettings } from "./LlmSettings";
import { Btn } from "./minimal";

/** The market workspaces, in toggle order. Each has its own experiments, factors, backtests and strategies. */
export const WORKSPACES: { region: string; label: string; base: string }[] = [
  { region: "cn", label: "A 股", base: "" },
  { region: "us", label: "美股", base: "/us" },
];
export function makeWorkspace(region: string): Workspace {
  const w = WORKSPACES.find((x) => x.region === region) || WORKSPACES[0];
  return { region: w.region, label: w.label, base: w.base, path: (p) => `${w.base}${p}`, href: (p) => `#${w.base}${p}` };
}

const MENU = [
  { path: "/research", symbol: "◎", title: "AI 研究", desc: "提出假设，开发并评估因子或模型" },
  { path: "/factors", symbol: "⊞", title: "因子库", desc: "研究产出的因子，挑选进组合" },
  { path: "/backtest", symbol: "◇", title: "组合回测", desc: "用已选因子构建并验证策略" },
  { path: "/strategies", symbol: "◈", title: "策略", desc: "保存验证过的组合，持续跟踪" },
  { path: "/runs", symbol: "↗", title: "运行记录", desc: "统一查看研究与回测" },
];

// RD-Agent's own Vue UI, served by the log server at "/" (rd-agent/web `npm run build:flask`). The React dev
// server has nothing at its root, so in DEV the link goes straight to the log server.
const PLAYGROUND_URL = import.meta.env.DEV ? "http://127.0.0.1:19899/#/Playground" : "/#/Playground";

const SWITCH_CODES: Record<string, string> = { cn: "CN", us: "US" };

/** The workspace switch at the top of the rail: a dark track with a sliding thumb, like a mode toggle. */
function MarketSwitch({ region, onChange }: { region: string; onChange: (r: string) => void }) {
  const index = Math.max(0, WORKSPACES.findIndex((w) => w.region === region));
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = (index + (e.key === "ArrowRight" ? 1 : WORKSPACES.length - 1)) % WORKSPACES.length;
    onChange(WORKSPACES[next].region);
  };
  return (
    <div role="tablist" aria-label="市场" className="mkt-switch mx-auto mb-4" style={{ "--mkt-n": WORKSPACES.length, "--mkt-i": index } as React.CSSProperties} onKeyDown={onKey}>
      <span className="mkt-switch__thumb" aria-hidden />
      {WORKSPACES.map((w) => (
        <button key={w.region} type="button" role="tab" aria-selected={w.region === region} tabIndex={w.region === region ? 0 : -1} onClick={() => onChange(w.region)} className="mkt-switch__item">
          <span className="mkt-switch__code">{SWITCH_CODES[w.region] || w.region.toUpperCase()}</span>
          <span className="mkt-switch__label">{w.label}</span>
        </button>
      ))}
    </div>
  );
}

/**
 * Root frame for one market workspace: the left rail plus the page outlet. Owns every cross-page store and hands
 * it down through context. The router mounts one shell per workspace (keyed by region), so switching markets
 * remounts everything with that market's stores, storage and API scope.
 */
export function StudioShell({ region }: { region: string }) {
  // Scope the API and local storage before any child hook reads them (render order: this runs first).
  studio.setApiRegion(region);
  setStorageWorkspace(region);
  const workspace = useMemo(() => makeWorkspace(region), [region]);
  const navigate = useNavigate();
  const location = useLocation();
  const [regions, setRegions] = useState<RegionInfo[] | null>(null);
  const loadRegions = () => studio.regions().then(setRegions).catch(() => setRegions([]));
  useEffect(() => { loadRegions(); }, [region]);
  const current = regions?.find((r) => r.region === region);
  // Same page, other market: strip this workspace's prefix and add the target's.
  const switchTo = (target: string) => {
    if (target === region) return;
    const rel = location.pathname.startsWith(workspace.base) ? location.pathname.slice(workspace.base.length) || "/research" : "/research";
    navigate(`${makeWorkspace(target).base}${rel}`);
  };
  const { env, load: reloadEnv } = useEnvironment();
  const trace = useTrace();
  const backtests = useBacktests();
  const basket = useFactorBasket();
  const layout = useLayoutState();
  useEffect(() => { reloadEnv(); trace.loadTraces(); backtests.load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const counts: Record<string, number | undefined> = { "/factors": basket.items.length || undefined, "/backtest": backtests.jobs.length || undefined };
  const value = useMemo(() => ({ workspace, env, reloadEnv, trace, backtests, basket, layout }), [workspace, env, reloadEnv, trace, backtests, basket, layout]);

  return (
    <StudioContext.Provider value={value}>
      <div className="grid h-full grid-cols-[230px_minmax(0,1fr)] gap-2 bg-background p-2">
        <aside className="flex min-h-0 flex-col overflow-y-auto rounded-r-2xl rounded-l-none border border-border bg-surface px-3.5 py-5">
          <MarketSwitch region={region} onChange={switchTo} />
          <a href={workspace.href("/research")} className="mx-auto flex flex-col items-center gap-0.5 no-underline" aria-label="AI 研究">
            <img src={`${import.meta.env.BASE_URL}rd-agent-mark.png`} alt="" className="size-20" />
            <small className="text-[11px] text-muted">RD-Agent × Qlib</small>
          </a>
          <nav aria-label="工作任务" className="mt-5 grid gap-2">
            {MENU.map((item) => (
              <NavLink key={item.path} to={workspace.path(item.path)}
                className={({ isActive }) => `flex items-start gap-2.5 rounded-[10px] px-2.5 py-3 text-left no-underline transition-colors ${isActive ? "bg-neutral-900 text-white" : "text-foreground hover:bg-surface-secondary"}`}>
                <span className="w-[22px] text-[19px] leading-none">{item.symbol}</span>
                <span className="min-w-0 text-[13px] font-medium">{item.title}<small className="mt-1 block text-[10px] font-normal leading-relaxed opacity-65">{item.desc}</small></span>
                {counts[item.path] && <span className="ml-auto text-[11px] opacity-60">{counts[item.path]}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="mt-6 border-t border-border" />
          <div className="mt-auto px-2 pt-8 text-xs">
            <LlmSettings onSaved={reloadEnv} />
            {region === "us" ? <DataBuild onBuilt={() => { reloadEnv(); loadRegions(); }} /> : <DataSync onSynced={reloadEnv} />}
            <div className="flex items-center gap-2">
              <i className={`inline-block size-[7px] rounded-full ${env ? (env.data_ready ? "bg-success" : "bg-warning") : "bg-danger"}`} />
              {env ? (env.data_ready ? `${workspace.label}数据已就绪` : `等待${workspace.label}数据`) : "后端未连接"}
            </div>
            {env ? (
              <small className="mb-4 mt-1.5 block text-muted">{env.start || "—"} → {env.end || "—"}</small>
            ) : (
              <small className="mb-4 mt-1.5 block text-muted">运行 <code>scripts/start-backend.sh</code> 后 <button className="text-accent underline" onClick={() => reloadEnv()}>重试</button></small>
            )}
            <a href={PLAYGROUND_URL} target="_blank" rel="noreferrer" className="text-muted">原生 Playground ↗</a>
          </div>
        </aside>
        {regions && current && !current.ready ? (
          <section className="flex min-h-0 flex-col items-center justify-center gap-3 rounded-2xl text-center" style={{ background: "var(--mm-ground)" }}>
            <div className="text-[15px] font-semibold">{workspace.label}数据还没构建</div>
            <p className="m-0 max-w-[420px] text-[12px] leading-relaxed text-muted">这个工作区的研究、因子库、回测和策略都要先有 Qlib 数据。{region === "us" ? "点下面从 Yahoo Finance 构建纳斯达克 100 的日线数据。" : "请先同步 Qlib 数据。"}</p>
            {region === "us" ? <DataBuild compact onBuilt={() => { reloadEnv(); loadRegions(); }} /> : <Btn onClick={() => loadRegions()}>重新检查</Btn>}
          </section>
        ) : <Outlet />}
      </div>
    </StudioContext.Provider>
  );
}
