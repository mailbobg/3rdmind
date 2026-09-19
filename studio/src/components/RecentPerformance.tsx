import type { RecentContext, RecentHorizon, StyleName } from "../api/studio";
import { Note } from "./minimal";
import { Hint, Signed } from "./widgets";
import { t } from "../i18n";

/**
 * 近期表现在历史中的位置: the newest run's last week and month placed inside that run's own history, so a
 * bad stretch can be told apart as noise, stale data, the market, a style tilt, the signal weakening or the
 * picks themselves. One block per horizon: the return and where it falls among all same-length windows
 * (a strip with the 10–90 band, the median and this window), the signal's recent IC against its history,
 * the market / style / residual split of the window, and a one-line reading.
 */
const STYLE_LABELS: Record<StyleName, string> = { momentum: "动量（20 日）", reversal: "反转（5 日）", volatility: "波动率（20 日）", liquidity: "成交额（20 日）" };
const HORIZON_LABELS = { week: "最近一周", month: "最近一月" };

const pct = (v: number) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
// Floored so the number agrees with the rule ("below 10" reads as 9, never 10).
const ordinal = (p: number) => Math.floor(p * 100);

function readingText(h: RecentHorizon) {
  const p = ordinal(h.percentile), n = h.days;
  const styles = h.attribution ? (Object.entries(h.attribution.styles) as [StyleName, number][]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])) : [];
  switch (h.reading) {
    case "normal":
      return t("落在历史第 {0} 百分位，属于正常波动，不需要动作。", [p]);
    case "drift":
      return t("收益在历史第 {0} 百分位，同时近 {1} 日 IC 均值 {2} 落在历史第 {3} 百分位：信号本身在变弱。走一次“更新到最新”重训，不要手工调参数。", [p, n, h.ic!.recent.toFixed(4), ordinal(h.ic!.percentile)]);
    case "market":
      return t("收益在历史第 {0} 百分位，这段亏损主要来自市场本身（{1}），信号 IC 正常。这是持有 beta 的账单，不是策略坏了。", [p, pct(h.attribution!.market)]);
    case "style":
      return t("收益在历史第 {0} 百分位，主要来自风格暴露（{1} {2}），信号 IC 正常。策略长期靠承担这个风格赚钱，短期回撤是它的代价。", [p, t(STYLE_LABELS[styles[0][0]]), pct(styles[0][1])]);
    case "specific":
      return t("收益在历史第 {0} 百分位，市场和风格解释不了（残差 {1}），IC 也正常：看个股，检查持仓里是否有个别标的出事。", [p, pct(h.attribution!.residual)]);
    default:
      return t("收益在历史第 {0} 百分位，低于正常范围；IC 与归因要在“更新到最新”跑一次新回测后才有，先更新再判断。", [p]);
  }
}

function Strip({ h }: { h: RecentHorizon }) {
  const span = h.high - h.low || 1;
  const at = (v: number) => `${Math.max(0, Math.min(100, ((v - h.low) / span) * 100))}%`;
  const bad = h.percentile < 0.1;
  return (
    <div className="pulse__dist">
      <div className="pulse__strip" role="img" aria-label={t("{0} 个同长度窗口的收益分布，当前窗口在第 {1} 百分位", [h.windows, ordinal(h.percentile)])}>
        <div className="pulse__band" style={{ left: at(h.p10), width: `calc(${at(h.p90)} - ${at(h.p10)})` }} title={t("10–90 百分位：{0} 到 {1}", [pct(h.p10), pct(h.p90)])} />
        {h.low < 0 && h.high > 0 && <div className="pulse__tick pulse__tick--zero" style={{ left: at(0) }} title="0" />}
        <div className="pulse__tick" style={{ left: at(h.median) }} title={t("中位数 {0}", [pct(h.median)])} />
        <div className={`pulse__dot${bad ? " pulse__dot--bad" : ""}`} style={{ left: at(h.return) }} title={t("当前窗口 {0}", [pct(h.return)])} />
      </div>
      <div className="pulse__axis"><span>{pct(h.low)}</span><span>{t("中位 {0}", [pct(h.median)])}</span><span>{pct(h.high)}</span></div>
    </div>
  );
}

function Attribution({ h }: { h: RecentHorizon }) {
  const a = h.attribution!;
  const styleTotal = Object.values(a.styles).reduce((s, v) => s + v, 0);
  const top = (Object.entries(a.styles) as [StyleName, number][]).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))[0];
  const items: { label: string; value: number; hint?: string }[] = [
    { label: t("市场"), value: a.market, hint: t("基准这段的涨跌 × 策略对基准的 beta") },
    { label: t("风格"), value: styleTotal, hint: (Object.entries(a.styles) as [StyleName, number][]).map(([k, v]) => `${t(STYLE_LABELS[k])} ${pct(v)}`).join(" · ") },
    { label: t("个股（残差）"), value: a.residual, hint: t("市场和风格都解释不了的部分：选出来的股票自己的涨跌") },
    { label: t("预期漂移"), value: a.alpha, hint: t("全期回归的日均 alpha × 天数") },
  ];
  const scale = Math.max(0.002, ...items.map((i) => Math.abs(i.value)));
  return (
    <div className="pulse__attr" role="list" aria-label={t("收益拆解")}>
      {items.map((i) => (
        <div key={i.label} className="pulse__row" role="listitem" title={i.hint}>
          <span className="pulse__key">{i.label}{i.label === t("风格") && top ? <span className="pulse__sub"> {t(STYLE_LABELS[top[0]])}</span> : null}</span>
          <div className="pulse__track">
            <div className={`pulse__bar${i.value < 0 ? " pulse__bar--neg" : ""}`} style={{ width: `${(Math.abs(i.value) / scale) * 50}%` }} />
          </div>
          <span className="pulse__val"><Signed value={i.value} format={(v) => pct(v ?? 0)} /></span>
        </div>
      ))}
      <Hint>{t("算术拆分：{0} = 市场 + 风格 + 残差 + 预期漂移；beta 用整段回测回归得到。", [pct(a.actual)])}</Hint>
    </div>
  );
}

export function RecentPerformance({ data, dataEnd }: { data: RecentContext; dataEnd?: string | null }) {
  const stale = !!dataEnd && (data.window_end || data.as_of) < dataEnd;
  return (
    <div className="flex flex-col gap-3">
      {stale && <Note tone="warn">{t("证据日期停在 {0}，行情数据已到 {1}。下面的数字是截至 {0} 的；先点“更新到最新”，再判断最近表现。", [data.window_end || data.as_of, dataEnd])}</Note>}
      {data.horizons.map((h) => (
        <div key={h.key} className="pulse">
          <div className="pulse__head">
            <span className="pulse__title">{t(HORIZON_LABELS[h.key])}</span>
            <span className="pulse__dates">{h.start} → {h.end} · {t("{0} 个交易日", [h.days])}</span>
          </div>
          <div className="pulse__nums">
            <span><span className="pulse__k">{t("收益")}</span><Signed value={h.return} format={(v) => pct(v ?? 0)} /></span>
            <span><span className="pulse__k">{t("基准")}</span><Signed value={h.benchmark} format={(v) => pct(v ?? 0)} /></span>
            <span><span className="pulse__k">{t("超额")}</span><Signed value={h.excess} format={(v) => pct(v ?? 0)} /></span>
            <span><span className="pulse__k">{t("历史位置")}</span><span className={`tabular-nums${h.percentile < 0.1 ? " text-danger" : ""}`}>{t("第 {0} 百分位", [ordinal(h.percentile)])}</span><span className="text-muted"> / {t("{0} 个窗口", [h.windows])}</span></span>
          </div>
          <Strip h={h} />
          <div className="pulse__ic">
            {h.ic ? (
              <>
                <span className="pulse__k">IC</span>
                <span className="tabular-nums">{t("近 {0} 日均值 {1}", [h.days, h.ic.recent.toFixed(4)])}{h.ic.lag ? <span className="text-muted" title={t("预测 N 日收益的信号，最近 N 日还没有完整的标签，IC 只能算到 {0}", [h.ic.end])}> {t("（截至 {0}）", [h.ic.end])}</span> : null}</span>
                <span className={`tabular-nums${h.ic.percentile < 0.1 ? " text-danger" : ""}`}>{t("历史第 {0} 百分位", [ordinal(h.ic.percentile)])}</span>
                <span className="text-muted">{t("全期均值 {0}", [h.ic.mean.toFixed(4)])}</span>
              </>
            ) : <span className="text-muted">{t("IC 序列与收益拆解：这次回测里还没有，“更新到最新”后可见。")}</span>}
          </div>
          {h.attribution && <Attribution h={h} />}
          <p className={`pulse__read${h.reading === "normal" ? "" : h.reading === "drift" ? " pulse__read--bad" : " pulse__read--warn"}`}>{readingText(h)}</p>
        </div>
      ))}
      <Hint>{t("一周的样本量建立不了任何统计结论，好坏都一样。这里只回答一个问题：最近这段在这条策略自己的历史里算不算反常，反常的话像什么。百分位低于 10 才往下看。")}</Hint>
    </div>
  );
}
