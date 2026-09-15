import { useCallback, useEffect, useMemo, useState } from "react";
import * as studio from "../api/studio";
import type { BacktestSummary, CorrelationMatrix as Corr, FactorRef, FactorWeight, LibraryFactor } from "../api/studio";
import { basketKey as key } from "../hooks/useFactorBasket";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { persistStudioState, restoreStudioState } from "../hooks/studioStorage";
import { download, errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { BacktestResultView } from "../components/BacktestResultView";
import { SelectBox } from "../components/fields";
import { Block, Btn, Empty, Field, FieldGrid, Link, Note, Num, NumberInput, P, SelectInput, Table, Tag, TextInput, TextTabs } from "../components/minimal";
import { Hint } from "../components/widgets";

type Market = "csi300" | "csi500" | "all";
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
  const [tab, setTab] = useState("params");
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
  useEffect(() => { if (backtests.jobs.length && !backtests.selectedId) backtests.select(backtests.jobs[0].id); }, [backtests.jobs]); // eslint-disable-line react-hooks/exhaustive-deps
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

  const statusLine = [
    coverage ? `覆盖 ${coverage.start} → ${coverage.end}` : "",
    factorRefs.length >= 2 ? (correlation ? `最高相关 ${maxCorr.toFixed(2)}${maxCorr >= 0.7 ? "（有信号重复）" : ""}` : correlationError ? "相关性计算失败" : "计算相关性…") : "",
  ].filter(Boolean).join(" · ");
  const lgbmKeys = ["learning_rate", "num_leaves", "max_depth", "n_estimators", "early_stopping_rounds"] as const;

  return (
    <PageFrame
      title="组合回测"
      description={basket.items.length ? `${basket.items.length} 个信号：${basket.items.map((f) => f.name).join("、")} · ${params.start || "?"} → ${params.end || "?"} · ${params.market}` : "信号篮为空，先去因子库挑选"}
      tag={method === "lgbm" ? "LightGBM" : "排名加权"}
      tabs={<TextTabs label="工作区视图" value={tab} onChange={setTab} items={[{ key: "params", label: "参数设置" }, { key: "source", label: "策略源码" }]} />}
      actions={<Btn kind="primary" disabled={backtests.busy || !env?.data_ready || !basket.items.length} onClick={submit}>{backtests.busy ? "运行中…" : "运行回测"}</Btn>}
      resultsTitle={result ? `回测 ${result.id.slice(0, 8)}` : "回测结果"}
      resultsActions={
        <>
          <SelectBox label="回测历史" isLabelHidden placeholder="回测历史" width={320} value={backtests.selectedId || null} onChange={(id) => { backtests.select(id); layout.openResults(); }}
            options={backtests.jobs.map((j) => ({ value: j.id, label: jobLabel(j) }))} />
          {result?.metrics && <Btn kind="text" onClick={() => download(`backtest-${result.id.slice(0, 8)}.json`, JSON.stringify(result, null, 2), "application/json")}>导出 JSON</Btn>}
        </>
      }
      results={result ? <BacktestResultView result={result} /> : <Hint>运行回测后在这里看指标、净值曲线、持仓与成交。</Hint>}
    >
      {(backtests.error || pageError) && <Note tone="bad" actions={<Btn kind="text" onClick={() => { backtests.setError(""); setPageError(""); }}>关闭</Btn>}>{backtests.error || pageError}</Note>}
      {!env && <Note>后端未连接，无法回测。运行 scripts/start-backend.sh 后刷新。</Note>}
      {env && !env.data_ready && <Note>Qlib 数据未就绪（{env.provider_uri}），无法回测。</Note>}

      {tab === "params" ? (
        <>
          <Block title="回测参数" note={`${params.start || "?"} → ${params.end || "?"} · ${params.market}`}>
            <FieldGrid min={140}>
              <Field label="开始"><TextInput type="date" value={params.start} onChange={(v) => set("start", v)} /></Field>
              <Field label="结束"><TextInput type="date" value={params.end} onChange={(v) => set("end", v)} /></Field>
              <Field label="股票池"><SelectInput value={params.market} onChange={(v) => set("market", v)} options={[{ value: "csi300", label: "沪深300" }, { value: "csi500", label: "中证500" }, { value: "all", label: "全市场" }]} /></Field>
              <Field label="基准"><TextInput value={params.benchmark} onChange={(v) => set("benchmark", v)} /></Field>
              <Field label="持股数" hint="每天按评分持有前 topk 只"><NumberInput value={params.topk} onChange={(v) => set("topk", v)} min={1} max={500} /></Field>
              <Field label="每日换出" hint="每天最多换出 n_drop 只"><NumberInput value={params.n_drop} onChange={(v) => set("n_drop", v)} min={0} max={500} /></Field>
              <Field label="初始资金"><NumberInput value={params.account} onChange={(v) => set("account", v)} min={1000} step={100000} /></Field>
              <Field label="买入费率" hint="0.0005 = 万分之五"><NumberInput value={params.open_cost} onChange={(v) => set("open_cost", v)} min={0} max={0.1} step={0.0001} /></Field>
              <Field label="卖出费率" hint="0.0015 含印花税"><NumberInput value={params.close_cost} onChange={(v) => set("close_cost", v)} min={0} max={0.1} step={0.0001} /></Field>
              <Field label="信号合成" hint="排名加权：截面百分位排名按权重求和；LightGBM：学信号与次日收益的关系，验证集早停">
                <SelectInput value={method} onChange={setMethod} options={[{ value: "rank", label: "排名加权" }, { value: "lgbm", label: "训练 LightGBM" }]} />
              </Field>
            </FieldGrid>
            {dateWarning && <div style={{ marginTop: 12 }}><Note actions={coverage && <Btn onClick={fitToCoverage}>按覆盖区间填日期</Btn>}>{dateWarning}</Note></div>}
          </Block>
          {method === "lgbm" && (
            <Block title="LightGBM" note="训练集学关系，验证集早停">
              <FieldGrid min={140}>
                <Field label="训练开始"><TextInput type="date" value={lgbm.train[0]} onChange={(v) => setLgbm((l) => ({ ...l, train: [v, l.train[1]] }))} /></Field>
                <Field label="训练结束"><TextInput type="date" value={lgbm.train[1]} onChange={(v) => setLgbm((l) => ({ ...l, train: [l.train[0], v] }))} /></Field>
                <Field label="验证开始"><TextInput type="date" value={lgbm.valid[0]} onChange={(v) => setLgbm((l) => ({ ...l, valid: [v, l.valid[1]] }))} /></Field>
                <Field label="验证结束"><TextInput type="date" value={lgbm.valid[1]} onChange={(v) => setLgbm((l) => ({ ...l, valid: [l.valid[0], v] }))} /></Field>
                {lgbmKeys.map((k) => <Field key={k} label={k}><NumberInput value={lgbm.params[k]} onChange={(v) => setLgbm((l) => ({ ...l, params: { ...l.params, [k]: v } }))} /></Field>)}
              </FieldGrid>
            </Block>
          )}
          <Block title="信号篮" count={basket.items.length} note={statusLine} noteTone={maxCorr >= 0.7 ? "bad" : "ok"}>
            {basket.items.length ? (
              <>
                <Table label="信号篮" columns={[{ label: "信号" }, { label: "来源", width: 200, optional: true }, { label: "IC", num: true, width: 82 }, { label: "Rank IC", num: true, width: 82 }, { label: "覆盖", width: 156, optional: true }, { label: "权重", num: true, width: 84 }, { label: "", width: 52 }]}
                  rows={basket.items.map((f) => ({
                    key: key(f),
                    cells: [
                      <span key="n"><span className="mm-mono mm-name">{f.name}</span>{f.kind === "prediction" && <Tag tone="dim"> · 模型预测</Tag>}</span>,
                      <span key="s" className="mm-dim block truncate">{shortName(f.trace)} · 第 {f.loop_id + 1} 轮</span>,
                      <Num key="ic" value={info(f)?.analysis?.ic.mean} />,
                      <Num key="ric" value={info(f)?.analysis?.rank_ic.mean} />,
                      <span key="cov" className="mm-mono mm-dim">{info(f)?.analysis ? `${info(f)!.analysis!.coverage.start.slice(0, 7)} → ${info(f)!.analysis!.coverage.end.slice(0, 7)}` : f.kind === "prediction" ? "模型测试期" : "未分析"}</span>,
                      <NumberInput key="w" className="mm-weight" ariaLabel="权重" step={0.5} value={f.weight} disabled={method === "lgbm"} onChange={(v) => basket.setWeight(f, v)} />,
                      <Link key="x" onClick={() => basket.toggle(f)}>移除</Link>,
                    ],
                  }))} />
                <P>
                  TopkDropoutStrategy · 前一日评分 · 当日收盘成交 · 权重为负 = 反向使用{method === "lgbm" ? "（LightGBM 模式下权重不生效）" : ""}
                  {coverageUnknown ? ` · ${coverageUnknown} 个信号未做单因子分析，覆盖区间未计入` : ""} · <Link href="#/factors">去因子库增减</Link>
                </P>
              </>
            ) : (
              <Empty>还没有选信号。去 <Link href="#/factors">因子库</Link> 勾选，或在研究轮次里点“用 N 个因子回测”。</Empty>
            )}
          </Block>
        </>
      ) : (
        <Block title="studio_worker.py" note="只读 · 服务端执行"><pre className="mm-pre">{source || "加载中…"}</pre></Block>
      )}
    </PageFrame>
  );
}
