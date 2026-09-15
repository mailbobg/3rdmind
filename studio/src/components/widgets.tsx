import { useEffect, useMemo, useRef, type ReactNode } from "react";
import * as echarts from "echarts";
import katex from "katex";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { Code } from "@astryxdesign/core/Code";
import { CodeBlock } from "@astryxdesign/core/CodeBlock";
import { Badge } from "@astryxdesign/core/Badge";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import type { BacktestRow, CorrelationMatrix as Corr } from "../api/studio";

export const percent = (v?: number | null, digits = 2) => (typeof v === "number" && Number.isFinite(v) ? (v * 100).toFixed(digits) + "%" : "—");
export const fixed = (v?: number | null, digits = 4) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—");
export const money = (v?: number | null) =>
  typeof v === "number" && Number.isFinite(v) ? "¥" + v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";

/** Signed number in green/red; neutral when not a number. */
export function Signed({ value, format = fixed }: { value?: number | null; format?: (v?: number | null) => string }) {
  const color = typeof value !== "number" ? "var(--color-text-secondary)" : value >= 0 ? "var(--color-text-success)" : "var(--color-text-error)";
  return <Text hasTabularNumbers><span style={{ color }}>{format(value)}</span></Text>;
}

/** Key/value spec sheet; a hint shows as a tooltip on the label. */
export function MetricGrid({ items, columns = 3 }: { items: { label: string; value: ReactNode; hint?: string }[]; columns?: number }) {
  return (
    <MetadataList columns={columns} label={{ position: "top" }}>
      {items.map((m) => (
        <MetadataListItem key={m.label} label={m.label}>
          {m.hint ? <Tooltip content={m.hint}><span>{m.value}</span></Tooltip> : m.value}
        </MetadataListItem>
      ))}
    </MetadataList>
  );
}

/** Native Qlib metrics as a two-column table, preferred keys first. */
const PREFERRED = ["IC", "ICIR", "Rank IC", "Rank ICIR", "1day.excess_return_with_cost.annualized_return",
  "1day.excess_return_with_cost.information_ratio", "1day.excess_return_with_cost.max_drawdown"];
export function MetricTable({ metrics }: { metrics: Record<string, number> }) {
  const rows = useMemo(() => {
    const head = PREFERRED.filter((k) => k in metrics).map((k) => ({ key: k, value: metrics[k] }));
    const rest = Object.entries(metrics).filter(([k]) => !PREFERRED.includes(k)).map(([key, value]) => ({ key, value }));
    return [...head, ...rest];
  }, [metrics]);
  return (
    <Table
      data={rows}
      idKey="key"
      density="compact"
      columns={[
        { key: "key", header: "指标", width: proportional(1), renderCell: (r) => <Code>{r.key}</Code> },
        { key: "value", header: "值", width: pixel(120), align: "end", renderCell: (r) => <Text hasTabularNumbers>{Number.isFinite(r.value) ? Number(r.value.toPrecision(5)).toString() : "—"}</Text> },
      ]}
    />
  );
}

/** Equity, benchmark and drawdown lines (ECharts). */
export function EquityChart({ rows }: { rows: BacktestRow[] }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    chart.setOption({
      color: ["#14765a", "#989da5", "#c26052"],
      tooltip: { trigger: "axis" },
      legend: { top: 4, data: ["策略净值（扣费）", "基准净值", "回撤"] },
      grid: [{ left: 54, right: 18, top: 44, height: "49%" }, { left: 54, right: 18, top: "72%", height: "17%" }],
      xAxis: [{ type: "category", data: rows.map((r) => r.date), axisLabel: { show: false } }, { type: "category", gridIndex: 1, data: rows.map((r) => r.date) }],
      yAxis: [{ type: "value", scale: true, splitLine: { lineStyle: { color: "#edf0ec" } } }, { type: "value", gridIndex: 1, axisLabel: { formatter: "{value}%" } }],
      series: [
        { name: "策略净值（扣费）", type: "line", symbol: "none", data: rows.map((r) => r.equity) },
        { name: "基准净值", type: "line", symbol: "none", lineStyle: { type: "dashed" }, data: rows.map((r) => r.benchmark) },
        { name: "回撤", type: "line", symbol: "none", xAxisIndex: 1, yAxisIndex: 1, areaStyle: { opacity: 0.12 }, data: rows.map((r) => (r.drawdown == null ? null : +(r.drawdown * 100).toFixed(3))) },
      ],
    }, true);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [rows]);
  return <div ref={host} role="img" aria-label="策略净值、基准净值与回撤" style={{ height: 340, width: "100%" }} />;
}

/** Monthly IC bars around a zero line. */
export function IcBars({ monthly, field }: { monthly: { month: string; ic: number | null; rank_ic: number | null }[]; field: "ic" | "rank_ic" }) {
  const scale = Math.max(0.02, ...monthly.map((m) => Math.abs(m[field] ?? 0)));
  return (
    <div>
      <div role="img" aria-label="按月 IC" style={{ display: "flex", gap: 2, height: 90, borderTop: "1px solid var(--color-border)", borderBottom: "1px solid var(--color-border)",
        background: "linear-gradient(to bottom, transparent 50%, var(--color-border) 50%, var(--color-border) calc(50% + 1px), transparent calc(50% + 1px))" }}>
        {monthly.map((m) => {
          const v = m[field];
          const h = v == null ? 0 : (Math.abs(v) / scale) * 50;
          return (
            <div key={m.month} title={`${m.month}：${v == null ? "—" : v.toFixed(4)}`} style={{ flex: 1, position: "relative", minWidth: 3 }}>
              <div style={{ position: "absolute", left: 0, right: 0, height: `${h}%`, ...(v == null || v >= 0 ? { bottom: "50%" } : { top: "50%" }),
                background: v == null || v >= 0 ? "var(--color-text-success)" : "var(--color-text-error)", borderRadius: 1 }} />
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <Text type="supporting">{monthly[0]?.month}</Text><Text type="supporting">{monthly[monthly.length - 1]?.month}</Text>
      </div>
    </div>
  );
}

/** Pairwise Spearman correlation heat-matrix. */
export function CorrelationMatrix({ data }: { data: Corr }) {
  const cell = (v: number, diagonal: boolean) => {
    if (diagonal) return { color: "var(--color-text-secondary)" };
    const s = Math.min(1, Math.abs(v));
    return { background: `rgba(${v >= 0 ? "23,103,78" : "178,72,58"}, ${0.08 + s * 0.4})`, fontWeight: s >= 0.7 ? 600 : 400 };
  };
  return (
    <div>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
        <thead><tr><th></th>{data.names.map((n) => <th key={n} style={{ textAlign: "right", padding: "4px 8px" }}><Code>{n}</Code></th>)}</tr></thead>
        <tbody>
          {data.matrix.map((row, i) => (
            <tr key={data.names[i]}>
              <th style={{ textAlign: "left", padding: "4px 8px" }}><Code>{data.names[i]}</Code></th>
              {row.map((v, j) => <td key={j} style={{ textAlign: "right", padding: "4px 8px", fontVariantNumeric: "tabular-nums", ...cell(v, i === j) }}>{v.toFixed(2)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <Text type="supporting">{data.days} 个交易日的截面 Spearman 相关系数均值。|ρ| ≥ 0.7 的两个因子基本是同一个信号，同时入选只是重复计权。</Text>
    </div>
  );
}

/** LaTeX rendered with KaTeX; falls back to the raw text when it does not parse. */
export function Formula({ source }: { source: string }) {
  const html = useMemo(() => {
    try { return katex.renderToString(source, { displayMode: true, throwOnError: true, strict: "ignore" }); }
    catch { return `<code>${source.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</code>`; }
  }, [source]);
  return <div style={{ overflowX: "auto", fontSize: 13, padding: "4px 8px", background: "var(--color-background-muted)", borderRadius: "var(--radius-md)" }} dangerouslySetInnerHTML={{ __html: html }} />;
}

export function CodeView({ code, title, language = "python" }: { code: string; title?: string; language?: string }) {
  return <CodeBlock code={code} title={title} language={language} size="sm" width="100%" maxHeight={480} isWrapped={false} />;
}

export function StatusBadge({ status }: { status: string }) {
  const variant = status === "已完成" || status === "接受" || status === "completed" ? "success"
    : status === "执行失败" || status === "拒绝" || status === "failed" ? "error"
    : status === "运行中" || status === "启动中" || status === "running" || status === "queued" ? "warning" : "neutral";
  return <Badge variant={variant} label={status} />;
}
