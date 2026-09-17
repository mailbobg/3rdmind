import { useEffect, useMemo, useState } from "react";
import { Alert, Card, Checkbox, Chip, Disclosure, TextArea } from "@heroui/react";
import { Btn, SelectInput } from "./minimal";
import type { TraceEvent } from "../api/studio";
import type { RoundView } from "../hooks/rounds";
import { download } from "../hooks/studioContext";
import { Section } from "./Section";
import { CodeView, Formula, Hint, MetricTable, Mono, StatusChip } from "./widgets";
import { t } from "../i18n";

/** A round's full detail in the results column. */
/** `onContinue` adds "继续研究" beside the agent's next hypothesis: the caller resumes the experiment. */
export function RoundDetail({ round, onContinue }: { round: RoundView; onContinue?: () => void }) {
  const [file, setFile] = useState(0);
  useEffect(() => setFile(Math.max(0, round.files.length - 1)), [round.id, round.files.length]);
  const current = round.files[file];
  if (!round.metrics && !round.files.length && !round.feedback && !round.hypothesis.hypothesis) return <Hint>{t("这一轮还没有产出。")}</Hint>;
  return (
    <div className="flex flex-col gap-3">
      {(round.hypothesis.hypothesis || round.hypothesis.reason) && (
        <Section title={t("研究假设")} note={t("第 {0} 轮", [Number(round.id) + 1])}>
          <p className="m-0 text-xs">{round.hypothesis.hypothesis}</p>
          {round.hypothesis.reason && <Hint>{round.hypothesis.reason}</Hint>}
          {round.hypothesis.concise_knowledge && <Hint>{t("经验：{0}", [round.hypothesis.concise_knowledge])}</Hint>}
        </Section>
      )}
      {round.feedback && (
        <Section title={t("Agent 反馈")} note={<Chip size="sm" variant="soft" color={round.feedback.decision ? "success" : "danger"}>{round.feedback.decision ? t("接受") : t("拒绝")}</Chip>}>
          {round.feedback.observations && <p className="m-0 text-xs">{round.feedback.observations}</p>}
          {round.feedback.hypothesis_evaluation && <p className="m-0 text-xs">{round.feedback.hypothesis_evaluation}</p>}
          {round.feedback.reason && <p className="m-0 text-xs">{round.feedback.reason}</p>}
          {round.feedback.new_hypothesis && (
            <div className="flex flex-col gap-1.5">
              <Hint>{t("下一步：{0}", [round.feedback.new_hypothesis])}</Hint>
              {onContinue && <div><Btn onClick={onContinue}>{t("继续研究，让 Agent 接着这个假设跑")}</Btn></div>}
            </div>
          )}
        </Section>
      )}
      {round.tasks.length > 0 && (
        <Section title={t("本轮因子")} note={t("{0} 个{1}", [round.tasks.length, round.factors.length ? t(" · {0} 个已实现", [round.factors.length]) : ""])}>
          <div className="flex flex-col gap-3">
            {round.tasks.map((task) => (
              <div key={task.name} className="flex flex-col gap-1 border-b border-border pb-3 last:border-b-0 last:pb-0">
                <div className="flex items-center gap-2">
                  <Mono>{task.name}</Mono>
                  <span className={`text-[11px] ${round.factors.includes(task.name) ? "text-success" : "text-muted"}`}>{round.factors.includes(task.name) ? t("已实现") : round.metrics ? t("未实现") : ""}</span>
                </div>
                {task.description && <p className="m-0 text-xs">{task.description}</p>}
                {task.formulation && <Formula source={task.formulation} />}
                {task.variables && Object.keys(task.variables).length > 0 && (
                  <Hint>{t("变量：")}{Object.entries(task.variables).map(([v, meaning]) => <span key={v}><Mono>{v}</Mono> {meaning}； </span>)}</Hint>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}
      {round.metrics && <Section title={t("原生 Qlib 评估")} note="LightGBM · TopkDropout"><MetricTable metrics={round.metrics} /></Section>}
      {round.chartHtml && <Section title={t("收益图")}><iframe srcDoc={round.chartHtml} sandbox="allow-scripts" title={t("收益图")} className="h-[420px] w-full border-0" /></Section>}
      {round.files.length > 0 && (
        <Section title={t("生成代码")} note={current && <Btn kind="text" onClick={() => download(`${current.task || "round"}-${current.name}`, current.code)}>{t("下载代码")}</Btn>}>
          {round.files.length > 1 && (
            <SelectInput value={String(file)} onChange={(v) => setFile(Number(v))} ariaLabel={t("代码文件")}
              options={round.files.map((f, i) => ({ value: String(i), label: f.name, group: f.task || undefined }))} />
          )}
          {current && <CodeView code={current.code} />}
        </Section>
      )}
    </div>
  );
}

const LABELS: Record<string, string> = { user_instruction: t("研究方向"), hypothesis: t("研究假设"), reason: t("依据与反馈"), decision: t("评估决定") };

type Kind = "instruction" | "features" | "hypothesis" | "feedback" | "other";
const kindOf = (c: any): Kind => (c && typeof c === "object"
  ? "features" in c ? "features" : "user_instruction" in c ? "instruction" : "decision" in c ? "feedback" : "hypothesis" in c ? "hypothesis" : "other" : "other");
const KIND_TITLES: Record<Kind, string> = { instruction: t("开始前的研究方向"), features: t("基础特征集"), hypothesis: t("这一轮的假设"), feedback: t("这一轮的评估结论"), other: t("继续") };
const KIND_HINTS: Record<Kind, string> = {
  instruction: t("留空就由 Agent 自行选题；写了会作为总体指示进入每一轮的假设生成。"),
  features: t("Agent 会在这些 Qlib 特征之上补充新因子。去掉的特征这次研究就不会用。"),
  hypothesis: t("认可就直接继续；想换方向就改写后继续。"),
  feedback: t("Agent 对这一轮的判断。不同意就切换接受 / 拒绝，下一步假设也可以改。"),
  other: t("不改直接提交即按 Agent 的原案继续。"),
};

/**
 * The agent's pending confirmation, as a form for what the decision actually is: a hypothesis to accept or
 * rewrite, a verdict to accept or flip, a feature list to prune, an instruction to write. The raw JSON stays
 * available under "高级" for anything else.
 */
export function InteractionPanel({ event, busy, defaultInstruction, onSubmit }: { event: TraceEvent; busy: boolean; defaultInstruction?: string; onSubmit: (payload: object) => void }) {
  const kind = kindOf(event.content);
  const original = useMemo(() => {
    const c = event.content;
    const seeded = defaultInstruction && kind === "instruction" ? { ...c, user_instruction: c.user_instruction || defaultInstruction } : c;
    return JSON.stringify(seeded, null, 2);
  }, [event.timestamp]); // eslint-disable-line react-hooks/exhaustive-deps
  const [text, setText] = useState(original);
  const [editing, setEditing] = useState(false);
  useEffect(() => { setText(original); setEditing(false); }, [original]);
  const parsed = useMemo(() => { try { return { value: JSON.parse(text), error: "" }; } catch { return { value: null, error: t("JSON 格式错误。") }; } }, [text]);
  const value = parsed.value && typeof parsed.value === "object" ? parsed.value : null;
  const update = (k: string, v: unknown) => { if (value) setText(JSON.stringify({ ...value, [k]: v }, null, 2)); };
  const changed = text !== original;
  const submit = () => {
    const d = parsed.value;
    if (!d || typeof d !== "object" || Array.isArray(d)) return;
    onSubmit(kind === "features" && d.features ? d.features : d);
  };
  const features: Record<string, string> = kind === "features" && value?.features ? value.features : {};
  const originalFeatures: Record<string, string> = kind === "features" ? event.content?.features || {} : {};
  const toggleFeature = (name: string) => {
    const next = { ...features };
    if (name in next) delete next[name]; else next[name] = originalFeatures[name];
    update("features", next);
  };
  return (
    <Card variant="secondary" className="interact gap-3 p-3">
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-2 text-xs font-semibold"><i className="live__dot" aria-hidden />{t("等你确认：{0}", [KIND_TITLES[kind]])}</span>
        <span className="text-[11px] text-muted">{event.timestamp.slice(11, 19)}</span>
      </div>
      <Hint>{KIND_HINTS[kind]}</Hint>

      {kind === "hypothesis" && value && (
        <div className="flex flex-col gap-2">
          {editing
            ? <TextArea rows={5} value={value.hypothesis || ""} onChange={(e) => update("hypothesis", e.target.value)} variant="secondary" aria-label={t("研究假设")} />
            : <p className="m-0 text-[13px] leading-relaxed">{value.hypothesis}</p>}
          {value.reason && <p className="m-0 text-[11px] leading-relaxed text-muted">{value.reason}</p>}
        </div>
      )}

      {kind === "feedback" && value && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-muted">{t("Agent 的判断")}</span>
            <div className="mm-seg" role="radiogroup" aria-label={t("评估决定")}>
              <button type="button" role="radio" aria-checked={value.decision === true} className="mm-seg__item mm-seg__item--ok" onClick={() => update("decision", true)}>{t("接受")}</button>
              <button type="button" role="radio" aria-checked={value.decision !== true} className="mm-seg__item mm-seg__item--bad" onClick={() => update("decision", false)}>{t("拒绝")}</button>
            </div>
            {value.decision !== event.content?.decision && <span className="text-[11px] text-warning">{t("你改了 Agent 的判断")}</span>}
          </div>
          {value.hypothesis_evaluation && <p className="m-0 text-[12px] leading-relaxed">{value.hypothesis_evaluation}</p>}
          {value.reason && <p className="m-0 text-[11px] leading-relaxed text-muted">{value.reason}</p>}
          {"new_hypothesis" in value && (
            <label className="flex flex-col gap-1 text-[11px] text-muted">{t("下一步假设")}
              {editing
                ? <TextArea rows={4} value={value.new_hypothesis || ""} onChange={(e) => update("new_hypothesis", e.target.value)} variant="secondary" aria-label={t("下一步假设")} />
                : <span className="text-[12px] leading-relaxed text-foreground">{value.new_hypothesis || <span className="text-muted">{t("（无）")}</span>}</span>}
            </label>
          )}
        </div>
      )}

      {kind === "instruction" && value && (
        <TextArea rows={4} value={value.user_instruction || ""} placeholder={t("留空则由 Agent 自行选题")} onChange={(e) => update("user_instruction", e.target.value)} variant="secondary" aria-label={t("研究方向")} />
      )}

      {kind === "features" && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-[11px] text-muted">
            <span>{t("{0} / {1} 个特征", [Object.keys(features).length, Object.keys(originalFeatures).length])}</span>
            <span className="flex gap-3">
              <button type="button" className="mm-link" onClick={() => update("features", { ...originalFeatures })}>{t("全选")}</button>
              <button type="button" className="mm-link" onClick={() => update("features", {})}>{t("清空")}</button>
            </span>
          </div>
          <div className="grid max-h-56 gap-1 overflow-auto pr-1" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
            {Object.entries(originalFeatures).map(([name, expr]) => (
              <label key={name} className="flex items-start gap-2 rounded-md px-1.5 py-1 text-[11px] hover:bg-surface-secondary" title={expr}>
                <input type="checkbox" className="mm-check mt-0.5" checked={name in features} onChange={() => toggleFeature(name)} />
                <span className="min-w-0"><span className="mm-mono">{name}</span><span className="block truncate text-muted">{expr}</span></span>
              </label>
            ))}
          </div>
          {event.content?.feature_validation_msg && <Alert status="warning"><Alert.Indicator /><Alert.Content><Alert.Title>{event.content.feature_validation_msg}</Alert.Title></Alert.Content></Alert>}
        </div>
      )}

      <Disclosure>
        <Disclosure.Heading><Disclosure.Trigger className="text-[11px]">{t("高级：完整 JSON")}<Disclosure.Indicator /></Disclosure.Trigger></Disclosure.Heading>
        <Disclosure.Content><TextArea aria-label={t("完整 JSON")} rows={10} value={text} onChange={(e) => setText(e.target.value)} variant="secondary" className="w-full font-mono text-[11px]" /></Disclosure.Content>
      </Disclosure>
      {parsed.error && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{parsed.error}</Alert.Title></Alert.Content></Alert>}
      <div className="flex flex-wrap items-center gap-2">
        <Btn kind="primary" disabled={busy || !!parsed.error} onClick={submit}>
          {busy ? t("提交中…") : changed ? t("按修改继续") : kind === "hypothesis" ? t("认可，继续") : kind === "feedback" ? t("同意判断，继续") : kind === "features" ? t("用这些特征继续") : kind === "instruction" ? (value?.user_instruction ? t("带着方向开始") : t("让 Agent 自选，开始")) : t("按原案继续")}
        </Btn>
        {(kind === "hypothesis" || kind === "feedback") && !editing && <Btn onClick={() => setEditing(true)}>{t("改写")}</Btn>}
        {(kind === "hypothesis" || kind === "feedback") && editing && changed && <Btn kind="text" onClick={() => { setText(original); setEditing(false); }}>{t("撤销改动")}</Btn>}
      </div>
    </Card>
  );
}
