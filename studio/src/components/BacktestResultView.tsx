import { useMemo, useState } from "react";
import { VStack, HStack } from "@astryxdesign/core/Stack";
import { Text } from "@astryxdesign/core/Text";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Table, pixel, proportional } from "@astryxdesign/core/Table";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Code } from "@astryxdesign/core/Code";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import type { BacktestResult, InstrumentSummary, Trade } from "../api/studio";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { Section } from "./Section";
import { CodeView, EquityChart, MetricGrid, Signed, StatusBadge, fixed, money, percent } from "./widgets";

export function BacktestResultView({ result }: { result: BacktestResult }) {
  const legacy = (result.config.loop_id === undefined || result.config.loop_id === null)
    && !result.config.factors.some((f) => f.loop_id !== undefined && f.loop_id !== null);
  const m = result.metrics;
  const excess = m ? m.total_return - m.benchmark_return : null;
  const verdict = useMemo(() => {
    if (!m) return [];
    const lines: string[] = [];
    const ex = m.total_return - m.benchmark_return;
    lines.push(ex >= 0 ? `跑赢基准 ${percent(ex)}。` : `跑输基准 ${percent(-ex)}：这段时间不如直接持有指数。`);
    if (typeof m.signal_ic === "number" && Math.abs(m.signal_ic) < 0.01 && typeof m.signal_rank_ic === "number" && Math.abs(m.signal_rank_ic) < 0.01)
      lines.push("评分对次日收益几乎没有预测力（|IC| < 0.01），收益主要来自运气或市场本身，回到因子库换信号比调参数更有用。");
    else if (typeof m.signal_ic === "number" && m.signal_ic < -0.01)
      lines.push("评分与次日收益负相关：信号方向反了，排名加权模式下把权重改成负数再试。");
    if (typeof m.sharpe === "number" && m.sharpe < 0.5 && ex >= 0) lines.push("夏普低于 0.5，收益波动大，不宜据此下结论。");
    if (result.model && result.model.best_iteration <= 20) lines.push(`LightGBM 在第 ${result.model.best_iteration} 轮就早停：训练集里学不到多少东西，信号本身偏弱。`);
    if ((m.days ?? 0) < 120) lines.push("交易日不足 120 天，样本太短。");
    return lines;
  }, [m, result.model]);
  const importance = useMemo(() => Object.entries(result.model?.feature_importance || {}).sort((a, b) => b[1] - a[1]), [result.model]);

  return (
    <VStack gap={3}>
      <Section title={`回测 ${result.id.slice(0, 8)}`} note={<StatusBadge status={backtestStatusLabel(result.status)} />}>
        <HStack gap={1} wrap="wrap">
          {legacy ? <Badge label={`旧格式回测 · ${result.config.factors.length} 个因子`} /> :
            result.config.factors.map((f) => <Badge key={`${f.trace}#${f.loop_id}#${f.name}`} variant="neutral" label={`${f.kind === "prediction" ? "模型 · " : ""}${f.name}${f.weight !== 1 ? ` ×${f.weight}` : ""}`} />)}
        </HStack>
        <Text type="supporting">
          {result.config.start} → {result.config.end} · {result.config.market} · 基准 {result.config.benchmark || "SH000300"} · topk {result.config.topk} / n_drop {result.config.n_drop}
          {" · "}{result.config.model?.method === "lgbm" ? `LightGBM（训练 ${result.config.model.train.join("→")}，验证 ${result.config.model.valid.join("→")}）` : "排名加权"}
        </Text>
        {result.error && <Banner status="error" title={result.error} collapsible={false} />}
        {m && (
          <>
            <MetricGrid items={[
              { label: "总收益（扣费）", value: <Signed value={m.total_return} format={(v) => percent(v)} />, hint: "回测区间内的净值变化，已扣手续费" },
              { label: "超额收益", value: <Signed value={excess} format={(v) => percent(v)} />, hint: "总收益减去基准指数同期收益" },
              { label: "基准收益", value: <Text hasTabularNumbers>{percent(m.benchmark_return)}</Text>, hint: "基准指数同期收益" },
              { label: "复利年化", value: <Signed value={m.annualized_return} format={(v) => percent(v)} />, hint: "按 252 个交易日折算" },
              { label: "夏普", value: <Text hasTabularNumbers>{typeof m.sharpe === "number" ? m.sharpe.toFixed(2) : "—"}</Text>, hint: "日收益均值 ÷ 波动 × √252；1 以上算不错，0.5 以下基本靠运气" },
              { label: "最大回撤", value: <Text hasTabularNumbers>{percent(m.max_drawdown)}</Text>, hint: "净值从高点回落的最大幅度" },
              { label: "信号 IC", value: <Signed value={m.signal_ic} />, hint: "最终评分与次日收益的日均相关；|IC| < 0.01 接近噪声" },
              { label: "信号 Rank IC", value: <Signed value={m.signal_rank_ic} />, hint: "评分排名与次日收益排名的日均相关" },
              { label: "交易日数", value: <Text hasTabularNumbers>{String(m.days ?? "—")}</Text>, hint: "样本太短（< 120 天）时以上指标都不可靠" },
            ]} />
            {verdict.map((line) => <Banner key={line} status={line.startsWith("跑赢") ? "success" : "info"} title={line} collapsible={false} />)}
            <EquityChart rows={result.rows || []} />
            <Text type="supporting">{result.method}</Text>
          </>
        )}
      </Section>
      {result.model && (
        <Section title="LightGBM 训练" note={`${result.model.train_rows.toLocaleString()} 训练样本 · ${result.model.valid_rows.toLocaleString()} 验证样本`}>
          <MetricGrid columns={2} items={[
            { label: "最佳迭代", value: String(result.model.best_iteration) },
            { label: "验证 L2", value: result.model.valid_l2.toFixed(4) },
          ]} />
          <VStack gap={1}>
            {importance.map(([name, gain]) => (
              <HStack key={name} gap={2} align="center">
                <Code>{name}</Code>
                <ProgressBar value={importance[0][1] ? (gain / importance[0][1]) * 100 : 0} label={`${name} 重要性`} isLabelHidden />
                <Text type="supporting" hasTabularNumbers>{gain.toFixed(1)}</Text>
              </HStack>
            ))}
          </VStack>
        </Section>
      )}
      {m && <TradeTables trades={result.trades || []} instruments={result.instruments || []} holdings={result.holdings} />}
      {result.log && (
        <Section title="执行日志">
          <Collapsible trigger={<Text type="supporting">展开日志</Text>} defaultIsOpen={false}><CodeView code={result.log} language="plaintext" /></Collapsible>
        </Section>
      )}
    </VStack>
  );
}

function TradeTables({ trades, instruments, holdings }: { trades: Trade[]; instruments: InstrumentSummary[]; holdings?: BacktestResult["holdings"] }) {
  const [instrumentQuery, setInstrumentQuery] = useState("");
  const [tradeQuery, setTradeQuery] = useState("");
  const [page, setPage] = useState(1);
  const PAGE = 20;
  const marketValue = holdings?.positions.reduce((s, p) => s + p.value, 0) ?? null;
  const totalCost = trades.reduce((s, t) => s + t.cost, 0);
  const filteredInstruments = useMemo(() => {
    const q = instrumentQuery.trim().toUpperCase();
    return q ? instruments.filter((r) => r.instrument.toUpperCase().includes(q)) : instruments;
  }, [instruments, instrumentQuery]);
  const filteredTrades = useMemo(() => {
    const q = tradeQuery.trim().toUpperCase();
    return q ? trades.filter((t) => t.instrument.toUpperCase().includes(q) || t.date.includes(q)) : trades;
  }, [trades, tradeQuery]);
  const paged = filteredTrades.slice((page - 1) * PAGE, page * PAGE).map((t, i) => ({ ...t, _id: `${t.date}-${t.instrument}-${i}` }));
  if (!instruments.length && !trades.length) return null;
  return (
    <>
      {instruments.length > 0 && (
        <Section title="持仓与标的收益" note={`${holdings?.positions.length ?? 0} 只在手 · 共 ${instruments.length} 只交易过`}>
          <MetricGrid columns={3} items={[
            { label: "持仓市值", value: money(marketValue) }, { label: "现金", value: money(holdings?.cash) }, { label: "手续费合计", value: money(totalCost) },
          ]} />
          <TextInput label="搜索标的" isLabelHidden placeholder="搜索合约代码" value={instrumentQuery} onChange={setInstrumentQuery} size="sm" />
          <Table
            data={filteredInstruments.slice(0, 50).map((r) => ({ ...r }))}
            idKey="instrument"
            density="compact"
            columns={[
              { key: "instrument", header: "标的", width: proportional(1), renderCell: (r) => <HStack gap={1} align="center"><Code>{r.instrument}</Code>{r.held && <Badge variant="success" label="持有" />}</HStack> },
              { key: "trades", header: "成交笔数", width: pixel(80), align: "end" },
              { key: "holding_value", header: "在手市值", width: pixel(120), align: "end", renderCell: (r) => <Text hasTabularNumbers>{r.holding_value ? money(r.holding_value) : "—"}</Text> },
              { key: "cost", header: "手续费", width: pixel(100), align: "end", renderCell: (r) => <Text hasTabularNumbers>{money(r.cost)}</Text> },
              { key: "pnl", header: "最终收益", width: pixel(120), align: "end", renderCell: (r) => <Signed value={r.pnl} format={money} /> },
            ]}
          />
          {filteredInstruments.length > 50 && <Text type="supporting">只显示前 50 只，用搜索缩小范围。</Text>}
        </Section>
      )}
      {trades.length > 0 && (
        <Section title="交易时间线" note={`共 ${filteredTrades.length} 笔`}>
          <TextInput label="搜索成交" isLabelHidden placeholder="搜索合约代码或日期" value={tradeQuery} onChange={(v) => { setTradeQuery(v); setPage(1); }} size="sm" />
          <Table
            data={paged}
            idKey="_id"
            density="compact"
            columns={[
              { key: "date", header: "时间", width: pixel(100) },
              { key: "instrument", header: "标的", width: proportional(1), renderCell: (r) => <Code>{r.instrument}</Code> },
              { key: "direction", header: "方向", width: pixel(56), renderCell: (r) => <Badge variant={r.direction === "buy" ? "success" : "error"} label={r.direction === "buy" ? "买入" : "卖出"} /> },
              { key: "price", header: "价格", width: pixel(80), align: "end", renderCell: (r) => <Text hasTabularNumbers>{r.price.toFixed(3)}</Text> },
              { key: "amount", header: "数量", width: pixel(90), align: "end", renderCell: (r) => <Text hasTabularNumbers>{Math.round(r.amount).toLocaleString()}</Text> },
              { key: "value", header: "金额", width: pixel(120), align: "end", renderCell: (r) => <Text hasTabularNumbers>{money(r.value)}</Text> },
              { key: "cost", header: "手续费", width: pixel(90), align: "end", renderCell: (r) => <Text hasTabularNumbers>{money(r.cost)}</Text> },
            ]}
          />
          <Pagination page={page} onChange={setPage} totalItems={filteredTrades.length} pageSize={PAGE} variant="compact" size="sm" />
          <Text type="supporting">价格为 Qlib 复权价，与交易所原始报价不同。</Text>
        </Section>
      )}
    </>
  );
}
