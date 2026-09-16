import { useMemo } from "react";
import { Alert, Disclosure } from "@heroui/react";
import type { SearchResult, SearchStep, VariantMetrics } from "../api/studio";
import { Btn } from "./minimal";
import { Section } from "./Section";
import { CodeView, CurveOverlay, DataTable, Hint, MetricGrid, Mono, Signed, StatusChip, percent } from "./widgets";

const KIND: Record<SearchStep["kind"], string> = { single: "单独", start: "起点", add: "加入", drop: "去掉" };
const fmt = (v?: number | null) => (typeof v === "number" ? v.toFixed(2) : "—");

/** The search path, the recommendation against "everything in", and the held-out validation. */
export function SearchResultView({ result, onAdopt }: { result: SearchResult; onAdopt?: (members: string[], weights: Record<string, number>) => void }) {
  const running = result.status === "queued" || result.status === "running";
  const rec = result.recommended_portfolio;
  const all = result.everything;
  const objective = result.objective === "total_return" ? "总收益" : "夏普";
  const curves = useMemo(() => {
    const out: { name: string; points: [string, number][]; bold?: boolean; dashed?: boolean }[] = [];
    if (rec?.validation.equity) out.push({ name: "推荐组合", points: rec.validation.equity, bold: true });
    if (all?.validation?.equity) out.push({ name: "全部放进去", points: all.validation.equity, dashed: true });
    return out;
  }, [rec, all]);
  const verdict = useMemo(() => {
    if (!rec || !all) return [];
    const lines: { ok: boolean; text: string }[] = [];
    const same = rec.members.length === (result.candidates?.length ?? 0);
    if (same) lines.push({ ok: true, text: "搜索没有剔除任何候选：全部放进去就是搜索区间上最好的组合。" });
    else lines.push({ ok: true, text: `${result.candidates?.length ?? 0} 个候选里留下 ${rec.members.length} 个：${rec.members.join("、")}。` });
    const rv = rec.validation.total_return, av = all.validation?.total_return;
    if (typeof rv === "number" && typeof av === "number") {
      lines.push(rv >= av
        ? { ok: true, text: `验证区间上推荐组合 ${percent(rv, 1)}，全部放进去 ${percent(av, 1)}：挑选在没参与搜索的时间段上仍然成立。` }
        : { ok: false, text: `验证区间上推荐组合 ${percent(rv, 1)}，不如全部放进去的 ${percent(av, 1)}：搜索区间上的优势没有延续，很可能是对那段历史的过拟合，别直接采用。` });
    }
    if (typeof rv === "number" && typeof rec.validation.benchmark_return === "number") {
      lines.push(rv >= rec.validation.benchmark_return
        ? { ok: true, text: `验证区间跑赢基准 ${percent(rv - rec.validation.benchmark_return, 1)}。` }
        : { ok: false, text: `验证区间跑输基准 ${percent(rec.validation.benchmark_return - rv, 1)}：这段时间不如持有指数。` });
    }
    return lines;
  }, [rec, all, result.candidates]);

  const metricsRow = (m?: VariantMetrics) => m && !m.error ? `${percent(m.total_return, 1)} · 夏普 ${fmt(m.sharpe)} · 回撤 ${percent(m.max_drawdown, 1)}` : m?.error ? `无法回测：${m.error}` : "—";

  return (
    <div className="flex flex-col gap-3">
      <Section title={`组合搜索 ${result.id.slice(0, 8)}`} note={<StatusChip status={result.status === "completed" ? "已完成" : result.status === "failed" ? "失败" : "运行中"} />}>
        <Hint>
          目标 {objective} · 候选 {result.config.factors.length} 个 · {result.config.start} → {result.config.end} · {result.config.market}
          {result.windows && <> · 搜索区间 {result.windows.search[0]} → {result.windows.search[1]} · 验证区间 {result.windows.validation[0]} → {result.windows.validation[1]}</>}
        </Hint>
        {running && <Hint>搜索中{result.done != null && result.total ? ` ${result.done}/${result.total} 次回测` : ""}…路径会随进度出现在下面。</Hint>}
        {result.error && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{result.error}</Alert.Title></Alert.Content></Alert>}
        {rec && (
          <>
            <div className="flex flex-col gap-1">
              {verdict.map((line) => (
                <Alert key={line.text} status={line.ok ? "success" : "danger"} className="py-1.5">
                  <Alert.Indicator /><Alert.Content><Alert.Title className="text-xs font-normal">{line.text}</Alert.Title></Alert.Content>
                </Alert>
              ))}
            </div>
            <MetricGrid columns={2} items={[
              { label: "推荐组合 · 搜索区间", value: metricsRow(rec.search) },
              { label: "推荐组合 · 验证区间", value: metricsRow(rec.validation), hint: "没参与挑选的时间段，看结论是否成立" },
              { label: "全部放进去 · 搜索区间", value: metricsRow(all?.search) },
              { label: "全部放进去 · 验证区间", value: metricsRow(all?.validation) },
            ]} />
            <div className="flex flex-wrap items-center gap-2">
              {rec.members.map((m) => <span key={m} className="flex items-center gap-1 text-xs"><Mono>{m}</Mono><span className="text-muted">×{rec.weights?.[m] ?? 1}</span></span>)}
              {onAdopt && <Btn kind="primary" onClick={() => onAdopt(rec.members, rec.weights || {})}>把推荐组合放进信号篮</Btn>}
            </div>
            {curves.length > 0 && <><CurveOverlay series={curves} height={260} /><Hint>验证区间的净值：粗线是推荐组合，虚线是全部放进去。</Hint></>}
          </>
        )}
      </Section>
      {result.steps && result.steps.length > 0 && (
        <Section title="搜索路径" note={`${result.steps.length} 次回测 · 搜索区间`}>
          <DataTable label="搜索路径" head={[["#"], ["动作"], ["组合"], ["收益", "end"], ["夏普", "end"], ["回撤", "end"], ["结果"]]}
            rows={result.steps.map((st) => ({
              key: String(st.step),
              cells: [
                <span key="i" className="tabular-nums text-muted">{st.step}</span>,
                <span key="k" className="text-xs">{KIND[st.kind]}{st.tried && st.kind !== "single" ? ` ${st.tried}` : ""}</span>,
                <span key="m" className="text-[11px]"><Mono>{st.members.join(" + ")}</Mono></span>,
                st.error ? <span key="r" className="text-[11px] text-muted" title={st.error}>—</span> : <Signed key="r" value={st.total_return} format={(v) => percent(v, 1)} />,
                <span key="s" className="tabular-nums">{fmt(st.sharpe)}</span>,
                <span key="d" className="tabular-nums">{percent(st.max_drawdown, 1)}</span>,
                <span key="a" className={`text-[11px] ${st.accepted === true ? "text-success" : st.accepted === false ? "text-muted" : ""}`}>{st.kind === "single" ? "" : st.accepted === true ? "采纳" : st.accepted === false ? "放弃" : ""}</span>,
              ],
            }))} />
          <Hint>先每个候选单独跑，取{objective}最高的做起点；然后每轮把剩下的逐个加进去，采纳提升最大的，直到再加也不涨；最后逐个试着去掉，去掉后更好的就剔除。全部在搜索区间上判断。</Hint>
        </Section>
      )}
      {result.log && (
        <Section title="执行日志">
          <Disclosure>
            <Disclosure.Heading><Disclosure.Trigger className="text-xs">展开日志<Disclosure.Indicator /></Disclosure.Trigger></Disclosure.Heading>
            <Disclosure.Content><CodeView code={result.log} /></Disclosure.Content>
          </Disclosure>
        </Section>
      )}
    </div>
  );
}
