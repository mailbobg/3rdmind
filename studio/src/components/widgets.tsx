import { useEffect, useMemo, useRef, type ReactNode } from "react";
import * as echarts from "echarts";
import katex from "katex";
import { Chip, Table, Tooltip } from "@heroui/react";
import type { BacktestRow, CorrelationMatrix as Corr } from "../api/studio";

export const percent = (v?: number | null, digits = 2) => (typeof v === "number" && Number.isFinite(v) ? (v * 100).toFixed(digits) + "%" : "—");
export const fixed = (v?: number | null, digits = 4) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—");
export const money = (v?: number | null) =>
  typeof v === "number" && Number.isFinite(v) ? "¥" + v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";

/** Signed number in green/red; neutral when not a number. */
export function Signed({ value, format = fixed }: { value?: number | null; format?: (v?: number | null) => string }) {
  const cls = typeof value !== "number" ? "text-muted" : value >= 0 ? "text-success" : "text-danger";
  return <span className={`tabular-nums ${cls}`}>{format(value)}</span>;
}

export function Mono({ children }: { children: ReactNode }) {
  return <code className="rounded bg-surface-secondary px-1 py-px font-mono text-[11.5px]">{children}</code>;
}

/** Key/value spec sheet; the hint shows as a tooltip on the label. */
/** Labelled values in a grid: `columns` is the most per row; cells wrap to fewer columns when the column is narrow. */
export function MetricGrid({ items, columns = 3 }: { items: { label: string; value: ReactNode; hint?: string }[]; columns?: number }) {
  const min = columns >= 3 ? 150 : 170;
  return (
    <dl className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(max(min(${min}px, 100%), calc(${(100 / columns).toFixed(3)}% - 6px)), 1fr))` }}>
      {items.map((m) => (
        <div key={m.label} className="flex items-center justify-between gap-2 rounded-lg border border-border px-2.5 py-1.5">
          {m.hint ? (
            <Tooltip delay={200}>
              <Tooltip.Trigger><dt className="cursor-help text-[11px] text-muted underline decoration-dotted underline-offset-2">{m.label}</dt></Tooltip.Trigger>
              <Tooltip.Content><Tooltip.Arrow />{m.hint}</Tooltip.Content>
            </Tooltip>
          ) : <dt className="text-[11px] text-muted">{m.label}</dt>}
          <dd className="m-0 text-[13px] font-semibold tabular-nums text-foreground">{m.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Native Qlib metrics as a two-column table, preferred keys first. */
const PREFERRED = ["IC", "ICIR", "Rank IC", "Rank ICIR", "1day.excess_return_with_cost.annualized_return",
  "1day.excess_return_with_cost.information_ratio", "1day.excess_return_with_cost.max_drawdown"];
export function MetricTable({ metrics }: { metrics: Record<string, number> }) {
  const rows = useMemo(() => {
    const head = PREFERRED.filter((k) => k in metrics).map((k) => [k, metrics[k]] as const);
    const rest = Object.entries(metrics).filter(([k]) => !PREFERRED.includes(k));
    return [...head, ...rest];
  }, [metrics]);
  return (
    <DataTable label="Qlib 指标" head={[["指标"], ["值", "end"]]}
      rows={rows.map(([k, v]) => ({ key: k, cells: [<Mono key="k">{k}</Mono>, <span key="v" className="tabular-nums">{Number.isFinite(v) ? Number(v.toPrecision(5)).toString() : "—"}</span>] }))} />
  );
}

/** Thin wrapper over HeroUI's Table for the many small dense tables in this app. */
export function DataTable({ label, head, rows, minWidth }: { label: string; head: [string, ("start" | "end")?][]; rows: { key: string; cells: ReactNode[]; onPress?: () => void; selected?: boolean }[]; minWidth?: number }) {
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content aria-label={label} style={minWidth ? { minWidth } : undefined}>
          <Table.Header>
            {head.map(([h, align], i) => <Table.Column key={i} isRowHeader={i === 0} className={align === "end" ? "text-right" : ""}>{h}</Table.Column>)}
          </Table.Header>
          <Table.Body>
            {rows.map((r) => (
              <Table.Row key={r.key} onAction={r.onPress} className={`${r.onPress ? "cursor-pointer" : ""} ${r.selected ? "bg-accent/10" : ""}`}>
                {r.cells.map((c, i) => <Table.Cell key={i} className={head[i]?.[1] === "end" ? "text-right" : ""}>{c}</Table.Cell>)}
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
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
  return <div ref={host} role="img" aria-label="策略净值、基准净值与回撤" className="h-[340px] w-full" />;
}

/** Monthly IC bars around a zero line. */
export function IcBars({ monthly, field }: { monthly: { month: string; ic: number | null; rank_ic: number | null }[]; field: "ic" | "rank_ic" }) {
  const scale = Math.max(0.02, ...monthly.map((m) => Math.abs(m[field] ?? 0)));
  return (
    <div>
      <div role="img" aria-label="按月 IC" className="flex h-[90px] gap-0.5 border-y border-border"
        style={{ background: "linear-gradient(to bottom, transparent 50%, var(--border) 50%, var(--border) calc(50% + 1px), transparent calc(50% + 1px))" }}>
        {monthly.map((m) => {
          const v = m[field];
          const h = v == null ? 0 : (Math.abs(v) / scale) * 50;
          return (
            <div key={m.month} title={`${m.month}：${v == null ? "—" : v.toFixed(4)}`} className="relative min-w-[3px] flex-1">
              <div className={`absolute inset-x-0 rounded-[1px] ${v == null || v >= 0 ? "bg-success" : "bg-danger"}`} style={{ height: `${h}%`, ...(v == null || v >= 0 ? { bottom: "50%" } : { top: "50%" }) }} />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-muted"><span>{monthly[0]?.month}</span><span>{monthly[monthly.length - 1]?.month}</span></div>
    </div>
  );
}

/** Pairwise Spearman correlation heat-matrix. */
export function CorrelationMatrix({ data }: { data: Corr }) {
  const cell = (v: number, diagonal: boolean) => {
    if (diagonal) return { color: "var(--muted)" };
    const s = Math.min(1, Math.abs(v));
    return { background: `rgba(${v >= 0 ? "23,103,78" : "178,72,58"}, ${0.08 + s * 0.4})`, fontWeight: s >= 0.7 ? 600 : 400 };
  };
  return (
    <div className="flex flex-col gap-1.5">
      <table className="w-full border-collapse text-xs">
        <thead><tr><th></th>{data.names.map((n) => <th key={n} className="px-2 py-1 text-right font-medium"><Mono>{n}</Mono></th>)}</tr></thead>
        <tbody>
          {data.matrix.map((row, i) => (
            <tr key={data.names[i]}>
              <th className="px-2 py-1 text-left font-medium"><Mono>{data.names[i]}</Mono></th>
              {row.map((v, j) => <td key={j} className="px-2 py-1 text-right tabular-nums" style={cell(v, i === j)}>{v.toFixed(2)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="m-0 text-[11px] text-muted">{data.days} 个交易日的截面 Spearman 相关系数均值。|ρ| ≥ 0.7 的两个因子基本是同一个信号，同时入选只是重复计权。</p>
    </div>
  );
}

/** LaTeX rendered with KaTeX; falls back to the raw text when it does not parse. */
export function Formula({ source }: { source: string }) {
  const html = useMemo(() => {
    try { return katex.renderToString(source, { displayMode: true, throwOnError: true, strict: "ignore" }); }
    catch { return `<code>${source.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</code>`; }
  }, [source]);
  return <div className="overflow-x-auto rounded-lg bg-surface-secondary px-2.5 py-1 text-[13px]" dangerouslySetInnerHTML={{ __html: html }} />;
}

export function CodeView({ code, maxHeight = 480 }: { code: string; maxHeight?: number }) {
  return <pre className="m-0 overflow-auto rounded-lg border border-border bg-surface-secondary p-2.5 font-mono text-[12px] leading-relaxed" style={{ maxHeight }}><code>{code}</code></pre>;
}

export function StatusChip({ status }: { status: string }) {
  const color = status === "已完成" || status === "接受" || status === "completed" ? "success"
    : status === "执行失败" || status === "拒绝" || status === "failed" ? "danger"
    : status === "运行中" || status === "启动中" || status === "running" || status === "queued" || status === "加载中" ? "warning" : "default";
  return <Chip size="sm" color={color} variant="soft">{status}</Chip>;
}

export function Hint({ children }: { children: ReactNode }) {
  return <p className="m-0 text-[11px] text-muted">{children}</p>;
}
