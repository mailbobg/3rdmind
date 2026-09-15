import { useEffect, useMemo } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Theme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { AppShell } from "@astryxdesign/core/AppShell";
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { NavIcon } from "@astryxdesign/core/NavIcon";
import { Badge } from "@astryxdesign/core/Badge";
import { StatusDot } from "@astryxdesign/core/StatusDot";
import { VStack, HStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Link } from "@astryxdesign/core/Link";
import { StudioContext } from "../hooks/studioContext";
import { useEnvironment } from "../hooks/useEnvironment";
import { useTrace } from "../hooks/useTrace";
import { useBacktests } from "../hooks/useBacktests";
import { useFactorBasket } from "../hooks/useFactorBasket";
import { useLayoutState } from "../hooks/useLayoutState";

const MENU = [
  { path: "/research", title: "AI 研究", desc: "提出假设，开发并评估因子或模型" },
  { path: "/factors", title: "因子库", desc: "研究产出的因子，挑选进组合" },
  { path: "/backtest", title: "组合回测", desc: "用已选因子构建并验证策略" },
  { path: "/runs", title: "运行记录", desc: "统一查看研究与回测" },
];

/** Root frame: side nav plus the page outlet. Owns every cross-page store and hands it down through context. */
export function StudioShell() {
  const { env, load: reloadEnv } = useEnvironment();
  const trace = useTrace();
  const backtests = useBacktests();
  const basket = useFactorBasket();
  const layout = useLayoutState();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => { reloadEnv(); trace.loadTraces(); backtests.load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const counts: Record<string, number | undefined> = { "/factors": basket.items.length, "/backtest": backtests.jobs.length };
  const value = useMemo(() => ({ env, reloadEnv, trace, backtests, basket, layout }), [env, reloadEnv, trace, backtests, basket, layout]);

  return (
    <Theme theme={neutralTheme}>
      <StudioContext.Provider value={value}>
        <AppShell
          height="fill"
          variant="elevated"
          contentPadding={0}
          sideNav={
            <SideNav
              header={<SideNavHeading icon={<NavIcon icon={<span style={{ fontFamily: "Georgia, serif", fontSize: 18 }}>R</span>} />} heading="Research Studio" subheading="RD-Agent × Qlib" headingHref="#/research" />}
              footer={
                <VStack gap={1}>
                  <HStack gap={1} align="center">
                    <StatusDot variant={env ? (env.data_ready ? "success" : "warning") : "error"} label={env ? (env.data_ready ? "Qlib 数据已就绪" : "等待 Qlib 数据") : "后端未连接"} />
                    <Text type="supporting">{env ? (env.data_ready ? "Qlib 数据已就绪" : "等待 Qlib 数据") : "后端未连接"}</Text>
                  </HStack>
                  {env ? (
                    <Text type="supporting">{env.start || "—"} → {env.end || "—"}<br />{(env.chat_model || "未配置研究模型").replace("deepseek/", "")}</Text>
                  ) : (
                    <Text type="supporting">运行 scripts/start-backend.sh 后 <Link onClick={() => reloadEnv()}>重试</Link></Text>
                  )}
                  <Link href="/#/Playground" target="_blank">原生 Playground ↗</Link>
                </VStack>
              }
              >
              <SideNavSection title="工作任务" isHeaderHidden>
                {MENU.map((item) => (
                  <SideNavItem
                    key={item.path}
                    label={item.title}
                    isSelected={location.pathname === item.path}
                    onClick={(e) => { e.preventDefault(); navigate(item.path); }}
                    href={`#${item.path}`}
                    endContent={counts[item.path] ? <Badge label={String(counts[item.path])} /> : undefined}
                  />
                ))}
              </SideNavSection>
              <SideNavSection title="标准工作流">
                <Text type="supporting" as="p">研究产生候选 → 因子库挑选 → 组合回测验证。所有成功与失败都保留在运行记录中。</Text>
              </SideNavSection>
            </SideNav>
          }>
          <Outlet />
        </AppShell>
      </StudioContext.Provider>
    </Theme>
  );
}
