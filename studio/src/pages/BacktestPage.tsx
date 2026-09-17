import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as studio from "../api/studio";
import type { BacktestSummary, CorrelationMatrix as Corr, Coverage, FactorRef, FactorWeight, LibraryFactor, Universe } from "../api/studio";
import { universeLabel } from "../api/studio";
import { basketKey as key } from "../hooks/useFactorBasket";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { persistStudioState, restoreStudioState } from "../hooks/studioStorage";
import { download, errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { BacktestResultView } from "../components/BacktestResultView";
import { SearchResultView } from "../components/SearchResultView";
import { useSearches } from "../hooks/useSearches";
import { shortTime } from "../hooks/experiments";
import { DUPLICATE_CORR, pickByCorrelation, rankCandidates } from "../hooks/autoPick";
import type { SearchObjective } from "../api/studio";
import { Block, Btn, Empty, Field, FieldGrid, Link, Note, Num, NumberInput, P, SelectInput, StatusTag, Table, TextInput, TextTabs } from "../components/minimal";
import { Hint } from "../components/widgets";
import { t } from "../i18n";

type Market = string;
interface Params { start: string; end: string; market: Market; benchmark: string; topk: number; n_drop: number; account: number; open_cost: number; close_cost: number }
interface Lgbm { train: [string, string]; valid: [string, string]; params: Record<string, number> }

const shiftYears = (date: string, years: number) => { const d = new Date(date); d.setFullYear(d.getFullYear() + years); return d.toISOString().slice(0, 10); };
const dayBefore = (date: string) => { const d = new Date(date); d.setDate(d.getDate() - 1); return d.toISOString().slice(0, 10); };
const LGBM_DEFAULTS = { learning_rate: 0.05, num_leaves: 63, max_depth: 8, n_estimators: 1000, early_stopping_rounds: 50, colsample_bytree: 0.8, subsample: 0.8, lambda_l2: 1 };

export function BacktestPage() {
  const { env, backtests, basket, layout, workspace } = useStudio();
  const saved = useMemo(() => restoreStudioState(), []);
  const [params, setParams] = useState<Params>({
    start: "", end: "", market: "csi300", benchmark: "SH000300", topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015, ...(saved.params || {}),
  });
  const set = <K extends keyof Params>(k: K, v: Params[K]) => setParams((p) => ({ ...p, [k]: v }));
  const [method, setMethod] = useState<"rank" | "lgbm">(saved.model?.method === "lgbm" ? "lgbm" : "rank");
  const [lgbm, setLgbm] = useState<Lgbm>({
    train: ["", ""], valid: ["", ""], params: { ...LGBM_DEFAULTS },
    ...(saved.model?.method === "lgbm" ? { train: saved.model.train, valid: saved.model.valid, params: { ...LGBM_DEFAULTS, ...saved.model.params } } : {}),
  });
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState(searchParams.get("tab") === "search" ? "search" : "params");
  const [universes, setUniverses] = useState<Universe[]>([]);
  useEffect(() => { studio.universes().then(setUniverses).catch(() => {}); }, []);
  useEffect(() => {
    if (!universes.length || universes.some((u) => u.market === params.market)) return;
    const u = universes[0];
    setParams((p) => ({ ...p, market: u.market, benchmark: u.benchmark, open_cost: u.open_cost, close_cost: u.close_cost }));
  }, [universes]); // eslint-disable-line react-hooks/exhaustive-deps
  // ?job= (from the runs page, a toast or the failure banner) opens that backtest or search on arrival.
  useEffect(() => {
    const wanted = searchParams.get("job");
    if (wanted) {
      if (searchParams.get("tab") === "search") searches.select(wanted); else backtests.select(wanted);
      layout.openResults();
    } else {
      // The page starts with an empty results column; earlier runs live under 历史回测.
      backtests.clear();
    }
    if (searchParams.get("tab") || wanted) setSearchParams({}, { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // Portfolio search: the basket's factor signals are the candidates, the backtest parameters the setting.
  const searches = useSearches();
  const [objective, setObjective] = useState<SearchObjective>("sharpe");
  useEffect(() => { searches.load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (tab === "search" && searches.jobs.length && !searches.selectedId) searches.select(searches.jobs[0].id); }, [tab, searches.jobs]); // eslint-disable-line react-hooks/exhaustive-deps
  const candidates = basket.items.filter((f) => (f.kind || "factor") === "factor");
  const startSearch = async () => {
    const accepted = await searches.run({ factors: candidates.map((f) => ({ ...f, weight: Number(f.weight) })), model: { method: "rank" }, ...params, search: { objective } });
    if (accepted) layout.openResults();
  };
  // 保存为策略: the completed backtest (or the search recommendation) becomes a named, tracked portfolio.
  const [savingFrom, setSavingFrom] = useState<"backtest" | "search" | "">("");
  const [strategyName, setStrategyName] = useState("");
  const [savedNote, setSavedNote] = useState("");
  const saveStrategy = async () => {
    const name = strategyName.trim();
    if (!name) { setPageError(t("给策略起个名字。")); return; }
    try {
      if (savingFrom === "backtest" && result?.metrics) {
        const c = result.config;
        await studio.saveStrategy({ name, factors: c.factors, model: c.model || { method: "rank" },
          params: { market: c.market, benchmark: c.benchmark, topk: c.topk, n_drop: c.n_drop, account: c.account, open_cost: c.open_cost, close_cost: c.close_cost },
          evidence: { backtest_id: result.id, start: c.start, end: c.end } });
      } else if (savingFrom === "search" && searches.result?.recommended_portfolio) {
        const rec = searches.result.recommended_portfolio; const c = searches.result.config;
        const members = c.factors.filter((f) => rec.members.includes(f.name)).map((f) => ({ ...f, weight: rec.weights?.[f.name] ?? f.weight }));
        await studio.saveStrategy({ name, factors: members, model: { method: "rank" },
          params: { market: c.market, benchmark: c.benchmark, topk: c.topk, n_drop: c.n_drop, account: c.account, open_cost: c.open_cost, close_cost: c.close_cost },
          evidence: { search_id: searches.result.id, start: c.start, end: c.end } });
      } else return;
      setSavedNote(t("已保存为策略「{0}」，在左栏「策略」里跟踪。", [name]));
      setSavingFrom(""); setStrategyName("");
    } catch (e) { setPageError(errorText(e)); }
  };
  const saveForm = (
    <div className="mm-row">
      <TextInput value={strategyName} onChange={setStrategyName} placeholder={t("策略名称")} className="w-56" />
      <Btn kind="primary" onClick={saveStrategy}>{t("保存")}</Btn>
      <Btn kind="text" onClick={() => setSavingFrom("")}>{t("取消")}</Btn>
    </div>
  );

  // The recommendation is rebuilt from the search job's own factor references, so it works even when the
  // basket has changed since (or the result belongs to an earlier search).
  // 自动挑候选: rank the library by |ICIR|, drop noise, keep one of each near-duplicate pair, sign by Rank IC.
  const [picking, setPicking] = useState(false);
  const [pickNote, setPickNote] = useState("");
  const [pendingAnalysis, setPendingAnalysis] = useState<LibraryFactor[]>([]);
  const [analyzeProgress, setAnalyzeProgress] = useState("");
  // Analyses are Qlib subprocesses, so they run one at a time; then the library is re-read and the pick redone.
  const analyzeThenPick = async () => {
    setPicking(true);
    try {
      for (let i = 0; i < pendingAnalysis.length; i++) {
        setAnalyzeProgress(t("计算指标 {0}/{1}：{2}", [i + 1, pendingAnalysis.length, pendingAnalysis[i].name]));
        try { await studio.factorAnalysis(pendingAnalysis[i]); } catch (e) { setPageError(`${pendingAnalysis[i].name}：${errorText(e)}`); }
      }
      const list = await studio.factorLibrary();
      const fresh = Object.fromEntries(list.map((f) => [key(f), f]));
      setLibrary(fresh);
      await autoPick(Object.values(fresh));
    } finally { setAnalyzeProgress(""); setPicking(false); }
  };
  const autoPick = async (pool: LibraryFactor[] = Object.values(library)) => {
    setPicking(true); setPickNote("");
    try {
      const all = pool;
      const { ranked, noise, unanalyzed } = rankCandidates(all);
      setPendingAnalysis(unanalyzed);
      if (ranked.length < 2) { setPickNote(t("因子库里只有 {0} 个因子有可用信号（{1} 个是噪声，{2} 个还没算指标），不够搜索。先在因子库点\"分析全部\"。", [ranked.length, noise.length, unanalyzed.length])); return; }
      const shortlist = ranked.slice(0, 12);
      const corr = await studio.factorCorrelation(shortlist.map((r) => ({ trace: r.factor.trace, loop_id: r.factor.loop_id, name: r.factor.name })));
      const { picked, duplicates } = pickByCorrelation(shortlist, corr, 8);
      basket.replace(picked);
      setPickNote(t("看了 {0} 个因子：{1} 个没有可测信号被排除{2}；按 |ICIR| 取前 {3} 个算两两相关，{4}留下 {5} 个：{6}。可以手动增减，然后开始搜索。", [all.length, noise.length, unanalyzed.length ? t("，{0} 个还没算指标未参与", [unanalyzed.length]) : "t(", shortlist.length, duplicates.length ? t("去掉重复的 {0}，", [duplicates.map((d) => `${d.name}（与 ${d.of} 相关 ${d.rho.toFixed(2)}）`).join(")、")]) : "", picked.length, picked.map((p) => `${p.name}${p.weight < 0 ? t("（反向）") : ""}`).join("、")]));
    } catch (e) { setPageError(t("自动挑候选失败：{0}", [errorText(e)])); } finally { setPicking(false); }
  };
  const adoptRecommendation = (members: string[], weights: Record<string, number>) => {
    const source = searches.result?.config.factors || [];
    const picked = source.filter((f) => members.includes(f.name)).map((f) => ({ name: f.name, trace: f.trace, loop_id: f.loop_id, kind: f.kind || "factor", weight: weights[f.name] ?? f.weight ?? 1 }));
    if (!picked.length) { setPageError(t("推荐组合里的因子在这次搜索的记录里找不到，无法放进篮子。")); return; }
    basket.replace(picked);
    setTab("params");
  };
  const [source, setSource] = useState("");
  const [pageError, setPageError] = useState("");
  const [library, setLibrary] = useState<Record<string, LibraryFactor>>({});
  const info = (f: FactorWeight) => library[key(f)];
  // Every signal's date span: the library's cached analysis when a factor has one, otherwise read from its
  // result.h5 (or a prediction's pred.pkl) through the coverage endpoints, so the date warnings always apply.
  const [fetched, setFetched] = useState<Record<string, Coverage | null>>({});
  const coverageOf = (f: FactorWeight): Coverage | undefined =>
    (f.kind === "prediction" ? undefined : info(f)?.coverage || info(f)?.analysis?.coverage) || fetched[key(f)] || undefined;
  useEffect(() => {
    for (const f of basket.items) {
      if (coverageOf(f) || key(f) in fetched) continue;
      setFetched((m) => ({ ...m, [key(f)]: null }));
      const request = f.kind === "prediction" ? studio.predictionCoverage(f.trace, f.loop_id) : studio.factorCoverage(f);
      request.then((c) => setFetched((m) => ({ ...m, [key(f)]: { start: c.start, end: c.end } }))).catch(() => {});
    }
  }, [basket.items, library]); // eslint-disable-line react-hooks/exhaustive-deps

  // Default windows once the environment is known: the last year of data, and 1 + 1 years before it for a model.
  useEffect(() => {
    const end = env?.end;
    if (!end) return;
    setParams((p) => (p.start && p.end ? p : { ...p, end, start: shiftYears(end, -1) }));
  }, [env]);
  useEffect(() => {
    if (lgbm.train[0] || !params.start) return;
    const valid: [string, string] = [shiftYears(params.start, -1), dayBefore(params.start)];
    setLgbm((l) => ({ ...l, valid, train: [shiftYears(params.start, -2), dayBefore(valid[0])] }));
  }, [params.start, lgbm.train]);
  const loadLibrary = useCallback(() => studio.factorLibrary().then((list) => setLibrary(Object.fromEntries(list.map((f) => [key(f), f])))).catch(() => {}), []);
  useEffect(() => { loadLibrary(); }, [loadLibrary]);
  // "重算到最新" for every factor signal whose coverage ends before the requested end: sequential Qlib subprocesses.
  const [refreshing, setRefreshing] = useState(false);
  const staleFactors = useMemo(() => basket.items.filter((f) => (f.kind || "factor") === "factor" && coverageOf(f) && params.end && coverageOf(f)!.end < params.end), [basket.items, library, fetched, params.end]); // eslint-disable-line react-hooks/exhaustive-deps
  // Factors whose signal stops before the market data does: candidates for 重算到最新.
  const behindMarket = useMemo(() => basket.items.filter((f) => (f.kind || "factor") === "factor" && coverageOf(f) && env?.end && coverageOf(f)!.end < env.end), [basket.items, library, fetched, env?.end]); // eslint-disable-line react-hooks/exhaustive-deps
  const refreshStale = async (targets: FactorWeight[] = staleFactors) => {
    setRefreshing(true);
    try {
      for (const f of targets) {
        await studio.refreshFactor(f);
        setFetched((m) => { const next = { ...m }; delete next[key(f)]; return next; });
      }
      await loadLibrary();
      // The user asked for newer signals, so the window follows: end moves to the earliest of the recomputed
      // factors' new last day and the market's last day; start only moves if it would no longer precede it.
      const ends = await Promise.all(targets.map((f) => studio.factorCoverage(f).then((c) => c.end).catch(() => null)));
      const newEnd = [env?.end, ...ends].filter((d): d is string => !!d).sort()[0];
      if (newEnd) {
        setParams((p) => ({ ...p, end: newEnd, start: p.start && p.start < newEnd ? p.start : shiftYears(newEnd, -1) }));
        setDatesTouched(true);
        setAutoNote(t("重算完成，回测结束日已推到 {0}。", [newEnd]));
      }
    } catch (e) { setPageError(t("重算失败：{0}", [errorText(e)])); } finally { setRefreshing(false); }
  };
  useEffect(() => { if (tab === "source" && !source) studio.strategySource().then((r) => setSource(r.code)).catch((e) => setPageError(errorText(e))); }, [tab, source]);

  // Pairwise correlation of the factor signals in the basket (predictions excluded), debounced.
  const factorRefs = useMemo<FactorRef[]>(() => basket.items.filter((f) => (f.kind || "factor") === "factor").map((f) => ({ trace: f.trace, loop_id: f.loop_id, name: f.name })), [basket.items]);
  const [correlation, setCorrelation] = useState<Corr | null>(null);
  const [correlationError, setCorrelationError] = useState("");
  useEffect(() => {
    setCorrelation(null); setCorrelationError("");
    if (factorRefs.length < 2) return;
    const t = setTimeout(() => studio.factorCorrelation(factorRefs).then(setCorrelation).catch((e) => setCorrelationError(errorText(e))), 400);
    return () => clearTimeout(t);
  }, [factorRefs]);
  const maxCorr = useMemo(() => {
    if (!correlation) return 0;
    let m = 0;
    correlation.matrix.forEach((row, i) => row.forEach((v, j) => { if (i !== j) m = Math.max(m, Math.abs(v)); }));
    return m;
  }, [correlation]);
  const coverage = useMemo(() => {
    const spans = basket.items.map(coverageOf).filter((c): c is Coverage => !!c);
    if (!spans.length) return null;
    return { start: spans.reduce((a, c) => (c.start > a ? c.start : a), spans[0].start), end: spans.reduce((a, c) => (c.end < a ? c.end : a), spans[0].end) };
  }, [basket.items, library, fetched]); // eslint-disable-line react-hooks/exhaustive-deps
  const coverageUnknown = basket.items.filter((f) => !coverageOf(f)).length;
  const dateWarning = useMemo(() => {
    if (!coverage || !params.start || !params.end) return "";
    if (params.start <= coverage.start) return t("回测开始日 {0} 不晚于信号首日 {1}：策略要用前一天的评分，请把开始日往后挪。", [params.start, coverage.start]);
    if (params.end > coverage.end) return t("回测结束日 {0} 超出信号覆盖末日 {1}，会直接报错。", [params.end, coverage.end]);
    return "";
  }, [coverage, params.start, params.end]);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const addDays = (date: string, n: number) => { const d = new Date(date); d.setDate(d.getDate() + n); return iso(d); };
  // Until the user touches the dates, the window follows the signals: the default (last year of market data)
  // always runs past research factors, which stop at the experiment's own data end, so clamp instead of blocking.
  const [datesTouched, setDatesTouched] = useState(false);
  const [autoNote, setAutoNote] = useState("");
  const setDate = (k: "start" | "end", v: string) => { setDatesTouched(true); setAutoNote(""); set(k, v); };
  useEffect(() => {
    if (datesTouched || !coverage || !params.start || !params.end) return;
    const minStart = addDays(coverage.start, 1);
    let start = params.start, end = params.end;
    if (end > coverage.end) { end = coverage.end; start = shiftYears(end, -1); }  // keep the default one-year length
    if (start < minStart) start = minStart;
    if (start >= end) { start = minStart; end = coverage.end; }
    if (start !== params.start || end !== params.end) {
      setParams((p) => ({ ...p, start, end }));
      setAutoNote(t("回测区间已按信号覆盖自动调整为 {0} → {1}（信号数据到 {2}）；需要更长就先把因子重算到最新。", [start, end, coverage.end]));
    }
  }, [coverage, params.start, params.end, datesTouched]); // eslint-disable-line react-hooks/exhaustive-deps
  // The basket's factors carry the universe they were researched on; when they all agree and the form still
  // points elsewhere, follow them (benchmark included), since a CSI300 backtest of NASDAQ factors finds no data.
  useEffect(() => {
    const markets = new Set(basket.items.map((f) => library[key(f)]?.market).filter((m): m is string => !!m));
    if (markets.size !== 1) return;
    const [market] = [...markets];
    if (market === params.market) return;
    const u = universes.find((x) => x.market === market);
    setParams((p) => ({ ...p, market, ...(u ? { benchmark: u.benchmark, open_cost: u.open_cost, close_cost: u.close_cost } : {}) }));
    setPageError("");
  }, [basket.items, library, universes]); // eslint-disable-line react-hooks/exhaustive-deps
  // Rank mode gets the whole coverage; LightGBM needs history first, so the backtest takes the last third and
  // training / validation split the first two thirds 2:1 (the worker insists on train < valid < backtest).
  const fitToCoverage = () => {
    if (!coverage) return;
    if (method !== "lgbm") { setParams((p) => ({ ...p, start: addDays(coverage.start, 1), end: coverage.end })); return; }
    const days = Math.round((new Date(coverage.end).getTime() - new Date(coverage.start).getTime()) / 86400000);
    if (days < 90) { setPageError(t("信号覆盖只有 {0} 天，放不下训练、验证和回测三段；换成排名加权或移出覆盖短的信号。", [days])); return; }
    const backtestStart = addDays(coverage.start, Math.floor(days * 2 / 3));
    const trainEnd = addDays(coverage.start, Math.floor(days * 4 / 9));
    setLgbm((l) => ({ ...l, train: [coverage.start, trainEnd], valid: [addDays(trainEnd, 1), addDays(backtestStart, -1)] }));
    setParams((p) => ({ ...p, start: backtestStart, end: coverage.end }));
  };
  // The worker rejects overlapping windows outright; say so before the run.
  const orderWarning = useMemo(() => {
    if (method !== "lgbm" || !params.start) return "";
    if (lgbm.train[1] && lgbm.valid[0] && lgbm.train[1] >= lgbm.valid[0]) return t("验证窗口 {0} 开始时训练窗口（到 {1}）还没结束，两段必须前后相接。", [lgbm.valid[0], lgbm.train[1]]);
    if (lgbm.valid[1] && lgbm.valid[1] >= params.start) return t("回测开始日 {0} 不晚于验证窗口结束日 {1}：模型会在回测期上训练，后端会拒绝。", [params.start, lgbm.valid[1]]);
    return "";
  }, [method, lgbm.train, lgbm.valid, params.start]);
  // LightGBM needs every signal observed inside the training and validation windows (the worker refuses
  // an empty column rather than dropping it); name the signals that would fail before the run starts.
  const windowGaps = useMemo(() => {
    if (method !== "lgbm") return [];
    const check = (name: string, [a, b]: [string, string]) => {
      if (!a || !b) return null;
      const missing = basket.items.filter((f) => { const c = coverageOf(f); return c && (c.end < a || c.start > b); });
      return missing.length ? { name, window: [a, b] as [string, string], missing } : null;
    };
    return [check(t("训练"), lgbm.train), check(t("验证"), lgbm.valid)].filter((g): g is NonNullable<typeof g> => !!g);
  }, [method, lgbm.train, lgbm.valid, basket.items, library, fetched]); // eslint-disable-line react-hooks/exhaustive-deps
  // These would all be rejected by the worker, so the run button waits until they are fixed.
  const blocked = !!dateWarning || !!orderWarning || windowGaps.length > 0;
  const removeGapSignals = () => { for (const f of windowGaps.flatMap((g) => g.missing)) if (basket.has(f)) basket.toggle(f); };
  // Fit both windows between the shared coverage start and the day before the backtest: two thirds training, one third validation.
  const fitWindowsToCoverage = () => {
    if (!coverage || !params.start) return;
    const from = new Date(coverage.start), to = new Date(dayBefore(params.start));
    const days = Math.round((to.getTime() - from.getTime()) / 86400000);
    if (days < 60) { setPageError(t("信号覆盖起点 {0} 到回测开始前一天只有 {1} 天，放不下训练和验证窗口；请把回测开始日往后挪。", [coverage.start, days])); return; }
    const split = new Date(from); split.setDate(split.getDate() + Math.floor(days * 2 / 3));
    setLgbm((l) => ({ ...l, train: [iso(from), iso(split)], valid: [iso(new Date(split.getTime() + 86400000)), iso(to)] }));
  };

  const submit = useCallback(async () => {
    const model = method === "lgbm" ? { method: "lgbm" as const, train: [...lgbm.train] as [string, string], valid: [...lgbm.valid] as [string, string], params: { ...lgbm.params } } : { method: "rank" as const };
    const accepted = await backtests.run({ factors: basket.items.map((f) => ({ ...f, weight: Number(f.weight) })), model, ...params });
    if (accepted) { persistStudioState({ params, model }); layout.openResults(); }
  }, [method, lgbm, basket.items, params, backtests, layout]);
  const result = backtests.result;
  // History dropdowns: two-line rows (status dot, signal names over window · method · status · when, return on
  // the right) that the filter box matches by any of those words, plus ">5" / "<0" on the return.
  const statusDot = (status: string) => (
    <i className={`inline-block size-[7px] rounded-full ${status === "completed" ? "bg-success" : status === "failed" ? "bg-danger" : "bg-warning"}`} />
  );
  const signalNames = (factors: { name: string }[] | undefined) => {
    const names = (factors || []).map((f) => f.name);
    return names.length <= 2 ? names.join(" + ") || "—" : `${names.slice(0, 2).join(" + ")} +${names.length - 2}`;
  };
  const pct = (v: number | null | undefined) => (v == null ? undefined : <span className={v >= 0 ? "text-success" : "text-danger"}>{v >= 0 ? "+" : ""}{(v * 100).toFixed(1)}%</span>);
  const jobOptions = backtests.jobs.map((j) => {
    const method = j.config.model?.method === "lgbm" ? "LightGBM" : t("排名加权");
    return {
      value: j.id, label: signalNames(j.config.factors), icon: statusDot(j.status),
      description: `${j.config.start} → ${j.config.end} · ${method} · ${backtestStatusLabel(j.status)}${j.created ? ` · ${shortTime(j.created)}` : ""}`,
      trailing: pct(j.total_return), number: j.total_return == null ? null : j.total_return * 100,
      keywords: `${j.id} ${(j.config.factors || []).map((f) => f.name).join(" ")} ${j.config.market} ${universeLabel(j.config.market)} ${j.config.model?.method === "lgbm" ? t("lgbm lightgbm 训练") : t("rank 排名")} top${j.config.topk}`,
    };
  });
  const searchOptions = searches.jobs.map((j) => {
    const status = j.status === "completed" ? t("已完成") : j.status === "failed" ? t("失败") : t("运行中");
    return {
      value: j.id, label: t("{0} 候选 → {1} 个", [j.config.factors.length, j.recommended?.length ?? "?"]), icon: statusDot(j.status),
      description: `${j.config.start} → ${j.config.end} · ${status}${j.recommended?.length ? ` · ${j.recommended.slice(0, 3).join(" + ")}${j.recommended.length > 3 ? " …" : ""}` : ""}${j.created ? ` · ${shortTime(j.created)}` : ""}`,
      trailing: pct(j.validation_return), number: j.validation_return == null ? null : j.validation_return * 100,
      keywords: `${j.id} ${j.config.factors.map((f) => f.name).join(" ")} ${(j.recommended || []).join(" ")} ${j.config.market}`,
    };
  });
  const HISTORY_SEARCH_HINT = t("筛选：因子名、日期、lgbm、已完成、>5、<0…");

  const statusLine = [
    coverage ? t("覆盖 {0} → {1}", [coverage.start, coverage.end]) : "",
    factorRefs.length >= 2 ? (correlation ? t("最高相关 {0}{1}", [maxCorr.toFixed(2), maxCorr >= 0.7 ? t("（有信号重复）") : ""]) : correlationError ? t("相关性计算失败：{0}", [correlationError]) : t("计算相关性…")) : "",
  ].filter(Boolean).join(" · ");
  const lgbmKeys = ["learning_rate", "num_leaves", "max_depth", "n_estimators", "early_stopping_rounds"] as const;

  return (
    <PageFrame
      tabs={<TextTabs label={t("工作区视图")} value={tab} onChange={setTab} items={[{ key: "params", label: t("参数设置") }, { key: "search", label: t("组合搜索") }, { key: "history", label: t("历史回测"), count: backtests.jobs.length || undefined }, { key: "source", label: t("策略源码") }]} />}
      actions={tab === "search"
        ? <Btn kind="primary" disabled={searches.busy || !env?.data_ready || candidates.length < 2 || blocked} title={blocked ? t("先处理参数设置里标红的日期问题") : candidates.length < 2 ? t("至少两个因子信号") : undefined} onClick={startSearch}>{searches.busy ? t("提交中…") : t("开始搜索")}</Btn>
        : <Btn kind="primary" disabled={backtests.busy || !env?.data_ready || !basket.items.length || blocked} title={blocked ? t("先处理下面标红的日期问题") : undefined} onClick={submit}>{backtests.busy ? t("运行中…") : blocked ? t("日期有问题，无法运行") : t("运行回测")}</Btn>}
      resultsTitle={tab === "search" ? (searches.result ? t("组合搜索 {0}", [searches.result.id.slice(0, 8)]) : t("搜索结果")) : result ? t("回测 {0}", [result.id.slice(0, 8)]) : t("回测结果")}
      resultsActions={tab === "search" ? (
        <>
          {searches.jobs.length ? <SelectInput ariaLabel={t("搜索历史")} placeholder={t("搜索历史")} className="w-80 max-w-full" value={searches.selectedId || ""} onChange={(id) => { searches.select(id); layout.openResults(); }}
            options={searchOptions} searchable listWidth={440} searchPlaceholder={HISTORY_SEARCH_HINT} /> : undefined}
          {searches.result?.recommended_portfolio && <Btn onClick={() => { setSavingFrom("search"); setStrategyName(""); setSavedNote(""); }}>{t("保存为策略")}</Btn>}
        </>
      ) : (
        <>
          <SelectInput ariaLabel={t("回测历史")} placeholder={t("回测历史")} className="w-80 max-w-full" value={backtests.selectedId || ""} onChange={(id) => { backtests.select(id); layout.openResults(); }}
            options={jobOptions} searchable listWidth={440} searchPlaceholder={HISTORY_SEARCH_HINT} />
          {result?.metrics && <Btn onClick={() => { setSavingFrom("backtest"); setStrategyName(""); setSavedNote(""); }}>{t("保存为策略")}</Btn>}
          {result?.metrics && <Btn kind="text" onClick={() => download(`backtest-${result.id.slice(0, 8)}.json`, JSON.stringify(result, null, 2), "application/json")}>{t("导出 JSON")}</Btn>}
        </>
      )}
      results={
        <div className="flex flex-col gap-3">
          {savingFrom && <Note tone="info" actions={saveForm}>{savingFrom === "search" ? t("把搜索推荐的组合保存为策略，以后在「策略」页跟踪它。") : t("把这次回测的组合、参数和结果保存为策略，以后在「策略」页跟踪它。")}</Note>}
          {savedNote && <Note tone="info" actions={<><Btn onClick={() => navigate(workspace.path("/strategies"))}>{t("去策略页")}</Btn><Btn kind="text" onClick={() => setSavedNote("")}>{t("关闭")}</Btn></>}>{savedNote}</Note>}
          {tab === "search"
            ? (searches.result ? <SearchResultView result={searches.result} onAdopt={adoptRecommendation} /> : <Hint>{t("开始搜索后在这里看搜索路径和推荐组合。")}</Hint>)
            : result ? <BacktestResultView result={result} onDiagnose={backtests.diagnose} /> : <Hint>{t("运行回测后在这里看指标、净值曲线、持仓与成交。")}</Hint>}
        </div>}
    >
      {(backtests.error || pageError) && <Note tone="bad" actions={<Btn kind="text" onClick={() => { backtests.setError(""); setPageError(""); }}>{t("关闭")}</Btn>}>{backtests.error || pageError}</Note>}
      {!env && <Note>{t("后端未连接，无法回测。运行 scripts/start-backend.sh 后刷新。")}</Note>}
      {env && !env.data_ready && <Note>{t("Qlib 数据未就绪（{0}），无法回测。", [env.provider_uri])}</Note>}

      {tab === "params" ? (
        <>
          <Block title={t("回测参数")} note={`${params.start || "?"} → ${params.end || "?"} · ${params.market}`}>
            <FieldGrid min={140}>
              <Field label={t("开始")}><TextInput type="date" value={params.start} onChange={(v) => setDate("start", v)} /></Field>
              <Field label={t("结束")}><TextInput type="date" value={params.end} onChange={(v) => setDate("end", v)} /></Field>
              <Field label={t("股票池")}><SelectInput value={params.market} onChange={(v) => { const u = universes.find((x) => x.market === v); setParams((p) => ({ ...p, market: v, ...(u ? { benchmark: u.benchmark, open_cost: u.open_cost, close_cost: u.close_cost } : {}) })); }} options={universes.length ? universes.map((u) => ({ value: u.market as Market, label: universeLabel(u.market), hint: u.members ? t("{0} 只 · {1}", [u.members, u.benchmark]) : u.benchmark })) : ["csi300", "csi500", "all"].map((m) => ({ value: m as Market, label: universeLabel(m) }))} /></Field>
              <Field label={t("基准")}><TextInput value={params.benchmark} onChange={(v) => set("benchmark", v)} /></Field>
              <Field label={t("持股数")} hint={t("每天按评分持有前 topk 只")}><NumberInput value={params.topk} onChange={(v) => set("topk", v)} min={1} max={500} /></Field>
              <Field label={t("每日换出")} hint={t("每天最多换出 n_drop 只")}><NumberInput value={params.n_drop} onChange={(v) => set("n_drop", v)} min={0} max={500} /></Field>
              <Field label={t("初始资金")}><NumberInput value={params.account} onChange={(v) => set("account", v)} min={1000} step={100000} /></Field>
              <Field label={t("买入费率")} hint={t("0.0005 = 万分之五")}><NumberInput value={params.open_cost} onChange={(v) => set("open_cost", v)} min={0} max={0.1} step={0.0001} /></Field>
              <Field label={t("卖出费率")} hint={universes.find((u) => u.market === params.market)?.region === "us" ? t("美股经纪佣金接近零，默认万分之一") : t("0.0015 含印花税")}><NumberInput value={params.close_cost} onChange={(v) => set("close_cost", v)} min={0} max={0.1} step={0.0001} /></Field>
              <Field label={t("信号合成")} hint={t("排名加权：截面百分位排名按权重求和；LightGBM：学信号与次日收益的关系，验证集早停")}>
                <SelectInput value={method} onChange={setMethod} options={[{ value: "rank", label: t("排名加权") }, { value: "lgbm", label: t("训练 LightGBM") }]} />
              </Field>
            </FieldGrid>
            {autoNote && !dateWarning && (
              <div style={{ marginTop: 12 }}>
                <Note tone="info" actions={behindMarket.length > 0 ? <Btn disabled={refreshing} onClick={() => refreshStale(behindMarket)}>{refreshing ? t("重算中…") : t("把 {0} 个因子重算到最新", [behindMarket.length])}</Btn> : undefined}>{autoNote}</Note>
              </div>
            )}
            {dateWarning && (
              <div style={{ marginTop: 12 }}>
                <Note tone="bad" actions={coverage && <>
                  {staleFactors.length > 0 && <Btn disabled={refreshing} onClick={() => refreshStale()}>{refreshing ? t("重算中…") : t("把 {0} 个因子重算到最新", [staleFactors.length])}</Btn>}
                  <Btn onClick={fitToCoverage}>{method === "lgbm" ? t("按覆盖区间重排三段") : t("按覆盖区间填日期")}</Btn>
                </>}>{dateWarning}</Note>
              </div>
            )}
            {orderWarning && <div style={{ marginTop: 12 }}><Note tone="bad" actions={coverage && <Btn onClick={fitToCoverage}>{t("按覆盖区间重排三段")}</Btn>}>{orderWarning}</Note></div>}
            {windowGaps.map((g) => (
              <div key={g.name} style={{ marginTop: 12 }}>
                <Note tone="bad" actions={<><Btn onClick={removeGapSignals}>{t("移出这些信号")}</Btn><Btn onClick={fitWindowsToCoverage}>{t("把窗口挪进覆盖区间")}</Btn></>}>
                  {t("{0}窗口 {1} → {2} 里没有 {3} 的数据，LightGBM 会直接报错。", [g.name, g.window[0], g.window[1], g.missing.map((f) => `${f.name}（${coverageOf(f)!.start} → ${coverageOf(f)!.end}）`).join(t("、"))])}
                </Note>
              </div>
            ))}
          </Block>
          {method === "lgbm" && (
            <Block title="LightGBM" note={t("训练集学关系，验证集早停")}>
              <FieldGrid min={140}>
                <Field label={t("训练开始")}><TextInput type="date" value={lgbm.train[0]} onChange={(v) => setLgbm((l) => ({ ...l, train: [v, l.train[1]] }))} /></Field>
                <Field label={t("训练结束")}><TextInput type="date" value={lgbm.train[1]} onChange={(v) => setLgbm((l) => ({ ...l, train: [l.train[0], v] }))} /></Field>
                <Field label={t("验证开始")}><TextInput type="date" value={lgbm.valid[0]} onChange={(v) => setLgbm((l) => ({ ...l, valid: [v, l.valid[1]] }))} /></Field>
                <Field label={t("验证结束")}><TextInput type="date" value={lgbm.valid[1]} onChange={(v) => setLgbm((l) => ({ ...l, valid: [l.valid[0], v] }))} /></Field>
                {lgbmKeys.map((k) => <Field key={k} label={k}><NumberInput value={lgbm.params[k]} onChange={(v) => setLgbm((l) => ({ ...l, params: { ...l.params, [k]: v } }))} /></Field>)}
              </FieldGrid>
            </Block>
          )}
          <Block title={t("信号篮")} count={basket.items.length} note={statusLine} noteTone={maxCorr >= 0.7 ? "bad" : "ok"}>
            {basket.items.length ? (
              <>
                <Table label={t("信号篮")} columns={[{ label: t("信号") }, { label: t("来源"), width: 200, optional: true }, { label: "IC", num: true, width: 82 }, { label: "Rank IC", num: true, width: 82 }, { label: t("覆盖"), width: 156, optional: true }, { label: t("权重"), num: true, width: 84 }, { label: "", width: 52 }]}
                  rows={basket.items.map((f) => ({
                    key: key(f),
                    cells: [
                      <span key="n" className="mm-mono mm-name">{f.name}</span>,
                      <span key="s" className="mm-dim block truncate">{t("{0} · 第 {1} 轮", [shortName(f.trace), f.loop_id + 1])}</span>,
                      <Num key="ic" value={info(f)?.analysis?.ic.mean} />,
                      <Num key="ric" value={info(f)?.analysis?.rank_ic.mean} />,
                      <span key="cov" className="mm-mono mm-dim">{coverageOf(f) ? `${coverageOf(f)!.start.slice(0, 7)} → ${coverageOf(f)!.end.slice(0, 7)}` : key(f) in fetched ? t("读取中…") : t("未知")}</span>,
                      <NumberInput key="w" className="mm-weight" ariaLabel={t("权重")} step={0.5} value={f.weight} disabled={method === "lgbm"} onChange={(v) => basket.setWeight(f, v)} />,
                      <Link key="x" onClick={() => basket.toggle(f)}>{t("移除")}</Link>,
                    ],
                  }))} />
                <P>
                  {t("TopkDropoutStrategy · 前一日评分 · 当日收盘成交 · 权重为负 = 反向使用")}{method === "lgbm" ? t("（LightGBM 模式下权重不生效）") : ""}
                  {coverageUnknown ? t(" · {0} 个信号的覆盖区间未知，未计入", [coverageUnknown]) : ""} · <Link href={workspace.href("/factors")}>{t("去因子库增减")}</Link>
                </P>
              </>
            ) : (
              <Empty>{t("还没有选信号。去")} <Link href={workspace.href("/factors")}>{t("因子库")}</Link> {t("勾选，或在研究轮次里点“用 N 个因子回测”。")}</Empty>
            )}
          </Block>
        </>
      ) : tab === "history" ? (
        <Block title={t("历史回测")} count={backtests.jobs.length} note={t("点一行在右栏查看结果")}>
          {backtests.jobs.length ? (
            <Table label={t("历史回测")} columns={[{ label: "", width: 18 }, { label: t("信号"), width: "34%" }, { label: t("区间") }, { label: t("合成"), width: 80, optional: true }, { label: t("收益"), num: true, width: 72 }, { label: t("状态"), width: 72 }, { label: t("时间"), width: 96, optional: true }]}
              rows={backtests.jobs.map((j) => ({
                key: j.id, selected: j.id === backtests.selectedId, onClick: () => { backtests.select(j.id); layout.openResults(); },
                cells: [
                  statusDot(j.status),
                  <span key="n" className="mm-mono block truncate" title={(j.config.factors || []).map((f) => f.name).join(", ")}>{signalNames(j.config.factors)}</span>,
                  <span key="w" className="mm-mono mm-dim">{j.config.start} → {j.config.end}</span>,
                  <span key="m" className="mm-dim">{j.config.model?.method === "lgbm" ? "LightGBM" : t("排名加权")}</span>,
                  j.total_return == null ? <span key="r" className="mm-dim">—</span> : <Num key="r" value={j.total_return} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />,
                  <StatusTag key="s" status={backtestStatusLabel(j.status)} />,
                  <span key="t" className="mm-mono mm-dim">{j.created ? shortTime(j.created) : ""}</span>,
                ],
              }))} />
          ) : <Empty>{t("还没有回测。")}</Empty>}
        </Block>
      ) : tab === "search" ? (
        <>
          {searches.error && <Note tone="bad" actions={<Btn kind="text" onClick={() => searches.setError("")}>{t("关闭")}</Btn>}>{searches.error}</Note>}
          <Block title={t("搜索设置")} note={t("{0} → {1} · {2} · 参数沿用「参数设置」", [params.start || "?", params.end || "?", params.market])}>
            <FieldGrid min={160}>
              <Field label={t("优化目标")} hint={t("搜索区间上比较各组合的指标")}><SelectInput value={objective} onChange={setObjective} options={[{ value: "sharpe", label: t("夏普") }, { value: "total_return", label: t("总收益") }]} /></Field>
              <Field label={t("区间划分")}><span className="text-xs" style={{ lineHeight: "28px" }}>{t("前 2/3 搜索 · 后 1/3 验证")}</span></Field>
              <Field label={t("信号合成")}><span className="text-xs" style={{ lineHeight: "28px" }}>{t("排名加权（按篮内权重）")}</span></Field>
            </FieldGrid>
            <P>{t("候选是信号篮里的因子（模型预测不参与）。先每个单独跑，再逐个加入、逐个剔除，在搜索区间上按目标挑选；推荐组合最后在验证区间上复核。{0} 个候选最多约 {1} 次回测。", [candidates.length, candidates.length + (candidates.length * (candidates.length - 1)) / 2 + candidates.length + 3])}</P>
          </Block>
          <Block title={t("候选信号")} count={candidates.length} note={<><Link href={workspace.href("/factors?return=search")}>{t("去因子库增减")}</Link>{candidates.length < 2 ? t(" · 至少两个") : ""}</>}>
            <div className="mm-row" style={{ marginBottom: 12 }}>
              <Btn disabled={picking} onClick={() => autoPick()}>{picking ? (analyzeProgress || t("挑选中…")) : t("自动挑候选")}</Btn>
              <span className="mm-dim" style={{ fontSize: 12 }}>{t("从整个因子库按 |ICIR| 排序，排除噪声，两两相关 ≥ {0} 只留一个，最多 8 个，IC 为负的自动反向；会替换当前篮子。", [DUPLICATE_CORR])}</span>
            </div>
            {pickNote && (
              <div style={{ marginBottom: 12 }}>
                <Note tone="info" actions={pendingAnalysis.length > 0 ? <Btn disabled={picking} onClick={analyzeThenPick}>{t("先算这 {0} 个指标再挑（约 {1} 分钟）", [pendingAnalysis.length, Math.ceil(pendingAnalysis.length / 6)])}</Btn> : undefined}>{pickNote}</Note>
              </div>
            )}
            {candidates.length ? (
              <Table label={t("候选信号")} columns={[{ label: t("信号") }, { label: t("来源"), width: 200, optional: true }, { label: t("权重"), num: true, width: 70 }, { label: t("覆盖"), width: 156, optional: true }]}
                rows={candidates.map((f) => ({ key: key(f), cells: [
                  <span key="n" className="mm-mono mm-name">{f.name}</span>,
                  <span key="s" className="mm-dim block truncate">{t("{0} · 第 {1} 轮", [shortName(f.trace), f.loop_id + 1])}</span>,
                  String(f.weight),
                  <span key="c" className="mm-mono mm-dim">{coverageOf(f) ? `${coverageOf(f)!.start.slice(0, 7)} → ${coverageOf(f)!.end.slice(0, 7)}` : "—"}</span>,
                ] }))} />
            ) : null}
            {candidates.length < 2 && (
              <div style={{ marginTop: candidates.length ? 12 : 0 }}>
                <Note tone="info" actions={<Btn onClick={() => navigate(workspace.path("/factors?return=search"))}>{t("去因子库勾选")}</Btn>}>
                  搜索至少需要两个因子作为候选{candidates.length ? t("，现在只有 {0} 个", [candidates.length]) : "t("}。勾好后因子库底部的")回组合搜索"会带你回到这里。
                </Note>
              </div>
            )}
          </Block>
          <Block title={t("搜索记录")} count={searches.jobs.length}>
            {searches.jobs.length ? (
              <Table label={t("搜索记录")} columns={[{ label: t("时间"), width: 100 }, { label: t("候选 → 推荐"), width: 110 }, { label: t("区间") }, { label: t("目标"), width: 60, optional: true }, { label: t("验证收益"), num: true, width: 90 }, { label: t("状态"), width: 64 }]}
                rows={searches.jobs.map((j) => ({ key: j.id, selected: j.id === searches.selectedId, onClick: () => { searches.select(j.id); layout.openResults(); }, cells: [
                  <span key="t" className="mm-mono mm-dim">{shortTime(j.created)}</span>,
                  <span key="n" className="mm-mono">{j.config.factors.length} → {j.recommended?.length ?? "—"}</span>,
                  <span key="w" className="mm-mono mm-dim">{j.config.start} → {j.config.end}</span>,
                  <span key="o" className="mm-dim">{j.config.search?.objective === "total_return" ? t("收益") : t("夏普")}</span>,
                  <Num key="v" value={j.validation_return} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />,
                  <StatusTag key="s" status={j.status === "completed" ? t("已完成") : j.status === "failed" ? t("失败") : t("运行中")} />,
                ] }))} />
            ) : <Empty>{t("还没有搜索记录。")}</Empty>}
          </Block>
        </>
      ) : (
        <Block title="studio_worker.py" note={t("只读 · 服务端执行")}><pre className="mm-pre">{source || t("加载中…")}</pre></Block>
      )}
    </PageFrame>
  );
}
