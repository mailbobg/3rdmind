import { useMemo, useState } from "react";
import { Alert, Chip, Disclosure, Input, ProgressBar } from "@heroui/react";
import type { BacktestResult, InstrumentSummary, Trade } from "../api/studio";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { Section } from "./Section";
import { CodeView, DataTable, EquityChart, Hint, MetricGrid, Mono, Signed, StatusChip, money, percent } from "./widgets";

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
    <div className="flex flex-col gap-3">
      <Section title={`回测 ${result.id.slice(0, 8)}`} note={<StatusChip status={backtestStatusLabel(result.status)} />}>
        <div className="flex flex-wrap gap-1">
          {legacy ? <Chip size="sm">旧格式回测 · {result.config.factors.length} 个因子</Chip> :
            result.config.factors.map((f) => <Chip key={`${f.trace}#${f.loop_id}#${f.name}`} size="sm" variant="soft">{f.kind === "prediction" ? "模型 · " : ""}{f.name}{f.weight !== 1 ? ` ×${f.weight}` : ""}</Chip>)}
        </div>
        <Hint>
          {result.config.start} → {result.config.end} · {result.config.market} · 基准 {result.config.benchmark || "SH000300"} · topk {result.config.topk} / n_drop {result.config.n_drop}
          {" · "}{result.config.model?.method === "lgbm" ? `LightGBM（训练 ${result.config.model.train.join("→")}，验证 ${result.config.model.valid.join("→")}）` : "排名加权"}
        </Hint>
        {result.error && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{result.error}</Alert.Title></Alert.Content></Alert>}
        {m && (
          <>
            <MetricGrid items={[
              { label: "总收益（扣费）", value: <Signed value={m.total_return} format={(v) => percent(v)} />, hint: "回测区间内的净值变化，已扣手续费" },
              { label: "超额收益", value: <Signed value={excess} format={(v) => percent(v)} />, hint: "总收益减去基准指数同期收益" },
              { label: "基准收益", value: percent(m.benchmark_return), hint: "基准指数同期收益" },
              { label: "复利年化", value: <Signed value={m.annualized_return} format={(v) => percent(v)} />, hint: "按 252 个交易日折算" },
              { label: "夏普", value: typeof m.sharpe === "number" ? m.sharpe.toFixed(2) : "—", hint: "日收益均值 ÷ 波动 × √252；1 以上算不错，0.5 以下基本靠运气" },
              { label: "最大回撤", value: percent(m.max_drawdown), hint: "净值从高点回落的最大幅度" },
              { label: "信号 IC", value: <Signed value={m.signal_ic} />, hint: "最终评分与次日收益的日均相关；|IC| < 0.01 接近噪声" },
              { label: "信号 Rank IC", value: <Signed value={m.signal_rank_ic} />, hint: "评分排名与次日收益排名的日均相关" },
              { label: "交易日数", value: String(m.days ?? "—"), hint: "样本太短（< 120 天）时以上指标都不可靠" },
            ]} />
            <div className="flex flex-col gap-1">
              {verdict.map((line) => (
                <Alert key={line} status={line.startsWith("跑赢") ? "success" : "default"} className="py-1.5">
                  <Alert.Indicator /><Alert.Content><Alert.Title className="text-xs font-normal">{line}</Alert.Title></Alert.Content>
                </Alert>
              ))}
            </div>
            <EquityChart rows={result.rows || []} />
            <Hint>{result.method}</Hint>
          </>
        )}
      </Section>
      {result.model && (
        <Section title="LightGBM 训练" note={`${result.model.train_rows.toLocaleString()} 训练样本 · ${result.model.valid_rows.toLocaleString()} 验证样本`}>
          <MetricGrid columns={2} items={[{ label: "最佳迭代", value: String(result.model.best_iteration) }, { label: "验证 L2", value: result.model.valid_l2.toFixed(4) }]} />
          <div className="flex flex-col gap-1.5">
            {importance.map(([name, gain]) => (
              <div key={name} className="grid grid-cols-[120px_1fr_60px] items-center gap-2">
                <Mono>{name}</Mono>
                <ProgressBar aria-label={`${name} 重要性`} value={importance[0][1] ? (gain / importance[0][1]) * 100 : 0} size="sm"><ProgressBar.Track><ProgressBar.Fill /></ProgressBar.Track></ProgressBar>
                <span className="text-right text-[11px] tabular-nums text-muted">{gain.toFixed(1)}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
      {m && <TradeTables trades={result.trades || []} instruments={result.instruments || []} holdings={result.holdings} />}
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
  const pageCount = Math.max(1, Math.ceil(filteredTrades.length / PAGE));
  const paged = filteredTrades.slice((page - 1) * PAGE, page * PAGE);
  if (!instruments.length && !trades.length) return null;
  return (
    <>
      {instruments.length > 0 && (
        <Section title="持仓与标的收益" note={`${holdings?.positions.length ?? 0} 只在手 · 共 ${instruments.length} 只交易过`}>
          <MetricGrid columns={3} items={[{ label: "持仓市值", value: money(marketValue) }, { label: "现金", value: money(holdings?.cash) }, { label: "手续费合计", value: money(totalCost) }]} />
          <Input aria-label="搜索标的" placeholder="搜索合约代码" value={instrumentQuery} onChange={(e) => setInstrumentQuery(e.target.value)} />
          <DataTable label="持仓与标的收益" head={[["标的"], ["成交笔数", "end"], ["在手市值", "end"], ["手续费", "end"], ["最终收益", "end"]]}
            rows={filteredInstruments.slice(0, 50).map((r) => ({
              key: r.instrument,
              cells: [
                <span key="i" className="flex items-center gap-1"><Mono>{r.instrument}</Mono>{r.held && <Chip size="sm" color="success" variant="soft">持有</Chip>}</span>,
                <span key="t" className="tabular-nums">{r.trades}</span>,
                <span key="h" className="tabular-nums">{r.holding_value ? money(r.holding_value) : "—"}</span>,
                <span key="c" className="tabular-nums">{money(r.cost)}</span>,
                <Signed key="p" value={r.pnl} format={money} />,
              ],
            }))} />
          {filteredInstruments.length > 50 && <Hint>只显示前 50 只，用搜索缩小范围。</Hint>}
        </Section>
      )}
      {trades.length > 0 && (
        <Section title="交易时间线" note={`共 ${filteredTrades.length} 笔 · 第 ${page} / ${pageCount} 页`}>
          <Input aria-label="搜索成交" placeholder="搜索合约代码或日期" value={tradeQuery} onChange={(e) => { setTradeQuery(e.target.value); setPage(1); }} />
          <DataTable label="交易时间线" head={[["时间"], ["标的"], ["方向"], ["价格", "end"], ["数量", "end"], ["金额", "end"], ["手续费", "end"]]}
            rows={paged.map((t, i) => ({
              key: `${t.date}-${t.instrument}-${i}`,
              cells: [
                <span key="d" className="tabular-nums">{t.date}</span>,
                <Mono key="i">{t.instrument}</Mono>,
                <Chip key="dir" size="sm" variant="soft" color={t.direction === "buy" ? "success" : "danger"}>{t.direction === "buy" ? "买入" : "卖出"}</Chip>,
                <span key="p" className="tabular-nums">{t.price.toFixed(3)}</span>,
                <span key="a" className="tabular-nums">{Math.round(t.amount).toLocaleString()}</span>,
                <span key="v" className="tabular-nums">{money(t.value)}</span>,
                <span key="c" className="tabular-nums">{money(t.cost)}</span>,
              ],
            }))} />
          <div className="flex items-center justify-center gap-2 text-[11px] text-muted">
            <button type="button" className="mm-btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</button>
            <span>{page} / {pageCount}</span>
            <button type="button" className="mm-btn" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>下一页</button>
          </div>
          <Hint>价格为 Qlib 复权价，与交易所原始报价不同。</Hint>
        </Section>
      )}
    </>
  );
}
