import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as studio from "../api/studio";
import type { ExperimentSummary, Universe } from "../api/studio";
import { universeLabel } from "../api/studio";
import type { RoundView } from "../hooks/rounds";
import { EXPERIMENT_STATUS_LABELS, mergeExperiments, shortTime } from "../hooks/experiments";
import { persistStudioState, restoreStudioState } from "../hooks/studioStorage";
import { errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { InteractionPanel, RoundDetail } from "../components/RoundViews";
import { Block, Btn, Empty, Field, FieldGrid, Note, NumberInput, P, SelectInput, StatusTag, Table, TextInput, TextTabs } from "../components/minimal";
import type { Row } from "../components/minimal";
import { Section } from "../components/Section";
import { Hint, MetricGrid } from "../components/widgets";
import { LiveStatus, RunSummary, StepStrip, useNow } from "../components/Progress";
import { fmtDuration, progressLine, roundProgress } from "../hooks/progress";

interface Mode {
  name: string; desc: string; value: string; loops: boolean; duration: boolean; objective: boolean; input?: "reports" | "paper";
  /** What one round does, in order, and what the run leaves behind: shown in the results column while the form is open. */
  steps: string[]; output: string;
}
// The scenarios the log server's /upload accepts; Data Science needs an MLE-bench dataset, so it stays in the Playground.
const MODES: Mode[] = [
  { name: "因子研发", desc: "假设 → 因子实现 → Qlib 评估", value: "Finance Data Building", loops: true, duration: true, objective: true,
    steps: ["Agent 根据研究方向和前几轮的反馈提出一个假设，并拆成几个因子任务", "为每个因子写 factor.py，在 daily_pv.h5 上计算出 result.h5，通不过检查就自己改", "把新因子和基础特征一起交给 Qlib：LightGBM 训练，TopkDropout 回测", "对照上一轮的指标写反馈，决定接受还是拒绝这个假设，进入下一轮"],
    output: "每一轮的因子都进因子库，可以挑进组合篮回测；训练出的模型预测（pred.pkl）也能直接当信号回测。" },
  { name: "模型研发", desc: "模型实现与迭代验证", value: "Finance Model Implementation", loops: true, duration: true, objective: true,
    steps: ["Agent 提出一个模型结构假设（网络、损失、训练方式）", "写出 PyTorch 模型代码并做形状与训练检查", "在 Qlib 的固定特征集上训练、回测", "对照上一轮写反馈，决定接受还是拒绝，进入下一轮"],
    output: "每一轮的模型预测（pred.pkl）可以在组合回测里当信号使用。" },
  { name: "因子 × 模型联合", desc: "RD-Agent 原生联合研究循环", value: "Finance Whole Pipeline", loops: true, duration: true, objective: true,
    steps: ["Agent 每轮自己决定这一轮改因子还是改模型", "按选择走因子研发或模型研发的实现与评估流程", "反馈同时看因子贡献和模型效果，进入下一轮"],
    output: "因子进因子库，模型预测可当信号，两者都能回测。" },
  { name: "研报因子提取", desc: "上传研报 PDF → 提取因子 → 实现与 Qlib 评估", value: "Finance Data Building (Reports)", loops: false, duration: true, objective: false, input: "reports",
    steps: ["读取上传的研报，抽出其中定义的因子（名称、公式、变量）", "逐个实现成 factor.py 并计算 result.h5", "交给 Qlib 评估"],
    output: "抽出的因子进因子库。这个场景不迭代假设，跑完一遍就结束。" },
  { name: "论文模型实现", desc: "上传论文 PDF 或给链接 → 提取模型结构 → 实现", value: "General Model Implementation", loops: false, duration: false, objective: false, input: "paper",
    steps: ["读取论文，抽出模型结构与训练细节", "实现成可运行的模型代码并做检查"],
    output: "产出是模型代码，没有 Qlib 评估，也不进因子库。" },
];

/** A round's one-line title: the first clause of its hypothesis (full text in the tooltip). */
function roundTitle(round: RoundView) {
  const text = (round.hypothesis.hypothesis || "").trim();
  if (!text) return <span className="mm-dim">（等待假设）</span>;
  const clause = text.split(/(?<=[.。;；:：!?！？])\s+/)[0].replace(/[.。;；:：]$/, "");
  return clause.length > 48 ? clause.slice(0, 48) + "…" : clause;
}

export function ResearchPage() {
  const { env, trace, basket, layout, workspace } = useStudio();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState(search.get("trace") ? "rounds" : search.get("new") || !trace.traceId ? "new" : "rounds");
  const saved0 = restoreStudioState();
  const [form, setForm] = useState(() => ({ scenario: MODES[0].value, loops: 3, duration: 2, objective: saved0.objective || "", link: "", market: "csi300",
    confirmMode: (saved0.confirm?.mode as string) || "hypothesis", confirmTimeout: typeof saved0.confirm?.timeout === "number" ? saved0.confirm.timeout as number : 30 }));
  const [universes, setUniverses] = useState<Universe[]>([]);
  useEffect(() => { studio.universes().then(setUniverses).catch(() => {}); }, []);
  // The form's universe must belong to this workspace; fall back to its first one (e.g. nasdaq100 for US).
  useEffect(() => { if (universes.length && !universes.some((u) => u.market === form.market)) setForm((f) => ({ ...f, market: universes[0].market })); }, [universes]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosenUniverse = universes.find((u) => u.market === form.market);
  const [files, setFiles] = useState<File[]>([]);
  const [roundId, setRoundId] = useState("");
  const [predictionLoops, setPredictionLoops] = useState<Set<number>>(new Set());
  const [summaries, setSummaries] = useState<ExperimentSummary[]>([]);
  const mode = MODES.find((m) => m.value === form.scenario) || MODES[0];
  const scenarioName = (id: string) => MODES.find((m) => id.startsWith(m.value + "/"))?.name || id.split("/")[0];

  // The experiment list: ids from /traces, summaries from /studio/experiments. Re-read when the id list or
  // the selected run's status changes, and every 15 s while any run is live.
  const loadSummaries = useCallback(() => { studio.experiments().then(setSummaries).catch(() => {}); }, []);
  useEffect(() => { loadSummaries(); }, [loadSummaries, trace.traceIds, trace.status]);
  const anyLive = summaries.some((s) => s.status === "running" || s.status === "starting");
  useEffect(() => {
    if (!anyLive) return;
    const t = setInterval(loadSummaries, 15000);
    return () => clearInterval(t);
  }, [anyLive, loadSummaries]);
  const experiments = useMemo(() => mergeExperiments(trace.traceIds, summaries), [trace.traceIds, summaries]);

  useEffect(() => { if (search.get("new")) setTab("new"); }, [search]);
  // The form's explanation lives in the results column, so switching to the form brings that column up.
  useEffect(() => { if (tab === "new") layout.openResults(); }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { persistStudioState({ objective: form.objective, confirm: { mode: form.confirmMode, timeout: form.confirmTimeout } }); }, [form.objective, form.confirmMode, form.confirmTimeout]);
  // The URL's ?trace= seeds the first load only; afterwards the user's pick wins on reload.
  useEffect(() => {
    const wanted = search.get("trace") || trace.traceId;
    if (wanted && (wanted !== trace.traceId || !trace.events.length)) trace.select(wanted);
    if (search.get("trace")) { setSearch({}, { replace: true }); setTab("rounds"); layout.openResults(); }
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
  // Which rounds recorded a Qlib model prediction lives on disk, so it comes from /studio/rounds.
  useEffect(() => {
    setPredictionLoops(new Set());
    if (!trace.traceId) return;
    const id = trace.traceId;
    studio.rounds(id).then((rounds) => { if (id === trace.traceId) setPredictionLoops(new Set(rounds.filter((r) => r.prediction).map((r) => r.loop_id))); }).catch(() => {});
  }, [trace.traceId, trace.rounds.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (trace.interaction) layout.openResults(); }, [trace.interaction]); // eslint-disable-line react-hooks/exhaustive-deps

  const status = trace.busy && !trace.events.length ? "加载中" : trace.status;
  const activeRound: RoundView | null = trace.rounds.find((r) => r.id === roundId) || trace.rounds[trace.rounds.length - 1] || null;
  // Step timelines of the selected experiment's rounds; the clock only ticks while it runs.
  const now = useNow(1000, trace.active);
  const progress = useMemo(() => roundProgress(trace.events, trace.active, now), [trace.events, trace.active, now]);
  const progressOf = (id: string) => progress.find((p) => p.id === id);
  const hasPrediction = (round: RoundView) => predictionLoops.has(Number(round.id));

  const pick = useCallback(async (id: string) => {
    setRoundId("");
    if (search.get("trace") || search.get("new")) setSearch({}, { replace: true });
    if (id) await trace.select(id); else trace.clear();
  }, [trace, search, setSearch]);

  const start = useCallback(async () => {
    if (mode.loops && (!Number.isInteger(form.loops) || form.loops < 1 || form.loops > 30)) { trace.setError("研究轮数应为 1–30。"); return; }
    if (mode.duration && !(form.duration >= 0.1 && form.duration <= 24)) { trace.setError("运行时限应为 0.1–24 小时。"); return; }
    if (mode.input === "reports" && !files.length) { trace.setError("请至少上传一份研报 PDF。"); return; }
    if (mode.input === "paper" && !files.length && !/^https?:\/\//.test(form.link.trim())) { trace.setError("请上传论文 PDF，或填写以 http(s) 开头的链接。"); return; }
    const data = new FormData();
    data.append("scenario", form.scenario);
    if (mode.loops) data.append("loops", String(form.loops));
    if (mode.duration) data.append("all_duration", String(form.duration));
    if (form.scenario.startsWith("Finance")) data.append("market", form.market);
    if (mode.loops) { data.append("confirm_mode", form.confirmMode); data.append("confirm_timeout", String(form.confirmTimeout)); }
    if (mode.objective && form.objective.trim()) data.append("objective", form.objective.trim());
    for (const file of files) data.append("files", file, file.name);
    if (mode.input === "paper" && !files.length) data.append("files", form.link.trim()); // the server reads a link from the files field
    try {
      trace.setBusy(true);
      const { id } = await studio.startResearch(data);
      trace.registerLaunched(id);
      setTab("rounds");
      if (search.get("new")) setSearch({}, { replace: true });
      await trace.select(id, true);
    } catch (e) { trace.setError(errorText(e)); } finally { trace.setBusy(false); }
  }, [mode, form, files, trace, search, setSearch]);

  // "继续研究 N 轮": restore the experiment's loop from its saved session and run N more rounds into the same trace.
  const [moreLoops, setMoreLoops] = useState(3);
  const [resuming, setResuming] = useState(false);
  const canContinue = !!trace.traceId && !trace.active && MODES.some((m) => m.loops && trace.traceId.startsWith(m.value + "/"));
  const continueResearch = useCallback(async () => {
    if (!canContinue) return;
    if (!Number.isInteger(moreLoops) || moreLoops < 1 || moreLoops > 30) { trace.setError("继续的轮数应为 1–30。"); return; }
    setResuming(true);
    try {
      const id = trace.traceId;
      await studio.resumeResearch(id, moreLoops, { mode: form.confirmMode, timeout: form.confirmMode === "auto" ? 0 : form.confirmTimeout });
      setRoundId("");
      await trace.select(id, true);
      loadSummaries();
      layout.openResults();
    } catch (e) { trace.setError(errorText(e)); } finally { setResuming(false); }
  }, [canContinue, moreLoops, form.confirmMode, form.confirmTimeout, trace, loadSummaries, layout]);

  const sendToBacktest = (round: RoundView) => { basket.addRound(trace.traceId, Number(round.id), round.factors); navigate(workspace.path("/backtest")); };
  const sendPrediction = (round: RoundView) => { basket.addPrediction(trace.traceId, Number(round.id)); navigate(workspace.path("/backtest")); };

  // Rounds of the expanded experiment, nested under its row; the states before the first round are spelled out.
  const roundsBody = () => {
    if (trace.busy && !trace.events.length) return <Empty>加载中…</Empty>;
    if (status === "启动中") return <Empty>Agent 正在初始化，第一条事件到达前这里是空的，通常几十秒。</Empty>;
    if (status === "未加载") return <Note tone="info">服务端没有加载这个实验的事件。<small>已结束的实验需要后端以 UI_LOAD_LEGACY_PICKLE_TRACES=true 启动才可回看。</small></Note>;
    if (status === "已结束" && !trace.rounds.length) return <Note>这个实验的进程已结束，且没有留下任何事件；看日志里的报错。</Note>;
    if (status === "运行中" && !trace.rounds.length) return <Empty>研究已启动，等待第一轮假设…</Empty>;
    return (
      <>
      <Table label="研究轮次" columns={[{ label: "轮", width: 36 }, { label: "假设" }, { label: "阶段", width: 200, optional: true }, { label: "因子", num: true, width: 48, optional: true }, { label: "状态", width: 88 }]}
        rows={trace.rounds.map((round) => ({
          key: round.id, selected: round.id === (activeRound?.id ?? ""), onClick: () => { setRoundId(round.id); layout.openResults(); },
          cells: [
            <span key="n" className="mm-mono mm-dim">{Number(round.id) + 1}</span>,
            <span key="h" className="block truncate" title={round.hypothesis.hypothesis}>{roundTitle(round)}</span>,
            <span key="s" className="flex items-center gap-2.5">{progressOf(round.id) && <StepStrip round={progressOf(round.id)!} now={now} compact />}<span className="mm-mono mm-dim" style={{ fontSize: 11 }}>{progressOf(round.id)?.elapsed != null ? fmtDuration(progressOf(round.id)!.elapsed) : ""}</span></span>,
            round.factors.length ? String(round.factors.length) : <span key="f" className="mm-dim">—</span>,
            <StatusTag key="st" status={round.status} />,
          ],
        }))} />
      {canContinue && (
        <div className="mm-row" style={{ marginTop: 10 }}>
          <span className="mm-dim" style={{ fontSize: 12 }}>继续研究</span>
          <NumberInput ariaLabel="继续的轮数" value={moreLoops} onChange={setMoreLoops} min={1} max={30} className="mm-weight" />
          <span className="mm-dim" style={{ fontSize: 12 }}>轮，</span>
          <SelectInput ariaLabel="确认方式" className="w-32" value={form.confirmMode} onChange={(v) => setForm((f) => ({ ...f, confirmMode: v }))} options={[
            { value: "hypothesis", label: "只确认假设" }, { value: "all", label: "全部确认" }, { value: "auto", label: "全自动" },
          ]} />
          {form.confirmMode !== "auto" && (
            <>
              <span className="mm-dim" style={{ fontSize: 12 }}>无人处理</span>
              <NumberInput ariaLabel="无人处理超时（分钟）" value={form.confirmTimeout} onChange={(v) => setForm((f) => ({ ...f, confirmTimeout: v }))} min={0} max={1440} className="mm-weight" />
              <span className="mm-dim" style={{ fontSize: 12 }}>分钟后自动继续{form.confirmTimeout === 0 ? "（0 = 一直等）" : ""}</span>
            </>
          )}
          <Btn kind="primary" disabled={resuming} onClick={continueResearch}>{resuming ? "启动中…" : `继续研究 ${moreLoops} 轮`}</Btn>
          <span className="mm-dim" style={{ fontSize: 12 }}>从最后一个快照接着跑，Agent 记得前面每一轮的假设和反馈；新轮次追加到这个实验里。</span>
        </div>
      )}
      </>
    );
  };
  // A row flashes when its round count grows (a round just finished); remembered per experiment.
  const roundsSeen = useRef<Record<string, number>>({});
  const [flash, setFlash] = useState<Record<string, number>>({});
  useEffect(() => {
    const next: Record<string, number> = {};
    for (const e of experiments) {
      const prev = roundsSeen.current[e.id];
      if (e.rounds != null && prev != null && e.rounds > prev) next[e.id] = Date.now();
      if (e.rounds != null) roundsSeen.current[e.id] = e.rounds;
    }
    if (Object.keys(next).length) setFlash((f) => ({ ...f, ...next }));
  }, [experiments]);
  const experimentRows: Row[] = experiments.flatMap((e) => {
    const open = e.id === trace.traceId;
    const row: Row = {
      key: e.id, expanded: open, className: flash[e.id] && Date.now() - flash[e.id] < 3000 ? "row-flash" : undefined,
      onClick: () => { if (open) pick(""); else { pick(e.id); layout.openResults(); } },
      cells: [
        <span key="c" className="mm-caret" data-open={open || undefined} aria-hidden />,
        <span key="n" className="block truncate" title={e.hypothesis || undefined}>{shortName(e.id)}</span>,
        <span key="sc" className="mm-dim">{scenarioName(e.id)}{e.market && e.market !== "csi300" ? ` · ${universeLabel(e.market)}` : ""}</span>,
        e.rounds == null ? <span key="r" className="mm-dim">—</span> : String(e.rounds),
        e.accepted == null ? <span key="a" className="mm-dim">—</span> : String(e.accepted),
        e.waiting && (e.status === "running" || e.status === "starting")
          ? <span key="st" className="flex items-center gap-2 text-[11px] text-accent" title="等你确认"><i className="live__dot" aria-hidden />等你确认</span>
          : open && trace.active && progress.length
          ? <span key="st" className="flex items-center gap-2 text-[11px]" title={progressLine(progress, now)}><i className="live__dot" aria-hidden /><span className="truncate">{progressLine(progress, now)}</span></span>
          : <StatusTag key="st" status={open && trace.events.length ? status : EXPERIMENT_STATUS_LABELS[e.status]} />,
        <span key="u" className="mm-mono mm-dim">{shortTime(e.updated)}</span>,
      ],
    };
    return open ? [row, { key: `${e.id}:rounds`, span: true, cells: [roundsBody()] }] : [row];
  });

  return (
    <PageFrame
      tabs={<TextTabs label="工作区视图" value={tab} onChange={setTab} items={[{ key: "rounds", label: "研究轮次" }, { key: "new", label: "新建研究" }]} />}
      actions={tab === "rounds" && (
        <>
          {trace.active && <Btn kind="danger" disabled={trace.busy} onClick={trace.stop}>停止</Btn>}
          {trace.traceId && <Btn onClick={() => window.open(studio.stdoutUrl(trace.traceId), "_blank")}>日志</Btn>}
          <Btn onClick={() => { trace.loadTraces(); loadSummaries(); }}>刷新</Btn>
        </>
      )}
      resultsTitle={tab === "new" ? mode.name : activeRound ? `第 ${Number(activeRound.id) + 1} 轮` : "轮次详情"}
      resultsActions={tab === "new" ? undefined : activeRound ? (
        <>
          {activeRound.factors.length > 0 && <Btn kind="primary" onClick={() => sendToBacktest(activeRound)}>用 {activeRound.factors.length} 个因子回测 →</Btn>}
          {hasPrediction(activeRound) && <Btn onClick={() => sendPrediction(activeRound)}>用模型预测回测 →</Btn>}
        </>
      ) : undefined}
      results={tab === "new" ? (
        <div className="flex flex-col gap-3">
          <Section title="这个场景做什么" note={mode.desc}>
            <ol className="m-0 flex list-decimal flex-col gap-1 pl-4 text-xs">{mode.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            <Hint>{mode.output}</Hint>
          </Section>
          <Section title="会用到的环境" note={env?.data_ready ? "就绪" : "未就绪"}>
            <MetricGrid columns={2} items={[
              { label: "研究模型", value: env?.chat_model?.replace("deepseek/", "") || "未配置" },
              { label: "Qlib 数据", value: env ? `${env.start || "—"} → ${env.end || "—"}` : "后端未连接" },
              ...(form.scenario.startsWith("Finance") ? [{ label: "股票池", value: `${universeLabel(form.market)} · 基准 ${chosenUniverse?.benchmark || "SH000300"}` }] : []),
              ...(mode.loops ? [{ label: "轮数", value: String(form.loops) }, { label: "确认", value: `${{ hypothesis: "只确认假设", all: "全部确认", auto: "全自动" }[form.confirmMode] || form.confirmMode}${form.confirmMode !== "auto" && form.confirmTimeout ? ` · ${form.confirmTimeout} 分钟无人则自动继续` : form.confirmMode !== "auto" ? " · 一直等" : ""}` }] : []),
              ...(mode.duration ? [{ label: "时限", value: `${form.duration} 小时` }] : []),
            ]} />
            {mode.input && <Hint>{files.length ? `已选 ${files.length} 个文件：${files.map((f) => f.name).join("，")}` : mode.input === "reports" ? "还没有上传研报。" : form.link.trim() ? `将读取链接 ${form.link.trim()}` : "还没有上传论文或填写链接。"}</Hint>}
          </Section>
          {mode.objective && (
            <Section title="运行中会问你三次" note="不提交它会一直等">
              <ol className="m-0 flex list-decimal flex-col gap-1 pl-4 text-xs">
                <li>开始前：总体研究方向和基础特征集。方向留空就由 Agent 自行选题。</li>
                <li>每一轮开始：这一轮的假设。认可就直接继续，也可以改写后提交。</li>
                <li>每一轮结束：评估结论。不同意 Agent 的判断可以在这里改。</li>
              </ol>
              <Hint>确认面板会出现在这一栏，不改直接提交就按 Agent 的原案继续。</Hint>
            </Section>
          )}
          {form.objective.trim() && mode.objective && <Section title="研究方向"><p className="m-0 text-xs">{form.objective}</p></Section>}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {trace.interaction && <InteractionPanel event={trace.interaction} busy={trace.busy} defaultInstruction={form.objective} onSubmit={trace.answer} />}
          {trace.traceId && !trace.active && trace.rounds.length > 0 && ["已完成", "已停止", "执行失败", "已结束"].includes(status) && (
            <RunSummary events={trace.events} status={status} onContinue={canContinue ? continueResearch : undefined}
              onBacktest={(names) => {
                const wanted = new Set(names);
                for (const r of trace.rounds) { const mine = r.factors.filter((f) => wanted.has(f)); if (mine.length) basket.addRound(trace.traceId, Number(r.id), mine); }
                navigate(workspace.path("/backtest"));
              }} />
          )}
          {trace.traceId && (progress.length > 0 || trace.active) && <LiveStatus traceId={trace.traceId} events={trace.events} running={trace.active} waiting={!!trace.interaction} roundId={activeRound?.id ?? null}
            confirm={summaries.find((x) => x.id === trace.traceId)?.confirm} autoAnswered={summaries.find((x) => x.id === trace.traceId)?.auto_answered} />}
          {activeRound ? <RoundDetail round={activeRound} onContinue={canContinue ? continueResearch : undefined} /> : <Hint>在左侧展开一个实验，点一轮查看假设、评估与代码。</Hint>}
        </div>
      )}
    >
      {trace.error && <Note tone="bad" actions={<Btn kind="text" onClick={() => trace.setError("")}>关闭</Btn>}>{trace.error}</Note>}
      {tab === "new" ? (
        <Block title="新建研究" note={env?.chat_model || "未配置研究模型"}>
          <FieldGrid min={160}>
            <Field label="场景">
              <SelectInput value={form.scenario} onChange={(v) => { setForm((f) => ({ ...f, scenario: v })); setFiles([]); }} options={MODES.map((m) => ({ value: m.value, label: m.name }))} />
            </Field>
            {form.scenario.startsWith("Finance") && universes.length > 0 && (
              <Field label="股票池" hint="因子在这个池子里计算、排序和回测">
                <SelectInput value={form.market} onChange={(v) => setForm((f) => ({ ...f, market: v }))} options={universes.map((u) => ({ value: u.market, label: `${universeLabel(u.market)}${u.ready ? "" : "（首次需准备数据）"}`, hint: u.members ? `${u.members} 只 · ${u.benchmark}` : u.benchmark }))} />
              </Field>
            )}
            {mode.loops && <Field label="轮数" hint="1–30"><NumberInput value={form.loops} onChange={(v) => setForm((f) => ({ ...f, loops: v }))} min={1} max={30} /></Field>}
            {mode.duration && <Field label="时限（小时）" hint="0.1–24"><NumberInput value={form.duration} onChange={(v) => setForm((f) => ({ ...f, duration: v }))} min={0.1} max={24} step={0.1} /></Field>}
            {mode.loops && (
              <Field label="确认方式" hint="运行中哪些环节要等你点头">
                <SelectInput value={form.confirmMode} onChange={(v) => setForm((f) => ({ ...f, confirmMode: v }))} options={[
                  { value: "hypothesis", label: "只确认假设", hint: "推荐" },
                  { value: "all", label: "全部确认", hint: "指示·特征·假设·结论" },
                  { value: "auto", label: "全自动", hint: "不打断" },
                ]} />
              </Field>
            )}
            {mode.loops && form.confirmMode !== "auto" && (
              <Field label="无人处理时（分钟）" hint="等这么久没人确认就按 Agent 原案继续；0 = 一直等">
                <NumberInput value={form.confirmTimeout} onChange={(v) => setForm((f) => ({ ...f, confirmTimeout: v }))} min={0} max={1440} />
              </Field>
            )}
            {mode.input && (
              <Field label={mode.input === "reports" ? "研报 PDF（可多选）" : "论文 PDF"}>
                <input type="file" accept=".pdf,application/pdf" multiple={mode.input === "reports"} onChange={(e) => setFiles([...(e.target.files || [])])} className="mm-control--file" />
              </Field>
            )}
            {mode.input === "paper" && <Field label="或论文链接"><TextInput placeholder="https://arxiv.org/pdf/…" value={form.link} onChange={(v) => setForm((f) => ({ ...f, link: v }))} /></Field>}
            {mode.objective && (
              <Field label="研究方向（可选）" wide>
                <textarea rows={5} className="mm-control" value={form.objective} onChange={(e) => setForm((f) => ({ ...f, objective: e.target.value }))}
                  placeholder="留空则由 Agent 自行选题。填了会作为总体指示进入每一轮的假设生成，例如：研究沪深300中量价动量因子的增量信息。" />
              </Field>
            )}
          </FieldGrid>
          {chosenUniverse && !chosenUniverse.ready && <div style={{ marginTop: 12 }}><Note tone="info">第一次在{universeLabel(form.market)}上研究要先从 Qlib 导出这个池子的日线数据给因子代码用，中证1000 约半分钟，全市场约一两分钟；点开始后请等待，之后不用再等。</Note></div>}
          <div className="mm-row" style={{ marginTop: 16 }}>
            <Btn kind="primary" disabled={trace.busy} onClick={start}>{trace.busy ? "启动中…" : "开始研究"}</Btn>
            <span className="mm-dim" style={{ fontSize: 12 }}>{mode.desc}{files.length ? ` · 已选 ${files.map((f) => f.name).join("，")}` : ""}</span>
          </div>
          <P>场景说明、环境和确认流程在右栏。</P>
        </Block>
      ) : (
        <Block title="实验" count={experiments.length} note={experiments.length ? "点一个实验展开它的轮次；再点一轮在右栏看详情" : undefined}>
          {experiments.length ? (
            <Table label="实验" columns={[{ label: "", width: 22 }, { label: "实验" }, { label: "场景", width: 110, optional: true }, { label: "轮", num: true, width: 44 }, { label: "接受", num: true, width: 50 }, { label: "状态", width: anyLive ? 180 : 72 }, { label: "更新", width: 100, optional: true }]}
              rows={experimentRows} />
          ) : <Empty>还没有实验。切到「新建研究」启动第一个。</Empty>}
        </Block>
      )}
    </PageFrame>
  );
}
