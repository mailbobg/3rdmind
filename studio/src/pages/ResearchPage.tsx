import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@heroui/react";
import * as studio from "../api/studio";
import type { RoundView } from "../hooks/rounds";
import { persistStudioState, restoreStudioState } from "../hooks/studioStorage";
import { errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { InteractionPanel, RoundDetail } from "../components/RoundViews";
import { Block, Btn, Empty, Field, FieldGrid, Note, NumberInput, P, SelectInput, StatusTag, Table, TextInput, TextTabs } from "../components/minimal";
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

const stagesOf = (round: RoundView) => [
  { name: "假设", done: !!round.hypothesis.hypothesis },
  { name: "代码", done: round.files.length > 0 },
  { name: "评估", done: !!round.metrics },
  { name: "反馈", done: !!round.feedback },
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
      tabs={<TextTabs label="工作区视图" value={tab} onChange={setTab} items={[{ key: "rounds", label: "研究轮次" }, { key: "new", label: "新建研究" }]} />}
      actions={
        <>
          <SelectInput ariaLabel="实验" placeholder="选择实验" className="w-56" value={trace.traceId} onChange={pick}
            options={trace.traceIds.map((id) => ({ value: id, label: shortName(id), group: MODES.find((m) => id.startsWith(m.value + "/"))?.name || id.split("/")[0] }))} />
          {trace.active && <Btn kind="danger" disabled={trace.busy} onClick={trace.stop}>停止</Btn>}
          {trace.traceId && <Btn onClick={() => window.open(studio.stdoutUrl(trace.traceId), "_blank")}>日志</Btn>}
          {trace.traceId && <Btn kind="text" onClick={() => pick("")}>取消选择</Btn>}
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
      {trace.error && <Note tone="bad" actions={<Btn kind="text" onClick={() => trace.setError("")}>关闭</Btn>}>{trace.error}</Note>}
      {tab === "new" ? (
        <Block title="新建研究" note={env?.chat_model || "未配置研究模型"}>
          <FieldGrid min={160}>
            <Field label="场景">
              <SelectInput value={form.scenario} onChange={(v) => { setForm((f) => ({ ...f, scenario: v })); setFiles([]); }} options={MODES.map((m) => ({ value: m.value, label: m.name }))} />
            </Field>
            {mode.loops && <Field label="轮数" hint="1–30"><NumberInput value={form.loops} onChange={(v) => setForm((f) => ({ ...f, loops: v }))} min={1} max={30} /></Field>}
            {mode.duration && <Field label="时限（小时）" hint="0.1–24"><NumberInput value={form.duration} onChange={(v) => setForm((f) => ({ ...f, duration: v }))} min={0.1} max={24} step={0.1} /></Field>}
            {mode.input && (
              <Field label={mode.input === "reports" ? "研报 PDF（可多选）" : "论文 PDF"}>
                <input type="file" accept=".pdf,application/pdf" multiple={mode.input === "reports"} onChange={(e) => setFiles([...(e.target.files || [])])} className="mm-control--file" />
              </Field>
            )}
            {mode.input === "paper" && <Field label="或论文链接"><TextInput placeholder="https://arxiv.org/pdf/…" value={form.link} onChange={(v) => setForm((f) => ({ ...f, link: v }))} /></Field>}
            {mode.objective && (
              <Field label="研究方向（可选）" wide>
                <textarea rows={5} className="mm-control" value={form.objective} onChange={(e) => setForm((f) => ({ ...f, objective: e.target.value }))}
                  placeholder="留空则由 agent 自行选题。填了会作为总体指示进入每一轮的假设生成，例如：研究沪深300中量价动量因子的增量信息。" />
              </Field>
            )}
          </FieldGrid>
          <div className="mm-row" style={{ marginTop: 16 }}>
            <Btn kind="primary" disabled={trace.busy} onClick={start}>{trace.busy ? "启动中…" : "开始研究"}</Btn>
            <span className="mm-dim" style={{ fontSize: 12 }}>{mode.desc}{files.length ? ` · 已选 ${files.map((f) => f.name).join("，")}` : ""}</span>
          </div>
          {mode.objective && <P>假设由 agent 自己提出并按前几轮的成败迭代。运行中它会在三个节点停下来让你确认（开始前的方向与基础特征、每轮的假设、每轮的反馈），面板里不改直接提交就按它的原案继续；不提交它会一直等。</P>}
        </Block>
      ) : (
        <Block title="研究轮次" count={trace.rounds.length} note={trace.traceId ? <StatusTag status={status} /> : undefined}>
          {!trace.traceId ? <Empty>从右上角选择一个实验，或新建研究。</Empty>
            : status === "启动中" ? <Empty>agent 正在初始化，第一条事件到达前这里是空的，通常几十秒。</Empty>
            : status === "未加载" ? <Note tone="info">服务端没有加载这个实验的事件。<small>已结束的实验需要后端以 UI_LOAD_LEGACY_PICKLE_TRACES=true 启动才可回看。</small></Note>
            : status === "已结束" && !trace.rounds.length ? <Note>这个实验的进程已结束，且没有留下任何事件；看日志里的报错。</Note>
            : status === "运行中" && !trace.rounds.length ? <Empty>研究已启动，等待第一轮假设…</Empty>
            : (
              <>
                <Table label="研究轮次" columns={[{ label: "轮", width: 48 }, { label: "假设" }, { label: "阶段", width: 220, optional: true }, { label: "因子", num: true, width: 56, optional: true }, { label: "状态", width: 72 }]}
                  rows={trace.rounds.map((round) => ({
                    key: round.id, selected: round.id === (activeRound?.id ?? ""), onClick: () => { setRoundId(round.id); layout.openResults(); },
                    cells: [
                      <span key="n" className="mm-mono mm-dim">{Number(round.id) + 1}</span>,
                      <span key="h" className="block truncate" title={round.hypothesis.hypothesis}>{round.hypothesis.hypothesis || <span className="mm-dim">（无假设文本）</span>}</span>,
                      <span key="s" className="mm-tag">{stagesOf(round).map((st) => <span key={st.name} className={st.done ? "mm-pos" : "mm-dim"} style={{ marginRight: 8 }}>{st.done ? "●" : "○"} {st.name}</span>)}</span>,
                      round.factors.length ? String(round.factors.length) : <span key="f" className="mm-dim">—</span>,
                      <StatusTag key="st" status={round.status} />,
                    ],
                  }))} />
                <P>点一轮在右栏看假设、评估、反馈与代码；回测入口在右栏标题行。</P>
              </>
            )}
        </Block>
      )}
    </PageFrame>
  );
}
