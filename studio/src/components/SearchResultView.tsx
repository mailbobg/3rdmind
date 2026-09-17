import { useMemo } from "react";
import { Alert, Disclosure } from "@heroui/react";
import type { SearchResult, SearchStep, VariantMetrics } from "../api/studio";
import { Btn } from "./minimal";
import { Section } from "./Section";
import { CodeView, CurveOverlay, DataTable, Hint, MetricGrid, Mono, Signed, StatusChip, percent } from "./widgets";
import { t } from "../i18n";

const KIND: Record<SearchStep["kind"], string> = { single: t("单独"), start: t("起点"), add: t("加入"), drop: t("去掉") };
const fmt = (v?: number | null) => (typeof v === "number" ? v.toFixed(2) : "—");

/** The search path, the recommendation against "everything in", and the held-out validation. */
export function SearchResultView({ result, onAdopt }: { result: SearchResult; onAdopt?: (members: string[], weights: Record<string, number>) => void }) {
  const running = result.status === "queued" || result.status === "running";
  const rec = result.recommended_portfolio;
  const all = result.everything;
  const objective = result.objective === "total_return" ? t("总收益") : t("夏普");
  const curves = useMemo(() => {
    const out: { name: string; points: [string, number][]; bold?: boolean; dashed?: boolean }[] = [];
    if (rec?.validation.equity) out.push({ name: t("推荐组合"), points: rec.validation.equity, bold: true });
    if (all?.validation?.equity) out.push({ name: t("全部放进去"), points: all.validation.equity, dashed: true });
    return out;
  }, [rec, all]);
  const verdict = useMemo(() => {
    if (!rec || !all) return [];
    const lines: { ok: boolean; text: string }[] = [];
    const same = rec.members.length === (result.candidates?.length ?? 0);
    if (same) lines.push({ ok: true, text: t("搜索没有剔除任何候选：全部放进去就是搜索区间上最好的组合。") });
    else lines.push({ ok: true, text: t("{0} 个候选里留下 {1} 个：{2}。", [result.candidates?.length ?? 0, rec.members.length, rec.members.join("、")]) });
    const rv = rec.validation.total_return, av = all.validation?.total_return;
    if (typeof rv === "number" && typeof av === "number") {
      lines.push(rv >= av
        ? { ok: true, text: t("验证区间上推荐组合 {0}，全部放进去 {1}：挑选在没参与搜索的时间段上仍然成立。", [percent(rv, 1), percent(av, 1)]) }
        : { ok: false, text: t("验证区间上推荐组合 {0}，不如全部放进去的 {1}：搜索区间上的优势没有延续，很可能是对那段历史的过拟合，别直接采用。", [percent(rv, 1), percent(av, 1)]) });
    }
    if (typeof rv === "number" && typeof rec.validation.benchmark_return === "number") {
      lines.push(rv >= rec.validation.benchmark_return
        ? { ok: true, text: t("验证区间跑赢基准 {0}。", [percent(rv - rec.validation.benchmark_return, 1)]) }
        : { ok: false, text: t("验证区间跑输基准 {0}：这段时间不如持有指数。", [percent(rec.validation.benchmark_return - rv, 1)]) });
    }
    return lines;
  }, [rec, all, result.candidates]);

  const metricsRow = (m?: VariantMetrics) => m && !m.error ? t("{0} · 夏普 {1} · 回撤 {2}", [percent(m.total_return, 1), fmt(m.sharpe), percent(m.max_drawdown, 1)]) : m?.error ? t("无法回测：{0}", [m.error]) : "—";

  return (
    <div className="flex flex-col gap-3">
      <Section title={t("组合搜索 {0}", [result.id.slice(0, 8)])} note={<StatusChip status={result.status === "completed" ? t("已完成") : result.status === "failed" ? t("失败") : t("运行中")} />}>
        <Hint>
          {t("目标")} {objective} · {result.prefilter?.enabled && (result.prefilter.requested?.length ?? 0) > result.config.factors.length
            ? t("候选 {0} 个，预筛后 {1} 个", [result.prefilter.requested?.length ?? 0, result.config.factors.length])
            : t("候选 {0} 个", [result.config.factors.length])} · {result.config.start} → {result.config.end} · {result.config.market}
          {result.windows && <> · {t("搜索区间")} {result.windows.search[0]} → {result.windows.search[1]} · {t("验证区间")} {result.windows.validation[0]} → {result.windows.validation[1]}</>}
        </Hint>
        {running && <Hint>搜索中{result.done != null && result.total ? t(" {0}/{1} 次回测", [result.done, result.total]) : ""}…路径会随进度出现在下面。</Hint>}
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
              { label: t("推荐组合 · 搜索区间"), value: metricsRow(rec.search) },
              { label: t("推荐组合 · 验证区间"), value: metricsRow(rec.validation), hint: t("没参与挑选的时间段，看结论是否成立") },
              { label: t("全部放进去 · 搜索区间"), value: metricsRow(all?.search) },
              { label: t("全部放进去 · 验证区间"), value: metricsRow(all?.validation) },
            ]} />
            <div className="flex flex-wrap items-center gap-2">
              {rec.members.map((m) => <span key={m} className="flex items-center gap-1 text-xs"><Mono>{m}</Mono><span className="text-muted">×{rec.weights?.[m] ?? 1}</span></span>)}
              {onAdopt && <Btn kind="primary" onClick={() => onAdopt(rec.members, rec.weights || {})}>{t("把推荐组合放进信号篮")}</Btn>}
            </div>
            {curves.length > 0 && <><CurveOverlay series={curves} height={260} /><Hint>{t("验证区间的净值：粗线是推荐组合，虚线是全部放进去。")}</Hint></>}
          </>
        )}
      </Section>
      {result.prefilter?.enabled && ((result.prefilter.excluded?.length ?? 0) > 0 || (result.prefilter.flipped?.length ?? 0) > 0) && (
        <Section title={t("预筛")} note={t("回测前的不花钱检查：只看单因子指标和两两相关，没跑回测")}>
          {(result.prefilter.excluded?.length ?? 0) > 0 && (
            <DataTable label={t("预筛淘汰")} head={[[t("因子")], [t("原因")]]}
              rows={result.prefilter.excluded.map((e) => ({
                key: e.name,
                cells: [
                  <span key="n" className="mm-mono mm-name">{e.name}</span>,
                  <span key="r" className="text-[11px]">{e.reason}</span>,
                ],
              }))} />
          )}
          {(result.prefilter.flipped?.length ?? 0) > 0 && (
            <Hint>{result.prefilter.flipped.map((f) => `${f.name}：${f.reason}`).join("；")}</Hint>
          )}
          <Hint>{t("这是软淘汰：这次没进搜索不代表以后没用，换一批队友或换个窗口可以再试。")}</Hint>
        </Section>
      )}
      {result.steps && result.steps.length > 0 && (
        <Section title={t("搜索路径")} note={t("{0} 次回测 · 搜索区间", [result.steps.length])}>
          <DataTable label={t("搜索路径")} head={[["#"], [t("动作")], [t("组合")], [t("收益"), "end"], [t("夏普"), "end"], [t("回撤"), "end"], [t("结果")]]}
            rows={result.steps.map((st) => ({
              key: String(st.step),
              cells: [
                <span key="i" className="tabular-nums text-muted">{st.step}</span>,
                <span key="k" className="text-xs">{KIND[st.kind]}{st.tried && st.kind !== "single" ? ` ${st.tried}` : ""}</span>,
                <span key="m" className="text-[11px]"><Mono>{st.members.join(" + ")}</Mono></span>,
                st.error ? <span key="r" className="text-[11px] text-muted" title={st.error}>—</span> : <Signed key="r" value={st.total_return} format={(v) => percent(v, 1)} />,
                <span key="s" className="tabular-nums">{fmt(st.sharpe)}</span>,
                <span key="d" className="tabular-nums">{percent(st.max_drawdown, 1)}</span>,
                <span key="a" className={`text-[11px] ${st.accepted === true ? "text-success" : st.accepted === false ? "text-muted" : ""}`}>{st.kind === "single" ? "" : st.accepted === true ? t("采纳") : st.accepted === false ? t("放弃") : ""}</span>,
              ],
            }))} />
          <Hint>{t("先每个候选单独跑，取{0}最高的做起点；然后每轮把剩下的逐个加进去，采纳提升最大的，直到再加也不涨；最后逐个试着去掉，去掉后更好的就剔除。全部在搜索区间上判断。", [objective])}</Hint>
        </Section>
      )}
      {result.log && (
        <Section title={t("执行日志")}>
          <Disclosure>
            <Disclosure.Heading><Disclosure.Trigger className="text-xs">{t("展开日志")}<Disclosure.Indicator /></Disclosure.Trigger></Disclosure.Heading>
            <Disclosure.Content><CodeView code={result.log} /></Disclosure.Content>
          </Disclosure>
        </Section>
      )}
    </div>
  );
}
