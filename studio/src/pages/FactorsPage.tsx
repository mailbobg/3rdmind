import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Chip, Input, Tooltip } from "@heroui/react";
import * as studio from "../api/studio";
import type { CorrelationMatrix as Corr, FactorRef, LibraryFactor } from "../api/studio";
import { basketKey as key } from "../hooks/useFactorBasket";
import { download, errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { Panel } from "../components/Panel";
import { Section } from "../components/Section";
import { ListRow, Stat, TabBar } from "../components/fields";
import { CodeView, CorrelationMatrix, Formula, Hint, IcBars, MetricGrid, MetricTable, Mono, Signed } from "../components/widgets";

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
  const select = (f: LibraryFactor) => { setSelectedKey(key(f)); layout.openResults(); if (!f.analysis && busyKey !== key(f)) analyze(f); };

  const basketFactors = useMemo<FactorRef[]>(() => basket.items.filter((f) => (f.kind || "factor") === "factor").map((f) => ({ trace: f.trace, loop_id: f.loop_id, name: f.name })), [basket.items]);
  const [correlation, setCorrelation] = useState<Corr | null>(null);
  const [correlationError, setCorrelationError] = useState("");
  useEffect(() => {
    setCorrelation(null); setCorrelationError("");
    if (basketFactors.length < 2) return;
    const t = setTimeout(() => studio.factorCorrelation(basketFactors).then(setCorrelation).catch((e) => setCorrelationError(errorText(e))), 400);
    return () => clearTimeout(t);
  }, [basketFactors]);
  const maxCorr = useMemo(() => {
    if (!correlation) return 0;
    let m = 0;
    correlation.matrix.forEach((row, i) => row.forEach((v, j) => { if (i !== j) m = Math.max(m, Math.abs(v)); }));
    return m;
  }, [correlation]);
  const statusLine = basketFactors.length >= 2
    ? (correlation ? `篮内最高相关 ${maxCorr.toFixed(2)}${maxCorr >= 0.7 ? "（有因子重复）" : ""}` : correlationError ? "相关性计算失败" : "计算相关性…") : undefined;
  const decisionChip = (d: boolean | null) => d === true ? <Chip size="sm" variant="soft" color="success">接受</Chip> : d === false ? <Chip size="sm" variant="soft" color="danger">拒绝</Chip> : <Chip size="sm" variant="soft">—</Chip>;

  return (
    <PageFrame
      title="因子库"
      description={`${all.length} 个因子来自 ${new Set(all.map((f) => f.trace)).size} 个实验 · 单因子 IC 由后端计算并缓存 · 篮内相关性实时计算`}
      tag={`篮内 ${basket.items.length}`}
      tabs={<TabBar label="筛选" value={filter} onChange={setFilter} items={[{ key: "all", label: "全部因子" }, { key: "accepted", label: "agent 接受的轮次" }]} />}
      actions={
        <>
          <Input aria-label="搜索因子" placeholder="搜索因子或实验" value={query} onChange={(e) => setQuery(e.target.value)} className="w-44" />
          <Button size="sm" variant="secondary" isDisabled={analyzing || !pending.length} onPress={analyzeAll}>{analyzing ? `分析中 ${analyzed}/${pending.length}…` : `分析全部（${pending.length}）`}</Button>
          <Button size="sm" variant="secondary" onPress={load}>刷新</Button>
        </>
      }
      resultsTitle={selected ? selected.name : "因子详情"}
      resultsActions={selected ? <Button size="sm" variant={basket.has(selected) ? "secondary" : "primary"} onPress={() => basket.toggle(selected)}>{basket.has(selected) ? "移出组合" : "加入组合"}</Button> : undefined}
      results={
        selected ? (
          <div className="flex flex-col gap-3">
            <Section title="这是什么" note={`${selected.trace} · 第 ${selected.loop_id + 1} 轮`}>
              <p className="m-0 text-xs">{selected.description || "agent 没有记录描述。"}</p>
              {selected.formulation && <Formula source={selected.formulation} />}
              {selected.variables && Object.keys(selected.variables).length > 0 && (
                <Hint>变量：{Object.entries(selected.variables).map(([v, meaning]) => <span key={v}><Mono>{v}</Mono> {meaning}； </span>)}</Hint>
              )}
            </Section>
            <Section title="为什么提出" note={selected.decision === true ? <Chip size="sm" variant="soft" color="success">agent 接受本轮</Chip> : selected.decision === false ? <Chip size="sm" variant="soft" color="danger">agent 拒绝本轮</Chip> : undefined}>
              {selected.hypothesis ? <p className="m-0 text-xs">{selected.hypothesis}</p> : <Hint>这一轮没有记录假设文本。</Hint>}
              {selected.reason && <Hint>agent 评价：{selected.reason}</Hint>}
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
                : <div className="flex items-center gap-2"><Hint>尚未计算。</Hint><Button size="sm" variant="secondary" onPress={() => analyze(selected)}>现在计算</Button></div>}
            </Section>
            {correlation && basketFactors.length >= 2 && <Section title="篮内相关性" note={`${basketFactors.length} 个因子`}><CorrelationMatrix data={correlation} /></Section>}
            <Section title="所在轮次的 Qlib 评估" note="与同轮其他因子合并训练的结果"><MetricTable metrics={selected.metrics} /></Section>
            <Section title="factor.py" note={selected.code ? <Button size="sm" variant="ghost" onPress={() => download(`${selected.name}.py`, selected.code!)}>下载代码</Button> : undefined}>
              {selected.code ? <CodeView code={selected.code} /> : <Hint>这个实验没有记录代码。</Hint>}
            </Section>
          </div>
        ) : correlation && basketFactors.length >= 2 ? (
          <Section title="篮内相关性" note={`${basketFactors.length} 个因子`}><CorrelationMatrix data={correlation} /></Section>
        ) : <Hint>点一行查看因子说明、单因子分析与代码。</Hint>
      }
    >
      {error && (
        <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{error}</Alert.Title></Alert.Content>
          <Button size="sm" variant="ghost" onPress={() => setError("")}>关闭</Button></Alert>
      )}
      <Panel grow flush
        title={<>因子 <span className="font-normal text-muted">{rows.length} 个</span></>}
        status={statusLine} statusTone={maxCorr >= 0.7 ? "bad" : "ok"}
        footer={basket.items.length ? (
          <div className="flex w-full flex-wrap items-center gap-2">
            <span className="font-semibold text-foreground">组合篮 · {basket.items.length}</span>
            {basket.items.map((f) => <Chip key={key(f)} size="sm" variant="soft">{f.name}</Chip>)}
            <span className="ml-auto flex gap-2">
              <Button size="sm" variant="ghost" onPress={basket.clear}>清空</Button>
              <Button size="sm" onPress={() => navigate("/backtest")}>去组合回测 →</Button>
            </span>
          </div>
        ) : (
          <div className="flex w-full items-center gap-2">
            <Tooltip delay={200}><Tooltip.Trigger><button className="text-accent underline">怎么挑因子</button></Tooltip.Trigger><Tooltip.Content className="max-w-md"><Tooltip.Arrow />{GUIDE}</Tooltip.Content></Tooltip>
            <span>勾选进组合篮；点名字在右栏看描述、公式、单因子分析与代码。</span>
          </div>
        )}>
        {rows.length ? groups.map((g) => (
          <div key={g.trace}>
            <div className="flex items-center justify-between border-b border-border bg-surface-secondary px-3 py-1.5 text-[12px]">
              <span className="font-medium">{shortName(g.trace)}</span>
              <span className="text-muted">{g.trace.split("/")[0]} · {g.items.length} 个因子</span>
            </div>
            {g.items.map((f) => (
              <ListRow key={key(f)} selected={key(f) === selectedKey} onSelect={() => select(f)}
                leading={<input type="checkbox" aria-label="加入组合" checked={basket.has(f)} onChange={() => basket.toggle(f)} className="size-4 cursor-pointer accent-[var(--accent)]" />}
                trailing={<>
                  <span className="w-12">{decisionChip(f.decision)}</span>
                  <Stat label="IC">{f.analysis ? <Signed value={f.analysis.ic.mean} /> : "—"}</Stat>
                  <Stat label="Rank IC">{f.analysis ? <Signed value={f.analysis.rank_ic.mean} /> : "—"}</Stat>
                  <Stat label="ICIR" width={56}>{f.analysis?.ic.ir == null ? "—" : f.analysis.ic.ir.toFixed(2)}</Stat>
                  <span className="w-[150px] text-right text-[12px] text-muted">
                    {f.analysis ? `${f.analysis.coverage.start.slice(0, 7)} → ${f.analysis.coverage.end.slice(0, 7)}` : busyKey === key(f) ? "分析中…" : <button className="text-accent underline" onClick={(e) => { e.stopPropagation(); analyze(f); }}>计算指标</button>}
                  </span>
                </>}>
                <div className="flex items-center gap-2">
                  <Mono>{f.name}</Mono>
                  <span className="text-[12px] text-muted">第 {f.loop_id + 1} 轮</span>
                </div>
              </ListRow>
            ))}
          </div>
        )) : !loading ? <div className="p-6 text-center text-xs text-muted">还没有带因子产物的研究轮次。先在「AI 研究」里跑一次因子研发。</div> : null}
      </Panel>
    </PageFrame>
  );
}
