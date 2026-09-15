import { useCallback, useEffect, useMemo, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Code } from "@astryxdesign/core/Code";
import { DateInput } from "@astryxdesign/core/DateInput";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Selector } from "@astryxdesign/core/Selector";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Link } from "@astryxdesign/core/Link";
import * as studio from "../api/studio";
import type { BacktestSummary, CorrelationMatrix as Corr, FactorRef, FactorWeight, LibraryFactor } from "../api/studio";
import { basketKey as key } from "../hooks/useFactorBasket";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { persistStudioState, restoreStudioState } from "../hooks/studioStorage";
import { download, errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { Panel } from "../components/Panel";
import { BacktestResultView } from "../components/BacktestResultView";
import { CodeView, Signed, fixed } from "../components/widgets";

type Market = "csi300" | "csi500" | "all";
type ISODate = `${number}${number}${number}${number}-${number}${number}-${number}${number}`;
interface Params { start: string; end: string; market: Market; benchmark: string; topk: number; n_drop: number; account: number; open_cost: number; close_cost: number }
interface Lgbm { train: [string, string]; valid: [string, string]; params: Record<string, number> }

const shiftYears = (date: string, years: number) => { const d = new Date(date); d.setFullYear(d.getFullYear() + years); return d.toISOString().slice(0, 10); };
const dayBefore = (date: string) => { const d = new Date(date); d.setDate(d.getDate() - 1); return d.toISOString().slice(0, 10); };
const LGBM_DEFAULTS = { learning_rate: 0.05, num_leaves: 63, max_depth: 8, n_estimators: 1000, early_stopping_rounds: 50, colsample_bytree: 0.8, subsample: 0.8, lambda_l2: 1 };

export function BacktestPage() {
  const { env, backtests, basket, layout } = useStudio();
  const saved = useMemo(() => restoreStudioState(), []);
  const [params, setParams] = useState<Params>({
    start: "", end: "", market: "csi300", benchmark: "SH000300", topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015, ...(saved.params || {}),
  });
  const set = <K extends keyof Params>(k: K, v: Params[K]) => setParams((p) => ({ ...p, [k]: v }));
  const [method, setMethod] = useState<"rank" | "lgbm">(saved.model?.method === "lgbm" ? "lgbm" : "rank");
  const [lgbm, setLgbm] = useState<Lgbm>({
    train: ["", ""], valid: ["", ""], params: { ...LGBM_DEFAULTS },
    ...(saved.model?.method === "lgbm" ? { train: saved.model.train, valid: saved.model.valid, params: { ...LGBM_DEFAULTS, ...saved.model.params } } : {}),
  });
  const [tab, setTab] = useState<"params" | "source">("params");
  const [source, setSource] = useState("");
  const [pageError, setPageError] = useState("");
  const [library, setLibrary] = useState<Record<string, LibraryFactor>>({});
  const info = (f: FactorWeight) => library[key(f)];

  // Default windows once the environment is known: the last year of data, and 1 + 1 years before it for a model.
  useEffect(() => {
    const end = env?.end;
    if (!end) return;
    setParams((p) => (p.start && p.end ? p : { ...p, end, start: shiftYears(end, -1) }));
  }, [env]);
  useEffect(() => {
    if (lgbm.train[0] || !params.start) return;
    const valid: [string, string] = [shiftYears(params.start, -1), dayBefore(params.start)];
    setLgbm((l) => ({ ...l, valid, train: [shiftYears(params.start, -2), dayBefore(valid[0])] }));
  }, [params.start, lgbm.train]);
  useEffect(() => { studio.factorLibrary().then((list) => setLibrary(Object.fromEntries(list.map((f) => [key(f), f])))).catch(() => {}); }, []);
  useEffect(() => {
    if (backtests.jobs.length && !backtests.selectedId) backtests.select(backtests.jobs[0].id);
  }, [backtests.jobs]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (tab === "source" && !source) studio.strategySource().then((r) => setSource(r.code)).catch((e) => setPageError(errorText(e))); }, [tab, source]);

  // Pairwise correlation of the factor signals in the basket (predictions excluded), debounced.
  const factorRefs = useMemo<FactorRef[]>(() => basket.items.filter((f) => (f.kind || "factor") === "factor").map((f) => ({ trace: f.trace, loop_id: f.loop_id, name: f.name })), [basket.items]);
  const [correlation, setCorrelation] = useState<Corr | null>(null);
  const [correlationError, setCorrelationError] = useState("");
  useEffect(() => {
    setCorrelation(null); setCorrelationError("");
    if (factorRefs.length < 2) return;
    const t = setTimeout(() => studio.factorCorrelation(factorRefs).then(setCorrelation).catch((e) => setCorrelationError(errorText(e))), 400);
    return () => clearTimeout(t);
  }, [factorRefs]);
  const maxCorr = useMemo(() => {
    if (!correlation) return 0;
    let m = 0;
    correlation.matrix.forEach((row, i) => row.forEach((v, j) => { if (i !== j) m = Math.max(m, Math.abs(v)); }));
    return m;
  }, [correlation]);
  const coverage = useMemo(() => {
    const spans = basket.items.map((f) => info(f)?.analysis?.coverage).filter((c): c is { start: string; end: string } => !!c);
    if (!spans.length) return null;
    return { start: spans.reduce((a, c) => (c.start > a ? c.start : a), spans[0].start), end: spans.reduce((a, c) => (c.end < a ? c.end : a), spans[0].end) };
  }, [basket.items, library]); // eslint-disable-line react-hooks/exhaustive-deps
  const coverageUnknown = basket.items.filter((f) => !info(f)?.analysis).length;
  const dateWarning = useMemo(() => {
    if (!coverage || !params.start || !params.end) return "";
    if (params.start <= coverage.start) return `回测开始日 ${params.start} 不晚于信号首日 ${coverage.start}：策略要用前一天的评分，请把开始日往后挪。`;
    if (params.end > coverage.end) return `回测结束日 ${params.end} 超出信号覆盖末日 ${coverage.end}，会直接报错。`;
    return "";
  }, [coverage, params.start, params.end]);
  const fitToCoverage = () => {
    if (!coverage) return;
    const start = new Date(coverage.start); start.setDate(start.getDate() + 1);
    setParams((p) => ({ ...p, start: start.toISOString().slice(0, 10), end: coverage.end }));
  };

  const submit = useCallback(async () => {
    const model = method === "lgbm" ? { method: "lgbm" as const, train: [...lgbm.train] as [string, string], valid: [...lgbm.valid] as [string, string], params: { ...lgbm.params } } : { method: "rank" as const };
    const accepted = await backtests.run({ factors: basket.items.map((f) => ({ ...f, weight: Number(f.weight) })), model, ...params });
    if (accepted) { persistStudioState({ params, model }); layout.openResults(); }
  }, [method, lgbm, basket.items, params, backtests, layout]);
  const result = backtests.result;
  const jobLabel = (job: BacktestSummary) =>
    `${backtestStatusLabel(job.status)}${job.total_return != null ? ` ${(job.total_return * 100).toFixed(1)}%` : ""} · ${job.config.factors?.length ?? 0} 信号 · ${job.config.model?.method === "lgbm" ? "LGBM" : "排名"} · ${job.config.start} → ${job.config.end}`;

  const basketRows = basket.items.map((f) => ({ ...f, _key: key(f) }));
  const statusLine = [
    coverage ? `覆盖 ${coverage.start} → ${coverage.end}` : "",
    factorRefs.length >= 2 ? (correlation ? `最高相关 ${maxCorr.toFixed(2)}${maxCorr >= 0.7 ? "（有信号重复）" : ""}` : correlationError ? "相关性计算失败" : "计算相关性…") : "",
  ].filter(Boolean).join(" · ");

  return (
    <PageFrame
      title="组合回测"
      description={basket.items.length ? `${basket.items.length} 个信号：${basket.items.map((f) => f.name).join("、")} · ${params.start || "?"} → ${params.end || "?"} · ${params.market}` : "信号篮为空，先去因子库挑选"}
      tag={method === "lgbm" ? "LightGBM" : "排名加权"}
      tabs={
        <SegmentedControl label="工作区视图" value={tab} onChange={(v) => setTab(v as "params" | "source")} size="sm">
          <SegmentedControlItem value="params" label="参数设置" />
          <SegmentedControlItem value="source" label="策略源码" />
        </SegmentedControl>
      }
      actions={<Button variant="primary" label="▶ 运行回测" isDisabled={backtests.busy || !env?.data_ready || !basket.items.length} isLoading={backtests.busy} onClick={submit} />}
      resultsTitle={result ? `回测 ${result.id.slice(0, 8)}` : "回测结果"}
      resultsActions={
        <>
          <Selector label="回测历史" placeholder="回测历史" size="sm" value={backtests.selectedId} onChange={(id) => { backtests.select(id); layout.openResults(); }}
            options={backtests.jobs.map((j) => ({ value: j.id, label: jobLabel(j) }))} />
          {result?.metrics && <Button size="sm" variant="ghost" label="导出 JSON" onClick={() => download(`backtest-${result.id.slice(0, 8)}.json`, JSON.stringify(result, null, 2), "application/json")} />}
        </>
      }
      results={result ? <BacktestResultView result={result} /> : <EmptyState title="还没有结果" description="运行回测后在这里看指标、净值曲线、持仓与成交。" isCompact />}
    >
      <VStack gap={3}>
        {(backtests.error || pageError) && <Banner status="error" title={backtests.error || pageError} isDismissable onDismiss={() => { backtests.setError(""); setPageError(""); }} collapsible={false} />}
        {!env && <Banner status="warning" title="后端未连接，无法回测。运行 scripts/start-backend.sh 后刷新。" collapsible={false} />}
        {env && !env.data_ready && <Banner status="warning" title={`Qlib 数据未就绪（${env.provider_uri}），无法回测。`} collapsible={false} />}

        {tab === "params" ? (
          <>
            <HStack gap={2} wrap="wrap" align="end">
              <DateInput label="开始" size="sm" value={params.start as ISODate} onChange={(v) => set("start", v || "")} />
              <DateInput label="结束" size="sm" value={params.end as ISODate} onChange={(v) => set("end", v || "")} />
              <NumberInput label="初始资金" size="sm" value={params.account} onChange={(v) => set("account", v)} />
              <Selector label="股票池" size="sm" value={params.market} onChange={(v) => set("market", v as Market)} options={[{ value: "csi300", label: "沪深300" }, { value: "csi500", label: "中证500" }, { value: "all", label: "全市场" }]} />
              <TextInput label="基准指数" size="sm" value={params.benchmark} onChange={(v) => set("benchmark", v)} />
              <NumberInput label="持股数 topk" size="sm" value={params.topk} onChange={(v) => set("topk", v)} description="每天按评分持有前 topk 只" />
              <NumberInput label="每日换出 n_drop" size="sm" value={params.n_drop} onChange={(v) => set("n_drop", v)} description="每天最多换出 n_drop 只" />
              <NumberInput label="买入费率" size="sm" value={params.open_cost} onChange={(v) => set("open_cost", v)} description="0.0005 = 万分之五" />
              <NumberInput label="卖出费率" size="sm" value={params.close_cost} onChange={(v) => set("close_cost", v)} description="0.0015 含印花税" />
            </HStack>
            <HStack gap={2} wrap="wrap" align="end">
              <Selector label="信号合成" size="sm" value={method} onChange={(v) => setMethod(v as "rank" | "lgbm")}
                options={[{ value: "rank", label: "排名加权", description: "每天做截面百分位排名，按权重求和" }, { value: "lgbm", label: "训练 LightGBM", description: "学信号与次日收益的关系，验证集早停" }]} />
              {method === "lgbm" && (
                <>
                  <DateInput label="训练开始" size="sm" value={lgbm.train[0] as ISODate} onChange={(v) => setLgbm((l) => ({ ...l, train: [v || "", l.train[1]] }))} />
                  <DateInput label="训练结束" size="sm" value={lgbm.train[1] as ISODate} onChange={(v) => setLgbm((l) => ({ ...l, train: [l.train[0], v || ""] }))} />
                  <DateInput label="验证开始" size="sm" value={lgbm.valid[0] as ISODate} onChange={(v) => setLgbm((l) => ({ ...l, valid: [v || "", l.valid[1]] }))} />
                  <DateInput label="验证结束" size="sm" value={lgbm.valid[1] as ISODate} onChange={(v) => setLgbm((l) => ({ ...l, valid: [l.valid[0], v || ""] }))} />
                  {(["learning_rate", "num_leaves", "max_depth", "n_estimators", "early_stopping_rounds"] as const).map((k) => (
                    <NumberInput key={k} label={k} size="sm" value={lgbm.params[k]} onChange={(v) => setLgbm((l) => ({ ...l, params: { ...l.params, [k]: v } }))} />
                  ))}
                </>
              )}
            </HStack>
            {dateWarning && <Banner status="warning" title={dateWarning} collapsible={false} endContent={coverage && <Button size="sm" label="按覆盖区间填日期" onClick={fitToCoverage} />} />}

            <Panel
              title={<>信号篮 <Text type="supporting">{basket.items.length} 个 · <Link href="#/factors">去因子库增减</Link></Text></>}
              status={statusLine}
              statusTone={maxCorr >= 0.7 ? "bad" : "ok"}
              flush
              footer={basket.items.length ? `TopkDropoutStrategy · 前一日评分 · 当日收盘成交${coverageUnknown ? ` · ${coverageUnknown} 个信号未做单因子分析，覆盖区间未计入` : ""}` : undefined}>
              {basket.items.length ? (
                <Table
                  data={basketRows}
                  idKey="_key"
                  density="compact"
                  columns={[
                    { key: "name", header: "信号", width: proportional(2), renderCell: (r) => (
                      <VStack gap={0}>
                        <HStack gap={1} align="center">{r.kind === "prediction" && <Badge label="模型" />}<Code>{r.name}</Code></HStack>
                        {info(r)?.description && <Text type="supporting" maxLines={2}>{info(r)!.description!}</Text>}
                      </VStack>) },
                    { key: "trace", header: "来源", width: pixel(200), renderCell: (r) => <Text type="supporting">{shortName(r.trace)} · 第 {r.loop_id + 1} 轮</Text> },
                    { key: "ic", header: "IC", width: pixel(80), align: "end", renderCell: (r) => <Signed value={info(r)?.analysis?.ic.mean} /> },
                    { key: "rank_ic", header: "Rank IC", width: pixel(80), align: "end", renderCell: (r) => <Signed value={info(r)?.analysis?.rank_ic.mean} /> },
                    { key: "coverage", header: "覆盖", width: pixel(190), renderCell: (r) => <Text type="supporting">{info(r)?.analysis ? `${info(r)!.analysis!.coverage.start} → ${info(r)!.analysis!.coverage.end}` : r.kind === "prediction" ? "模型测试期" : "未分析"}</Text> },
                    { key: "weight", header: "权重", width: pixel(110), align: "end", renderCell: (r) => (
                      <Tooltip content="负权重 = 反向使用；LightGBM 模式下不生效">
                        <NumberInput label="权重" isLabelHidden size="sm" value={r.weight} isDisabled={method === "lgbm"} onChange={(v) => basket.setWeight(r, v)} />
                      </Tooltip>) },
                    { key: "_key", header: "", width: pixel(64), renderCell: (r) => <Button size="sm" variant="ghost" label="移除" onClick={() => basket.toggle(r)} /> },
                  ]}
                />
              ) : (
                <EmptyState title="还没有选信号" description="去因子库勾选，或在研究轮次里点“用 N 个因子回测”。" isCompact actions={<Link href="#/factors">去因子库</Link>} />
              )}
            </Panel>
          </>
        ) : (
          <Panel title="studio_worker.py" status="只读 · 服务端执行" flush>
            <CodeView code={source || "加载中…"} title="studio_worker.py" />
          </Panel>
        )}
      </VStack>
    </PageFrame>
  );
}
