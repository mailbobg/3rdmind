import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Chip } from "@heroui/react";
import * as studio from "../api/studio";
import type { CorrelationMatrix as Corr, FactorRef, LibraryFactor } from "../api/studio";
import { basketKey as key } from "../hooks/useFactorBasket";
import { download, errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { Section } from "../components/Section";
import { Block, Btn, Empty, Link, Note, Num, Table, Tag, TextInput, TextTabs } from "../components/minimal";
import { CodeView, CorrelationMatrix, DataTable, Formula, Hint, IcBars, MetricGrid, MetricTable, Mono, Signed } from "../components/widgets";

const GUIDE = "① 单独有没有用：看 IC / Rank IC 的符号和 ICIR（均值÷波动）；|IC|<0.01 且 ICIR≈0 基本是噪声，IC 为负的回测时权重设 −1 反向。② 放一起合不合适：篮内两两相关 |ρ|<0.5 才互补，高相关只是重复计权。③ 覆盖区间要包住回测期。";

export function FactorsPage() {
  const { basket, layout } = useStudio();
  const navigate = useNavigate();
  const [all, setAll] = useState<LibraryFactor[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedKey, setSelectedKey] = useState("");
  // The results column answers one of two questions: "what is this factor" or "do these go together".
  const [view, setView] = useState<"factor" | "basket">("factor");
  const [busyKey, setBusyKey] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzed, setAnalyzed] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try { setAll(await studio.factorLibrary()); setError(""); } catch (e) { setError(errorText(e)); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter((f) => (filter !== "accepted" || f.decision === true) && (!q || `${f.name} ${f.description || ""} ${f.trace}`.toLowerCase().includes(q)));
  }, [all, query, filter]);
  const groups = useMemo(() => {
    const map = new Map<string, LibraryFactor[]>();
    for (const f of rows) { if (!map.has(f.trace)) map.set(f.trace, []); map.get(f.trace)!.push(f); }
    return [...map.entries()].map(([trace, items]) => ({ trace, items }));
  }, [rows]);
  const selected = useMemo(() => all.find((f) => key(f) === selectedKey) || null, [all, selectedKey]);
  const pending = useMemo(() => all.filter((f) => !f.analysis), [all]);

  const analyze = useCallback(async (f: LibraryFactor) => {
    setBusyKey(key(f));
    try {
      const analysis = await studio.factorAnalysis(f);
      setAll((list) => list.map((item) => (key(item) === key(f) ? { ...item, analysis } : item)));
    } catch (e) { setError(`${f.name}：${errorText(e)}`); } finally { setBusyKey(""); }
  }, []);
  const analyzeAll = useCallback(async () => {
    // Sequential on purpose: each analysis is a Qlib subprocess; parallel runs would fight for CPU and memory.
    setAnalyzing(true); setAnalyzed(0);
    try { for (const f of pending) { await analyze(f); setAnalyzed((n) => n + 1); } } finally { setAnalyzing(false); }
  }, [pending, analyze]);
  const select = (f: LibraryFactor) => { setSelectedKey(key(f)); setView("factor"); layout.openResults(); if (!f.analysis && busyKey !== key(f)) analyze(f); };
  const check = (f: LibraryFactor) => { basket.toggle(f); setView("basket"); layout.openResults(); };
  const showBasket = () => { setView("basket"); layout.openResults(); };
  const library = useMemo(() => new Map(all.map((f) => [key(f), f])), [all]);

  const basketFactors = useMemo<FactorRef[]>(() => basket.items.filter((f) => (f.kind || "factor") === "factor").map((f) => ({ trace: f.trace, loop_id: f.loop_id, name: f.name })), [basket.items]);
  const [correlation, setCorrelation] = useState<Corr | null>(null);
  const [correlationError, setCorrelationError] = useState("");
  useEffect(() => {
    setCorrelation(null); setCorrelationError("");
    if (basketFactors.length < 2) return;
    const t = setTimeout(() => studio.factorCorrelation(basketFactors).then(setCorrelation).catch((e) => setCorrelationError(errorText(e))), 400);
    return () => clearTimeout(t);
  }, [basketFactors]);
  const strongest = useMemo(() => {
    if (!correlation) return null;
    let best = { value: 0, a: "", b: "" };
    correlation.matrix.forEach((row, i) => row.forEach((v, j) => { if (i < j && Math.abs(v) > Math.abs(best.value)) best = { value: v, a: correlation.names[i], b: correlation.names[j] }; }));
    return best;
  }, [correlation]);
  const maxCorr = strongest ? Math.abs(strongest.value) : 0;
  const basketCoverage = useMemo(() => {
    const spans = basket.items.map((f) => library.get(key(f))?.analysis?.coverage).filter((c): c is { start: string; end: string } => !!c);
    if (!spans.length) return null;
    return { start: spans.reduce((a, c) => (c.start > a ? c.start : a), spans[0].start), end: spans.reduce((a, c) => (c.end < a ? c.end : a), spans[0].end), missing: basket.items.length - spans.length };
  }, [basket.items, library]);
  const statusLine = basketFactors.length >= 2
    ? (correlation ? `篮内最高相关 ${maxCorr.toFixed(2)}${maxCorr >= 0.7 ? "（有因子重复）" : ""}` : correlationError ? "相关性计算失败" : "计算相关性…") : undefined;
  const decisionTag = (d: boolean | null) => d === true ? <Tag tone="ok">接受</Tag> : d === false ? <Tag tone="bad">拒绝</Tag> : <Tag tone="dim">—</Tag>;

  return (
    <PageFrame
      tabs={<TextTabs label="筛选" value={filter} onChange={setFilter} items={[{ key: "all", label: "全部因子" }, { key: "accepted", label: "Agent 接受的轮次" }]} />}
      actions={
        <>
          <TextInput type="search" ariaLabel="搜索因子" placeholder="搜索因子或实验" value={query} onChange={setQuery} className="w-44" />
          <Btn disabled={analyzing || !pending.length} onClick={analyzeAll}>{analyzing ? `分析中 ${analyzed}/${pending.length}…` : `分析全部（${pending.length}）`}</Btn>
          <Btn onClick={load}>刷新</Btn>
        </>
      }
      resultsTitle={<TextTabs label="右栏视图" value={view} onChange={(v) => setView(v as "factor" | "basket")} items={[{ key: "factor", label: selected ? selected.name : "因子详情" }, { key: "basket", label: `组合篮 ${basket.items.length}` }]} />}
      resultsActions={view === "factor"
        ? (selected ? <Btn kind={basket.has(selected) ? undefined : "primary"} onClick={() => check(selected)}>{basket.has(selected) ? "移出组合" : "加入组合"}</Btn> : undefined)
        : (basket.items.length ? <><Btn kind="text" onClick={basket.clear}>清空</Btn><Btn kind="primary" onClick={() => navigate("/backtest")}>去组合回测 →</Btn></> : undefined)}
      results={view === "factor" ? (
        selected ? (
          <div className="flex flex-col gap-3">
            <Section title="这是什么" note={`${selected.trace} · 第 ${selected.loop_id + 1} 轮`}>
              <p className="m-0 text-xs">{selected.description || "Agent 没有记录描述。"}</p>
              {selected.formulation && <Formula source={selected.formulation} />}
              {selected.variables && Object.keys(selected.variables).length > 0 && (
                <Hint>变量：{Object.entries(selected.variables).map(([v, meaning]) => <span key={v}><Mono>{v}</Mono> {meaning}； </span>)}</Hint>
              )}
            </Section>
            <Section title="为什么提出" note={selected.decision === true ? <Chip size="sm" variant="soft" color="success">Agent 接受本轮</Chip> : selected.decision === false ? <Chip size="sm" variant="soft" color="danger">Agent 拒绝本轮</Chip> : undefined}>
              {selected.hypothesis ? <p className="m-0 text-xs">{selected.hypothesis}</p> : <Hint>这一轮没有记录假设文本。</Hint>}
              {selected.reason && <Hint>Agent 评价：{selected.reason}</Hint>}
            </Section>
            <Section title="单因子分析" note="沪深300 · 次日收益">
              {selected.analysis ? (
                <>
                  <MetricGrid items={[
                    { label: "IC 均值", value: <Signed value={selected.analysis.ic.mean} /> },
                    { label: "ICIR", value: selected.analysis.ic.ir == null ? "—" : selected.analysis.ic.ir.toFixed(2) },
                    { label: "IC > 0 天数占比", value: `${(selected.analysis.ic.positive_ratio * 100).toFixed(0)}%` },
                    { label: "Rank IC 均值", value: <Signed value={selected.analysis.rank_ic.mean} /> },
                    { label: "Rank ICIR", value: selected.analysis.rank_ic.ir == null ? "—" : selected.analysis.rank_ic.ir.toFixed(2) },
                    { label: "交易日 / 样本", value: `${selected.analysis.days} / ${selected.analysis.rows.toLocaleString()}` },
                  ]} />
                  <Hint>按月 Rank IC · 覆盖 {selected.analysis.coverage.start} → {selected.analysis.coverage.end}</Hint>
                  <IcBars monthly={selected.analysis.monthly} field="rank_ic" />
                </>
              ) : busyKey === key(selected) ? <Hint>分析中，约 10 秒…</Hint>
                : <div className="flex items-center gap-2"><Hint>尚未计算。</Hint><Btn onClick={() => analyze(selected)}>现在计算</Btn></div>}
            </Section>
            <Section title="所在轮次的 Qlib 评估" note="与同轮其他因子合并训练的结果"><MetricTable metrics={selected.metrics} /></Section>
            <Section title="factor.py" note={selected.code ? <Btn kind="text" onClick={() => download(`${selected.name}.py`, selected.code!)}>下载代码</Btn> : undefined}>
              {selected.code ? <CodeView code={selected.code} /> : <Hint>这个实验没有记录代码。</Hint>}
            </Section>
          </div>
        ) : <Hint>点因子名查看说明、单因子分析与代码。</Hint>
      ) : (
        basket.items.length ? (
          <div className="flex flex-col gap-3">
            <Section title="篮内信号" note={basketCoverage ? `回测可用区间 ${basketCoverage.start} → ${basketCoverage.end}${basketCoverage.missing ? `（${basketCoverage.missing} 个未分析，未计入）` : ""}` : "覆盖区间未知：先在中间栏计算指标"}>
              <DataTable label="篮内信号" head={[["信号"], ["来源"], ["IC", "end"], ["Rank IC", "end"], ["覆盖"], [""]]}
                rows={basket.items.map((f) => {
                  const a = library.get(key(f))?.analysis;
                  return {
                    key: key(f),
                    cells: [
                      <Mono key="n">{f.name}</Mono>,
                      <span key="s" className="text-[11px] text-muted">{shortName(f.trace)} · 第 {f.loop_id + 1} 轮</span>,
                      <Signed key="ic" value={a?.ic.mean} />,
                      <Signed key="ric" value={a?.rank_ic.mean} />,
                      <span key="c" className="whitespace-nowrap text-[11px] text-muted tabular-nums">{a ? `${a.coverage.start.slice(0, 7)} → ${a.coverage.end.slice(0, 7)}` : f.kind === "prediction" ? "模型测试期" : "未分析"}</span>,
                      <Btn key="x" kind="text" onClick={() => basket.toggle(f)}>移出</Btn>,
                    ],
                  };
                })} />
            </Section>
            <Section title="篮内相关性" note={`${basketFactors.length} 个因子${basket.items.length > basketFactors.length ? " · 模型预测不参与" : ""}`}>
              {basketFactors.length < 2 ? <Hint>至少两个因子才有相关性可看。</Hint>
                : correlationError ? <Hint>相关性计算失败：{correlationError}</Hint>
                : !correlation || !strongest ? <Hint>计算中…</Hint>
                : (
                  <>
                    <p className={`m-0 text-xs ${maxCorr >= 0.7 ? "text-danger" : ""}`}>
                      {maxCorr >= 0.7
                        ? `${strongest.a} 与 ${strongest.b} 相关 ${strongest.value.toFixed(2)}，基本是同一个信号，同时入选只是重复计权。`
                        : maxCorr >= 0.5
                          ? `最高相关 ${strongest.value.toFixed(2)}（${strongest.a} 与 ${strongest.b}），有部分重叠，仍可组合。`
                          : `最高相关 ${strongest.value.toFixed(2)}（${strongest.a} 与 ${strongest.b}），彼此互补。`}
                    </p>
                    <CorrelationMatrix data={correlation} />
                  </>
                )}
            </Section>
          </div>
        ) : <Hint>在中间栏勾选因子，这里看它们放在一起合不合适：覆盖区间、两两相关性。</Hint>
      )}
    >
      {error && <Note tone="bad" actions={<Btn kind="text" onClick={() => setError("")}>关闭</Btn>}>{error}</Note>}
      <Block title="因子" count={rows.length} note={statusLine} noteTone={maxCorr >= 0.7 ? "bad" : "ok"}>
        {rows.length ? (
          <Table label="因子库" columns={[{ label: "", width: 34 }, { label: "因子" }, { label: "轮", num: true, width: 44, optional: true }, { label: "判定", width: 56, optional: true }, { label: "IC", num: true, width: 82 }, { label: "Rank IC", num: true, width: 82 }, { label: "ICIR", num: true, width: 66, optional: true }, { label: "覆盖", width: 156, optional: true }]}
            rows={groups.flatMap((g) => [
              { key: `g:${g.trace}`, group: true, cells: [<span key="g">{shortName(g.trace)}<span className="mm-dim">{g.trace.split("/")[0]} · {g.items.length} 个因子</span></span>] },
              ...g.items.map((f) => ({
                key: key(f), selected: key(f) === selectedKey, onClick: () => select(f),
                cells: [
                  <input key="c" type="checkbox" className="mm-check" aria-label="加入组合" checked={basket.has(f)} onChange={() => check(f)} onClick={(e) => e.stopPropagation()} />,
                  <span key="n" className="mm-mono mm-name">{f.name}</span>,
                  <span key="r" className="mm-dim">{f.loop_id + 1}</span>,
                  decisionTag(f.decision),
                  <Num key="ic" value={f.analysis?.ic.mean} />,
                  <Num key="ric" value={f.analysis?.rank_ic.mean} />,
                  f.analysis?.ic.ir == null ? <span key="ir" className="mm-dim">—</span> : f.analysis.ic.ir.toFixed(2),
                  <span key="cov" className="mm-mono mm-dim">
                    {f.analysis ? `${f.analysis.coverage.start.slice(0, 7)} → ${f.analysis.coverage.end.slice(0, 7)}` : busyKey === key(f) ? "分析中…" : <Link onClick={(e) => { e.stopPropagation(); analyze(f); }}>计算指标</Link>}
                  </span>,
                ],
              })),
            ])} />
        ) : !loading ? <Empty>还没有带因子产物的研究轮次。先在「AI 研究」里跑一次因子研发。</Empty> : <Empty>加载中…</Empty>}
        {rows.length > 0 && !basket.items.length && (
          <details className="mm-details" style={{ marginTop: 12 }}>
            <summary>勾选进组合篮；点名字在右栏看描述、公式、单因子分析与代码。怎么挑因子？</summary>
            <p className="mm-p">{GUIDE}</p>
          </details>
        )}
      </Block>
      {basket.items.length > 0 && (
        <div className="mm-sticky mm-row">
          <Link onClick={showBasket}><span className="mm-name" style={{ color: "var(--mm-ink)" }}>组合篮 <span className="mm-count mm-mono mm-dim" style={{ fontWeight: 400 }}>{basket.items.length}</span></span></Link>
          <span className="mm-mono mm-dim" style={{ fontSize: 12, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{basket.items.map((f) => f.name).join(" · ")}</span>
          <Btn kind="text" onClick={basket.clear}>清空</Btn>
          <Btn kind="primary" onClick={() => navigate("/backtest")}>去组合回测 →</Btn>
        </div>
      )}
    </PageFrame>
  );
}
