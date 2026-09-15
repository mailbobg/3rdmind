import { useEffect, useMemo } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Chip } from "@heroui/react";
import { StudioContext } from "../hooks/studioContext";
import { useEnvironment } from "../hooks/useEnvironment";
import { useTrace } from "../hooks/useTrace";
import { useBacktests } from "../hooks/useBacktests";
import { useFactorBasket } from "../hooks/useFactorBasket";
import { useLayoutState } from "../hooks/useLayoutState";

const MENU = [
  { path: "/research", symbol: "◎", title: "AI 研究", desc: "提出假设，开发并评估因子或模型" },
  { path: "/factors", symbol: "⊞", title: "因子库", desc: "研究产出的因子，挑选进组合" },
  { path: "/backtest", symbol: "◇", title: "组合回测", desc: "用已选因子构建并验证策略" },
  { path: "/runs", symbol: "↗", title: "运行记录", desc: "统一查看研究与回测" },
];

// RD-Agent's own Vue UI, served by the log server at "/" (rd-agent/web `npm run build:flask`). The React dev
// server has nothing at its root, so in DEV the link goes straight to the log server.
const PLAYGROUND_URL = import.meta.env.DEV ? "http://127.0.0.1:19899/#/Playground" : "/#/Playground";

/** Root frame: the left rail plus the page outlet. Owns every cross-page store and hands it down through context. */
export function StudioShell() {
  const { env, load: reloadEnv } = useEnvironment();
  const trace = useTrace();
  const backtests = useBacktests();
  const basket = useFactorBasket();
  const layout = useLayoutState();
  useEffect(() => { reloadEnv(); trace.loadTraces(); backtests.load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const counts: Record<string, number | undefined> = { "/factors": basket.items.length || undefined, "/backtest": backtests.jobs.length || undefined };
  const value = useMemo(() => ({ env, reloadEnv, trace, backtests, basket, layout }), [env, reloadEnv, trace, backtests, basket, layout]);

  return (
    <StudioContext.Provider value={value}>
      <div className="grid h-full grid-cols-[230px_minmax(0,1fr)] gap-2 bg-background p-2">
        <aside className="flex min-h-0 flex-col overflow-y-auto rounded-2xl border border-border bg-surface px-3.5 py-5">
          <a href="#/research" className="block no-underline" aria-label="AI 研究">
            <img src={`${import.meta.env.BASE_URL}rd-agent-mark.png`} alt="" className="size-16" />
          </a>
          <nav aria-label="工作任务" className="mt-8 grid gap-2">
            {MENU.map((item) => (
              <NavLink key={item.path} to={item.path}
                className={({ isActive }) => `flex items-start gap-2.5 rounded-[10px] px-2.5 py-3 text-left no-underline transition-colors ${isActive ? "bg-neutral-900 text-white" : "text-foreground hover:bg-surface-secondary"}`}>
                <span className="w-[22px] text-[19px] leading-none">{item.symbol}</span>
                <span className="min-w-0 text-[13px] font-medium">{item.title}<small className="mt-1 block text-[10px] font-normal leading-relaxed opacity-65">{item.desc}</small></span>
                {counts[item.path] && <span className="ml-auto text-[11px] opacity-60">{counts[item.path]}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="mt-6 border-t border-border px-2 pt-5 text-[11px] text-muted">
            <strong className="font-medium text-foreground/70">标准工作流</strong>
            <p className="my-2 leading-relaxed">研究产生候选 → 因子库挑选 → 组合回测验证。</p>
            <p className="my-2 leading-relaxed">所有成功与失败都保留在运行记录中。</p>
          </div>
          <div className="mt-auto px-2 pt-8 text-xs">
            <div className="flex items-center gap-2">
              <i className={`inline-block size-[7px] rounded-full ${env ? (env.data_ready ? "bg-success" : "bg-warning") : "bg-danger"}`} />
              {env ? (env.data_ready ? "Qlib 数据已就绪" : "等待 Qlib 数据") : "后端未连接"}
            </div>
            {env ? (
              <small className="mb-4 mt-1.5 block text-muted">{env.start || "—"} → {env.end || "—"}<br />{(env.chat_model || "未配置研究模型").replace("deepseek/", "")}</small>
            ) : (
              <small className="mb-4 mt-1.5 block text-muted">运行 <code>scripts/start-backend.sh</code> 后 <button className="text-accent underline" onClick={() => reloadEnv()}>重试</button></small>
            )}
            <a href={PLAYGROUND_URL} target="_blank" rel="noreferrer" className="text-muted">原生 Playground ↗</a>
          </div>
        </aside>
        <Outlet />
      </div>
    </StudioContext.Provider>
  );
}
