import { useEffect, useMemo, useState } from "react";
import { Alert, Card, Checkbox, Chip, Disclosure, TextArea } from "@heroui/react";
import { Btn, SelectInput } from "./minimal";
import type { TraceEvent } from "../api/studio";
import type { RoundView } from "../hooks/rounds";
import { download } from "../hooks/studioContext";
import { Section } from "./Section";
import { CodeView, Formula, Hint, MetricTable, Mono, StatusChip } from "./widgets";

/** A round's full detail in the results column. */
/** `onContinue` adds "继续研究" beside the agent's next hypothesis: the caller resumes the experiment. */
export function RoundDetail({ round, onContinue }: { round: RoundView; onContinue?: () => void }) {
  const [file, setFile] = useState(0);
  useEffect(() => setFile(Math.max(0, round.files.length - 1)), [round.id, round.files.length]);
  const current = round.files[file];
  if (!round.metrics && !round.files.length && !round.feedback && !round.hypothesis.hypothesis) return <Hint>这一轮还没有产出。</Hint>;
  return (
    <div className="flex flex-col gap-3">
      {(round.hypothesis.hypothesis || round.hypothesis.reason) && (
        <Section title="研究假设" note={`第 ${Number(round.id) + 1} 轮`}>
          <p className="m-0 text-xs">{round.hypothesis.hypothesis}</p>
          {round.hypothesis.reason && <Hint>{round.hypothesis.reason}</Hint>}
          {round.hypothesis.concise_knowledge && <Hint>经验：{round.hypothesis.concise_knowledge}</Hint>}
        </Section>
      )}
      {round.feedback && (
        <Section title="Agent 反馈" note={<Chip size="sm" variant="soft" color={round.feedback.decision ? "success" : "danger"}>{round.feedback.decision ? "接受" : "拒绝"}</Chip>}>
          {round.feedback.observations && <p className="m-0 text-xs">{round.feedback.observations}</p>}
          {round.feedback.hypothesis_evaluation && <p className="m-0 text-xs">{round.feedback.hypothesis_evaluation}</p>}
          {round.feedback.reason && <p className="m-0 text-xs">{round.feedback.reason}</p>}
          {round.feedback.new_hypothesis && (
            <div className="flex flex-col gap-1.5">
              <Hint>下一步：{round.feedback.new_hypothesis}</Hint>
              {onContinue && <div><Btn onClick={onContinue}>继续研究，让 Agent 接着这个假设跑</Btn></div>}
            </div>
          )}
        </Section>
      )}
      {round.tasks.length > 0 && (
        <Section title="本轮因子" note={`${round.tasks.length} 个${round.factors.length ? ` · ${round.factors.length} 个已实现` : ""}`}>
          <div className="flex flex-col gap-3">
            {round.tasks.map((task) => (
              <div key={task.name} className="flex flex-col gap-1 border-b border-border pb-3 last:border-b-0 last:pb-0">
                <div className="flex items-center gap-2">
                  <Mono>{task.name}</Mono>
                  <span className={`text-[11px] ${round.factors.includes(task.name) ? "text-success" : "text-muted"}`}>{round.factors.includes(task.name) ? "已实现" : round.metrics ? "未实现" : ""}</span>
                </div>
                {task.description && <p className="m-0 text-xs">{task.description}</p>}
                {task.formulation && <Formula source={task.formulation} />}
                {task.variables && Object.keys(task.variables).length > 0 && (
                  <Hint>变量：{Object.entries(task.variables).map(([v, meaning]) => <span key={v}><Mono>{v}</Mono> {meaning}； </span>)}</Hint>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}
      {round.metrics && <Section title="原生 Qlib 评估" note="LightGBM · TopkDropout"><MetricTable metrics={round.metrics} /></Section>}
      {round.chartHtml && <Section title="收益图"><iframe srcDoc={round.chartHtml} sandbox="allow-scripts" title="收益图" className="h-[420px] w-full border-0" /></Section>}
      {round.files.length > 0 && (
        <Section title="生成代码" note={current && <Btn kind="text" onClick={() => download(`${current.task || "round"}-${current.name}`, current.code)}>下载代码</Btn>}>
          {round.files.length > 1 && (
            <SelectInput value={String(file)} onChange={(v) => setFile(Number(v))} ariaLabel="代码文件"
              options={round.files.map((f, i) => ({ value: String(i), label: f.name, group: f.task || undefined }))} />
          )}
          {current && <CodeView code={current.code} />}
        </Section>
      )}
    </div>
  );
}

const LABELS: Record<string, string> = { user_instruction: "研究方向", hypothesis: "研究假设", reason: "依据与反馈", decision: "评估决定" };

/** The agent's pending confirmation request: editable fields for the common keys, raw JSON underneath. */
export function InteractionPanel({ event, busy, defaultInstruction, onSubmit }: { event: TraceEvent; busy: boolean; defaultInstruction?: string; onSubmit: (payload: object) => void }) {
  const original = useMemo(() => {
    const c = event.content;
    const seeded = defaultInstruction && c && typeof c === "object" && "user_instruction" in c ? { ...c, user_instruction: c.user_instruction || defaultInstruction } : c;
    return JSON.stringify(seeded, null, 2);
  }, [event.timestamp]); // eslint-disable-line react-hooks/exhaustive-deps
  const [text, setText] = useState(original);
  useEffect(() => setText(original), [original]);
  const parsed = useMemo(() => { try { return { value: JSON.parse(text), error: "" }; } catch { return { value: null, error: "JSON 格式错误。" }; } }, [text]);
  const fields = parsed.value && typeof parsed.value === "object" ? Object.keys(LABELS).filter((k) => k in parsed.value).map((k) => ({ key: k, value: parsed.value[k] })) : [];
  const update = (k: string, v: unknown) => { if (parsed.value) setText(JSON.stringify({ ...parsed.value, [k]: v }, null, 2)); };
  const c = event.content || {};
  const stageHint = "features" in c ? "基础特征集：Agent 会在这些 Qlib 特征之上补充新因子，不改直接继续。"
    : "user_instruction" in c ? "开始前的总体指示：可留空，Agent 会自行选题。"
    : "hypothesis" in c ? "这一轮 Agent 提出的假设：认可就直接继续，也可以改写后提交。"
    : "decision" in c ? "这一轮的评估结论：不同意 Agent 的判断可以在这里改。" : "不改直接提交即按 Agent 的原案继续。";
  const submit = () => {
    const d = parsed.value;
    if (!d || typeof d !== "object" || Array.isArray(d)) return;
    onSubmit("features" in c && d.features ? d.features : d);
  };
  return (
    <Card variant="secondary" className="gap-2 p-3">
      <div className="flex items-center justify-between"><span className="text-xs font-semibold">RD-Agent 等待你的确认</span><span className="text-[11px] text-muted">{event.timestamp}</span></div>
      <Hint>{stageHint}</Hint>
      {fields.map((f) =>
        typeof f.value === "string" ? (
          <label key={f.key} className="flex flex-col gap-1 text-[11px] text-muted">{LABELS[f.key]}
            <TextArea rows={3} value={f.value} onChange={(e) => update(f.key, e.target.value)} variant="secondary" />
          </label>
        ) : typeof f.value === "boolean" ? (
          <Checkbox key={f.key} isSelected={f.value} onChange={(v) => update(f.key, v)}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{LABELS[f.key]}</Checkbox.Content></Checkbox>
        ) : <Hint key={f.key}>{LABELS[f.key]}：{JSON.stringify(f.value)}</Hint>)}
      <Disclosure>
        <Disclosure.Heading><Disclosure.Trigger className="text-[11px]">完整 JSON<Disclosure.Indicator /></Disclosure.Trigger></Disclosure.Heading>
        <Disclosure.Content><TextArea aria-label="完整 JSON" rows={10} value={text} onChange={(e) => setText(e.target.value)} variant="secondary" className="w-full font-mono text-[11px]" /></Disclosure.Content>
      </Disclosure>
      {parsed.error && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{parsed.error}</Alert.Title></Alert.Content></Alert>}
      <div><Btn kind="primary" disabled={busy || !!parsed.error} onClick={submit}>{text !== original ? "提交修改" : "按原案继续"}</Btn></div>
    </Card>
  );
}
