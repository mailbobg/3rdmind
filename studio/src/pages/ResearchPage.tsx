import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Button, TextArea } from "@heroui/react";
import * as studio from "../api/studio";
import type { RoundView } from "../hooks/rounds";
import { persistStudioState, restoreStudioState } from "../hooks/studioStorage";
import { errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { Panel } from "../components/Panel";
import { InteractionPanel, RoundCard, RoundDetail } from "../components/RoundViews";
import { NumberBox, SelectBox, TabBar, TextBox } from "../components/fields";
import { Hint, StatusChip } from "../components/widgets";

interface Mode { name: string; desc: string; value: string; loops: boolean; duration: boolean; objective: boolean; input?: "reports" | "paper" }
// The scenarios the log server's /upload accepts; Data Science needs an MLE-bench dataset, so it stays in the Playground.
const MODES: Mode[] = [
  { name: "因子研发", desc: "假设 → 因子实现 → Qlib 评估", value: "Finance Data Building", loops: true, duration: true, objective: true },
  { name: "模型研发", desc: "模型实现与迭代验证", value: "Finance Model Implementation", loops: true, duration: true, objective: true },
  { name: "因子 × 模型联合", desc: "RD-Agent 原生联合研究循环", value: "Finance Whole Pipeline", loops: true, duration: true, objective: true },
  { name: "研报因子提取", desc: "上传研报 PDF → 提取因子 → 实现与 Qlib 评估", value: "Finance Data Building (Reports)", loops: false, duration: true, objective: false, input: "reports" },
  { name: "论文模型实现", desc: "上传论文 PDF 或给链接 → 提取模型结构 → 实现", value: "General Model Implementation", loops: false, duration: false, objective: false, input: "paper" },
];

export function ResearchPage() {
  const { env, trace, basket, layout } = useStudio();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState(search.get("new") || !trace.traceId ? "new" : "rounds");
  const [form, setForm] = useState(() => ({ scenario: MODES[0].value, loops: 3, duration: 2, objective: restoreStudioState().objective || "", link: "" }));
  const [files, setFiles] = useState<File[]>([]);
  const [roundId, setRoundId] = useState("");
  const [predictionLoops, setPredictionLoops] = useState<Set<number>>(new Set());
  const mode = MODES.find((m) => m.value === form.scenario) || MODES[0];

  useEffect(() => { if (search.get("new")) setTab("new"); }, [search]);
  useEffect(() => { persistStudioState({ objective: form.objective }); }, [form.objective]);
  // The URL's ?trace= seeds the first load only; afterwards the user's pick wins on reload.
  useEffect(() => {
    const wanted = search.get("trace") || trace.traceId;
    if (wanted && (wanted !== trace.traceId || !trace.events.length)) trace.select(wanted);
    if (search.get("trace")) setSearch({}, { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
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

  const sendToBacktest = (round: RoundView) => { basket.addRound(trace.traceId, Number(round.id), round.factors); navigate("/backtest"); };
  const sendPrediction = (round: RoundView) => { basket.addPrediction(trace.traceId, Number(round.id)); navigate("/backtest"); };
  const objectDesc = useMemo(() => {
    if (!trace.traceId) return "启动 RD-Agent 研究，查看假设、代码与评估";
    const last = trace.rounds[trace.rounds.length - 1];
    return last?.hypothesis?.hypothesis || trace.traceId;
  }, [trace.traceId, trace.rounds]);
  const objectTag = trace.traceId ? (MODES.find((m) => trace.traceId.startsWith(m.value + "/"))?.name || trace.traceId.split("/")[0]) : undefined;

  return (
    <PageFrame
      title={trace.traceId ? shortName(trace.traceId) : "AI 研究"}
      description={objectDesc}
      tag={objectTag}
      titleEnd={trace.traceId ? <StatusChip status={status} /> : undefined}
      tabs={<TabBar label="工作区视图" value={tab} onChange={setTab} items={[{ key: "rounds", label: "研究轮次" }, { key: "new", label: "＋ 新建研究" }]} />}
      actions={
        <>
          <SelectBox label="实验" isLabelHidden placeholder="选择实验" width={280} value={trace.traceId || null} onChange={pick} options={trace.traceIds.map((id) => ({ value: id, label: id }))} />
          {trace.traceId && <Button size="sm" variant="ghost" onPress={() => pick("")}>取消选择</Button>}
          {trace.active && <Button size="sm" variant="danger-soft" isDisabled={trace.busy} onPress={trace.stop}>■ 停止</Button>}
          {trace.traceId && <a className="text-xs text-accent underline" href={studio.stdoutUrl(trace.traceId)} download>日志</a>}
        </>
      }
      resultsTitle={activeRound ? `第 ${Number(activeRound.id) + 1} 轮` : "轮次详情"}
      resultsActions={activeRound ? (
        <>
          {activeRound.factors.length > 0 && <Button size="sm" onPress={() => sendToBacktest(activeRound)}>用 {activeRound.factors.length} 个因子回测 →</Button>}
          {hasPrediction(activeRound) && <Button size="sm" variant="secondary" onPress={() => sendPrediction(activeRound)}>用模型预测回测 →</Button>}
        </>
      ) : undefined}
      results={
        <div className="flex flex-col gap-3">
          {trace.interaction && <InteractionPanel event={trace.interaction} busy={trace.busy} defaultInstruction={form.objective} onSubmit={trace.answer} />}
          {activeRound ? <RoundDetail round={activeRound} /> : <Hint>在左侧选择一轮查看假设、评估与代码。</Hint>}
        </div>
      }
    >
      {trace.error && (
        <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{trace.error}</Alert.Title></Alert.Content>
          <Button size="sm" variant="ghost" onPress={() => trace.setError("")}>关闭</Button></Alert>
      )}
      {tab === "new" ? (
        <>
          <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
            <SelectBox label="场景" value={form.scenario} onChange={(v) => { setForm((f) => ({ ...f, scenario: v })); setFiles([]); }} width={220}
              options={MODES.map((m) => ({ value: m.value, label: m.name, description: m.desc }))} />
            {mode.loops && <NumberBox label="轮数（1–30）" value={form.loops} onChange={(v) => setForm((f) => ({ ...f, loops: v }))} min={1} max={30} width={110} />}
            {mode.duration && <NumberBox label="时限（小时，0.1–24）" value={form.duration} onChange={(v) => setForm((f) => ({ ...f, duration: v }))} min={0.1} max={24} step={0.1} width={140} />}
            {mode.input && (
              <label className="flex flex-col gap-1 text-[11px] text-muted">{mode.input === "reports" ? "研报 PDF（可多选）" : "论文 PDF"}
                <input type="file" accept=".pdf,application/pdf" multiple={mode.input === "reports"} onChange={(e) => setFiles([...(e.target.files || [])])} className="text-xs" />
              </label>
            )}
            {mode.input === "paper" && <TextBox label="或论文链接" placeholder="https://arxiv.org/pdf/…" value={form.link} onChange={(v) => setForm((f) => ({ ...f, link: v }))} width={260} />}
          </div>
          <Panel grow title={mode.name} status={env?.chat_model || "未配置研究模型"} footer={<Button size="sm" isDisabled={trace.busy} isPending={trace.busy} onPress={start}>▶ 开始研究</Button>}>
            <div className="flex flex-col gap-2">
              <Hint>{mode.desc}</Hint>
              {files.length > 0 && <Hint>已选文件：{files.map((f) => f.name).join("，")}</Hint>}
              {mode.objective && (
                <>
                  <label className="flex flex-col gap-1 text-[11px] text-muted">研究方向（可选）
                    <TextArea rows={5} value={form.objective} onChange={(e) => setForm((f) => ({ ...f, objective: e.target.value }))}
                      placeholder="留空则由 agent 自行选题。填了会作为总体指示进入每一轮的假设生成，例如：研究沪深300中量价动量因子的增量信息。" className="w-full" />
                  </label>
                  <Hint>假设由 agent 自己提出并按前几轮的成败迭代。运行中它会在三个节点停下来让你确认（开始前的方向与基础特征、每轮的假设、每轮的反馈），面板里不改直接提交就按它的原案继续；不提交它会一直等。</Hint>
                </>
              )}
            </div>
          </Panel>
        </>
      ) : (
        <Panel grow title={<>研究轮次 <span className="font-normal text-muted">{trace.rounds.length} 轮</span></>} status={trace.traceId ? status : undefined}>
          {!trace.traceId ? <div className="p-6 text-center text-xs text-muted">从右上角选择一个实验，或新建研究。</div>
            : status === "启动中" ? <div className="p-6 text-center text-xs text-muted">agent 正在初始化，第一条事件到达前这里是空的，通常几十秒。</div>
            : status === "未加载" ? <Alert status="accent"><Alert.Indicator /><Alert.Content><Alert.Title>服务端没有加载这个实验的事件</Alert.Title><Alert.Description>已结束的实验需要后端以 UI_LOAD_LEGACY_PICKLE_TRACES=true 启动才可回看。</Alert.Description></Alert.Content></Alert>
            : status === "已结束" && !trace.rounds.length ? <Alert status="warning"><Alert.Indicator /><Alert.Content><Alert.Title>这个实验的进程已结束，且没有留下任何事件；看日志里的报错。</Alert.Title></Alert.Content></Alert>
            : status === "运行中" && !trace.rounds.length ? <div className="p-6 text-center text-xs text-muted">研究已启动，等待第一轮假设…</div>
            : (
              <div className="flex flex-col gap-2">
                {trace.rounds.map((round) => (
                  <RoundCard key={round.id} round={round} selected={round.id === (activeRound?.id ?? "")} hasPrediction={hasPrediction(round)}
                    onSelect={() => { setRoundId(round.id); layout.openResults(); }} onBacktest={() => sendToBacktest(round)} onBacktestPrediction={() => sendPrediction(round)} />
                ))}
              </div>
            )}
        </Panel>
      )}
    </PageFrame>
  );
}
