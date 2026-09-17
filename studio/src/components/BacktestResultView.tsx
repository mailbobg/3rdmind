import { useMemo, useState } from "react";
import { Alert, Chip, Disclosure, Input, ProgressBar } from "@heroui/react";
import type { BacktestResult, Breakdown, InstrumentSummary, SignalDiagnosis, Trade } from "../api/studio";
import { Btn } from "./minimal";
import { useStudio } from "../hooks/studioContext";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { Section } from "./Section";
import { CodeView, CorrelationMatrix, CurveOverlay, DataTable, EquityChart, Hint, Instrument, MetricGrid, Mono, Signed, StatusChip, money, percent } from "./widgets";
import { t as tr } from "../i18n";

/** `onDiagnose` starts the take-apart diagnosis (the owner refetches and polls); absent, the button is hidden. */
export function BacktestResultView({ result, onDiagnose }: { result: BacktestResult; onDiagnose?: () => void }) {
  const legacy = (result.config.loop_id === undefined || result.config.loop_id === null)
    && !result.config.factors.some((f) => f.loop_id !== undefined && f.loop_id !== null);
  const m = result.metrics;
  const excess = m ? m.total_return - m.benchmark_return : null;
  const verdict = useMemo(() => {
    if (!m) return [];
    const lines: string[] = [];
    const ex = m.total_return - m.benchmark_return;
    lines.push(ex >= 0 ? tr("跑赢基准 {0}。", [percent(ex)]) : tr("跑输基准 {0}：这段时间不如直接持有指数。", [percent(-ex)]));
    if (typeof m.signal_ic === "number" && Math.abs(m.signal_ic) < 0.01 && typeof m.signal_rank_ic === "number" && Math.abs(m.signal_rank_ic) < 0.01)
      lines.push(tr("评分对次日收益几乎没有预测力（|IC| < 0.01），收益主要来自运气或市场本身，回到因子库换信号比调参数更有用。"));
    else if (typeof m.signal_ic === "number" && m.signal_ic < -0.01)
      lines.push(tr("评分与次日收益负相关：信号方向反了，排名加权模式下把权重改成负数再试。"));
    if (typeof m.sharpe === "number" && m.sharpe < 0.5 && ex >= 0) lines.push(tr("夏普低于 0.5，收益波动大，不宜据此下结论。"));
    if (result.model && result.model.best_iteration <= 20) lines.push(tr("LightGBM 在第 {0} 轮就早停：训练集里学不到多少东西，信号本身偏弱。", [result.model.best_iteration]));
    if ((m.days ?? 0) < 120) lines.push(tr("交易日不足 120 天，样本太短。"));
    return lines;
  }, [m, result.model]);
  const importance = useMemo(() => Object.entries(result.model?.feature_importance || {}).sort((a, b) => b[1] - a[1]), [result.model]);

  return (
    <div className="flex flex-col gap-3">
      <Section title={tr("回测 {0}", [result.id.slice(0, 8)])} note={<StatusChip status={backtestStatusLabel(result.status)} />}>
        <div className="flex flex-wrap gap-1">
          {legacy ? <Chip size="sm">{tr("旧格式回测 · {0} 个因子", [result.config.factors.length])}</Chip> :
            result.config.factors.map((f) => <Chip key={`${f.trace}#${f.loop_id}#${f.name}`} size="sm" variant="soft">{f.kind === "prediction" ? tr("模型 · ") : ""}{f.name}{f.weight !== 1 ? ` ×${f.weight}` : ""}</Chip>)}
        </div>
        <Hint>
          {result.config.start} → {result.config.end} · {result.config.market} · {tr("基准")} {result.config.benchmark || "SH000300"} · topk {result.config.topk} / n_drop {result.config.n_drop}
          {" · "}{result.config.model?.method === "lgbm" ? tr("LightGBM（训练 {0}，验证 {1}）", [result.config.model.train.join("→"), result.config.model.valid.join("→")]) : tr("排名加权")}
        </Hint>
        {result.error && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{result.error}</Alert.Title></Alert.Content></Alert>}
        {result.notes?.map((n, i) => <Alert key={i} status="accent"><Alert.Indicator /><Alert.Content><Alert.Title>{n}</Alert.Title></Alert.Content></Alert>)}
        {m && (
          <>
            <MetricGrid items={[
              { label: tr("总收益（扣费）"), value: <Signed value={m.total_return} format={(v) => percent(v)} />, hint: tr("回测区间内的净值变化，已扣手续费") },
              { label: tr("超额收益"), value: <Signed value={excess} format={(v) => percent(v)} />, hint: tr("总收益减去基准指数同期收益") },
              { label: tr("基准收益"), value: percent(m.benchmark_return), hint: tr("基准指数同期收益") },
              { label: tr("复利年化"), value: <Signed value={m.annualized_return} format={(v) => percent(v)} />, hint: tr("按 252 个交易日折算") },
              { label: tr("夏普"), value: typeof m.sharpe === "number" ? m.sharpe.toFixed(2) : "—", hint: tr("日收益均值 ÷ 波动 × √252；1 以上算不错，0.5 以下基本靠运气") },
              { label: tr("最大回撤"), value: percent(m.max_drawdown), hint: tr("净值从高点回落的最大幅度") },
              { label: tr("信号 IC"), value: <Signed value={m.signal_ic} />, hint: tr("最终评分与次日收益的日均相关；|IC| < 0.01 接近噪声") },
              { label: tr("信号 Rank IC"), value: <Signed value={m.signal_rank_ic} />, hint: tr("评分排名与次日收益排名的日均相关") },
              { label: tr("交易日数"), value: String(m.days ?? "—"), hint: tr("样本太短（< 120 天）时以上指标都不可靠") },
            ]} />
            <div className="flex flex-col gap-1">
              {verdict.map((line) => (
                <Alert key={line} status={line.startsWith(tr("跑赢")) ? "success" : "default"} className="py-1.5">
                  <Alert.Indicator /><Alert.Content><Alert.Title className="text-xs font-normal">{line}</Alert.Title></Alert.Content>
                </Alert>
              ))}
            </div>
            <EquityChart rows={result.rows || []} />
            <Hint>{result.method}</Hint>
          </>
        )}
      </Section>
      {m && result.diagnosis && <PortfolioDiagnosis result={result} onDiagnose={onDiagnose} />}
      {result.model && (
        <Section title={tr("LightGBM 训练")} note={tr("{0} 训练样本 · {1} 验证样本", [result.model.train_rows.toLocaleString(), result.model.valid_rows.toLocaleString()])}>
          <MetricGrid columns={2} items={[{ label: tr("最佳迭代"), value: String(result.model.best_iteration) }, { label: tr("验证 L2"), value: result.model.valid_l2.toFixed(4) }]} />
          <div className="flex flex-col gap-1.5">
            {importance.map(([name, gain]) => (
              <div key={name} className="grid grid-cols-[120px_1fr_60px] items-center gap-2">
                <Mono>{name}</Mono>
                <ProgressBar aria-label={tr("{0} 重要性", [name])} value={importance[0][1] ? (gain / importance[0][1]) * 100 : 0} size="sm"><ProgressBar.Track><ProgressBar.Fill /></ProgressBar.Track></ProgressBar>
                <span className="text-right text-[11px] tabular-nums text-muted">{gain.toFixed(1)}</span>
              </div>
            ))}
          </div>
        </Section>
      )}
      {m && <TradeTables trades={result.trades || []} instruments={result.instruments || []} holdings={result.holdings} />}
      {result.log && (
        <Section title={tr("执行日志")}>
          <Disclosure>
            <Disclosure.Heading><Disclosure.Trigger className="text-xs">{tr("展开日志")}<Disclosure.Indicator /></Disclosure.Trigger></Disclosure.Heading>
            <Disclosure.Content><CodeView code={result.log} /></Disclosure.Content>
          </Disclosure>
        </Section>
      )}
    </div>
  );
}

function TradeTables({ trades, instruments, holdings }: { trades: Trade[]; instruments: InstrumentSummary[]; holdings?: BacktestResult["holdings"] }) {
  const { workspace } = useStudio();
  const region = workspace.region;
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
        <Section title={tr("持仓与标的收益")} note={tr("{0} 只在手 · 共 {1} 只交易过", [holdings?.positions.length ?? 0, instruments.length])}>
          <MetricGrid columns={3} items={[{ label: tr("持仓市值"), value: money(marketValue, region) }, { label: tr("现金"), value: money(holdings?.cash, region) }, { label: tr("手续费合计"), value: money(totalCost, region) }]} />
          <Input aria-label={tr("搜索标的")} placeholder={tr("搜索合约代码")} value={instrumentQuery} onChange={(e) => setInstrumentQuery(e.target.value)} />
          <DataTable label={tr("持仓与标的收益")} head={[[tr("标的")], [tr("成交笔数"), "end"], [tr("在手市值"), "end"], [tr("手续费"), "end"], [tr("最终收益"), "end"]]}
            rows={filteredInstruments.slice(0, 50).map((r) => ({
              key: r.instrument,
              cells: [
                <span key="i" className="flex items-center gap-1"><Instrument code={r.instrument} />{r.held && <Chip size="sm" color="success" variant="soft">{tr("持有")}</Chip>}</span>,
                <span key="t" className="tabular-nums">{r.trades}</span>,
                <span key="h" className="tabular-nums">{r.holding_value ? money(r.holding_value, region) : "—"}</span>,
                <span key="c" className="tabular-nums">{money(r.cost, region)}</span>,
                <Signed key="p" value={r.pnl} format={money} />,
              ],
            }))} />
          {filteredInstruments.length > 50 && <Hint>{tr("只显示前 50 只，用搜索缩小范围。")}</Hint>}
        </Section>
      )}
      {trades.length > 0 && (
        <Section title={tr("交易时间线")} note={tr("共 {0} 笔 · 第 {1} / {2} 页", [filteredTrades.length, page, pageCount])}>
          <Input aria-label={tr("搜索成交")} placeholder={tr("搜索合约代码或日期")} value={tradeQuery} onChange={(e) => { setTradeQuery(e.target.value); setPage(1); }} />
          <DataTable label={tr("交易时间线")} head={[[tr("时间")], [tr("标的")], [tr("方向")], [tr("价格"), "end"], [tr("数量"), "end"], [tr("金额"), "end"], [tr("手续费"), "end"]]}
            rows={paged.map((t, i) => ({
              key: `${t.date}-${t.instrument}-${i}`,
              cells: [
                <span key="d" className="tabular-nums">{t.date}</span>,
                <Instrument key="i" code={t.instrument} />,
                <Chip key="dir" size="sm" variant="soft" color={t.direction === "buy" ? "success" : "danger"}>{t.direction === "buy" ? tr("买入") : tr("卖出")}</Chip>,
                <span key="p" className="tabular-nums">{t.price.toFixed(3)}</span>,
                <span key="a" className="tabular-nums">{Math.round(t.amount).toLocaleString()}</span>,
                <span key="v" className="tabular-nums">{money(t.value, region)}</span>,
                <span key="c" className="tabular-nums">{money(t.cost, region)}</span>,
              ],
            }))} />
          <div className="flex items-center justify-center gap-2 text-[11px] text-muted">
            <button type="button" className="mm-btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>{tr("上一页")}</button>
            <span>{page} / {pageCount}</span>
            <button type="button" className="mm-btn" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>{tr("下一页")}</button>
          </div>
          <Hint>{tr("价格为 Qlib 复权价，与交易所原始报价不同。")}</Hint>
        </Section>
      )}
    </>
  );
}

const fmtPct = (v?: number | null) => (typeof v === "number" ? percent(v, 1) : "—");
const fmtIc = (v?: number | null) => (typeof v === "number" ? (v > 0 ? "+" : "") + v.toFixed(4) : "—");

/**
 * Is this combination sound? Read on every multi-signal run from the per-signal IC and the correlation on the
 * window; optionally deepened by the take-apart backtests (each signal alone, portfolio without each signal).
 */
function PortfolioDiagnosis({ result, onDiagnose }: { result: BacktestResult; onDiagnose?: () => void }) {
  const { workspace } = useStudio();
  const d = result.diagnosis!;
  const b: Breakdown | null | undefined = result.breakdown;
  const done = b?.status === "completed" && b.base && b.alone && b.without;
  const base = result.metrics!.total_return;

  const verdict = useMemo(() => {
    const lines: { tone: "bad" | "warn" | "ok"; text: string }[] = [];
    // IC is a mean over the whole cross-section; TopkDropout only trades the top of the ranking, so once the
    // take-apart numbers exist they overrule an IC-based suspicion about a signal that measurably helps.
    const contribution = (name: string) => {
      const w = done ? b!.without![name] : undefined;
      return w && typeof w.total_return === "number" ? base - w.total_return : null;
    };
    for (const sig of d.signals) {
      const ric = sig.rank_ic;
      if (typeof ric !== "number") continue;
      const suspicious = Math.abs(ric) < 0.005 ? "weak" : Math.sign(ric) !== Math.sign(sig.weight) ? "reversed" : null;
      if (!suspicious) continue;
      const c = contribution(sig.name);
      if (c != null && c > 0.005) {
        lines.push({ tone: "ok", text: tr("{0} 的 Rank IC {1} 看着{2}，但去掉它组合收益会少 {3}：它对头部选股有用，IC 这个全截面平均看不出来。", [sig.name, fmtIc(ric), suspicious === "weak" ? tr("没用") : tr("方向反了"), fmtPct(c)]) });
      } else if (suspicious === "weak") {
        lines.push({ tone: "warn", text: tr("{0} 在这段区间几乎没有预测力（Rank IC {1}），留在组合里只是稀释别的信号。", [sig.name, fmtIc(ric)]) });
      } else {
        lines.push({ tone: "bad", text: tr("{0} 的 Rank IC {1} 与权重 {2} 方向相反，正在拖累组合：把权重改成 {3} 或移出。", [sig.name, fmtIc(ric), sig.weight, -sig.weight]) });
      }
    }
    const { names, matrix } = d.correlation;
    matrix.forEach((row, i) => row.forEach((v, j) => { if (i < j && Math.abs(v) >= 0.7) lines.push({ tone: "warn", text: tr("{0} 与 {1} 在这段区间相关 {2}，基本是同一个信号，同时入选只是重复计权。", [names[i], names[j], v.toFixed(2)]) }); }));
    if (done) {
      const alone = Object.entries(b!.alone!).filter(([, v]) => typeof v.total_return === "number").sort((x, y) => y[1].total_return! - x[1].total_return!);
      if (alone.length) {
        const [bestName, best] = alone[0];
        lines.push(base >= best.total_return!
          ? { tone: "ok", text: tr("组合 {0} 优于最好的单信号 {1}（{2}），组合本身有价值。", [fmtPct(base), bestName, fmtPct(best.total_return)]) }
          : { tone: "bad", text: tr("最好的单信号 {0} 单独就有 {1}，组合只有 {2}：其他信号在拖累它。", [bestName, fmtPct(best.total_return), fmtPct(base)]) });
      }
      const drops = Object.entries(b!.without!).filter(([, v]) => typeof v.total_return === "number").map(([name, v]) => ({ name, gain: v.total_return! - base })).sort((x, y) => y.gain - x.gain);
      if (drops.length && drops[0].gain > 0.005) lines.push({ tone: "bad", text: tr("去掉 {0} 后组合收益从 {1} 变为 {2}，它是首先应该移出的信号。", [drops[0].name, fmtPct(base), fmtPct(base + drops[0].gain)]) });
      else if (drops.length) lines.push({ tone: "ok", text: tr("去掉任何一个信号都不会让组合更好，每个信号都在贡献。") });
    }
    if (!lines.length) lines.push({ tone: "ok", text: tr("每个信号的方向都和权重一致，两两相关都在 0.7 以下；要判断谁在贡献，点“逐个拆开回测”。") });
    return lines;
  }, [d, b, done, base]);

  const columns: [string, ("start" | "end")?][] = [[tr("信号")], [tr("权重"), "end"], ["IC", "end"], ["Rank IC", "end"], [tr("与组合评分相关"), "end"]];
  if (done) columns.push([tr("单独回测"), "end"], [tr("去掉它后"), "end"], [tr("贡献"), "end"]);
  const rows = d.signals.map((sig: SignalDiagnosis) => {
    const alone = done ? b!.alone![sig.name] : undefined;
    const without = done ? b!.without![sig.name] : undefined;
    const contribution = without && typeof without.total_return === "number" ? base - without.total_return : null;
    const cells = [
      <span key="n" className="flex items-center gap-1"><Mono>{sig.name}</Mono>{sig.kind === "prediction" && <Chip size="sm" variant="soft">{tr("模型")}</Chip>}</span>,
      <span key="w" className="tabular-nums">{sig.weight}</span>,
      <Signed key="ic" value={sig.ic} />,
      <Signed key="ric" value={sig.rank_ic} />,
      <span key="c" className="tabular-nums">{typeof sig.corr_with_score === "number" ? sig.corr_with_score.toFixed(2) : "—"}</span>,
    ];
    if (done) cells.push(
      alone?.error ? <span key="a" className="text-[11px] text-muted" title={alone.error}>{tr("无法单独回测")}</span> : <Signed key="a" value={alone?.total_return} format={(v) => percent(v, 1)} />,
      without?.error ? <span key="wo" className="text-[11px] text-muted" title={without.error}>—</span> : <Signed key="wo" value={without?.total_return} format={(v) => percent(v, 1)} />,
      <Signed key="g" value={contribution} format={(v) => percent(v, 1)} />,
    );
    return { key: sig.name, cells };
  });

  const curves = useMemo(() => {
    if (!done) return [];
    const out: { name: string; points: [string, number][]; dashed?: boolean; bold?: boolean; hidden?: boolean }[] = [];
    if (b!.base?.equity) out.push({ name: tr("组合"), points: b!.base.equity, bold: true });
    for (const name of b!.names || []) {
      const alone = b!.alone![name]; const without = b!.without![name];
      if (alone?.equity) out.push({ name: tr("{0} 单独", [name]), points: alone.equity });
      if (without?.equity) out.push({ name: tr("去掉 {0}", [name]), points: without.equity, dashed: true, hidden: true });
    }
    return out;
  }, [b, done]);
  const running = b?.status === "queued" || b?.status === "running";
  return (
    <Section title={tr("组合诊断")} note={tr("{0} 个信号 · 回测区间 {1} 个交易日", [d.signals.length, d.correlation.days])}>
      <div className="flex flex-col gap-1">
        {verdict.map((line) => (
          <Alert key={line.text} status={line.tone === "bad" ? "danger" : line.tone === "warn" ? "warning" : "success"} className="py-1.5">
            <Alert.Indicator /><Alert.Content><Alert.Title className="text-xs font-normal">{line.text}</Alert.Title></Alert.Content>
          </Alert>
        ))}
      </div>
      <DataTable label={tr("组合诊断")} head={columns} rows={rows} />
      {done && curves.length > 1 && (
        <>
          <CurveOverlay series={curves} />
          <Hint>{tr("粗线是组合；实线是每个信号单独跑出来的净值，虚线是去掉该信号后的组合（默认隐藏，点图例显示）。同一区间、同一参数。")}</Hint>
        </>
      )}
      <Hint>IC / Rank IC 按回测区间内每日截面计算；“与组合评分相关”是该信号排名与最终评分的相关，越低说明它在组合里的话语权越小。{done ? tr("“贡献”= 组合收益 − 去掉它后的组合收益，正数表示它在帮忙。") : ""}</Hint>
      {d.correlation.names.length > 1 && <CorrelationMatrix data={d.correlation} />}
      <div className="flex flex-wrap items-center gap-2">
        {!done && onDiagnose && <Btn disabled={running} onClick={onDiagnose}>{running ? tr("拆开回测中{0}…", [b?.done != null && b?.total ? ` ${b.done}/${b.total}` : ""]) : tr("逐个拆开回测")}</Btn>}
        {b?.status === "failed" && <span className="text-[11px] text-danger">{tr("拆开回测失败：{0}", [b.error])}</span>}
        {!done && !running && <Hint>{tr("每个信号单独跑一遍，再每次去掉一个跑一遍，同样的区间和参数；{0} 次回测，约 {1} 分钟。", [2 * d.signals.length + 1, Math.ceil((2 * d.signals.length + 1) * 0.5)])}</Hint>}
        <a href={workspace.href("/factors")} className="text-[11px] text-accent underline">{tr("回因子库换信号 →")}</a>
      </div>
    </Section>
  );
}
