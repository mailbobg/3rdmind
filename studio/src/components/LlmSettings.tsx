import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as studio from "../api/studio";
import type { EmbeddingForm, LlmForm, LlmProvider, LlmStatus } from "../api/studio";
import { errorText } from "../hooks/studioContext";
import { Btn, Field, SelectInput, TextInput } from "./minimal";
import { t } from "../i18n";

const CUSTOM = "__custom__";

/**
 * The rail's model line plus a bottom sheet: provider, model, API key, base URL and retry count for research
 * runs. Saved settings live in studio_data/llm.json and apply to every research process started afterwards;
 * the key only ever comes back as its last four characters.
 */
export function LlmSettings({ onSaved }: { onSaved: () => void }) {
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<LlmForm>({ provider: "", model: "" });
  const [customModel, setCustomModel] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState<"" | "test" | "save" | "list">("");
  // Model lists fetched from each provider's own /models endpoint this session, keyed by provider id.
  const [remote, setRemote] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<{ tone: "ok" | "bad" | "info"; text: string } | null>(null);

  const load = useCallback(async () => {
    try { setStatus(await studio.llmSettings()); } catch (e) { setMessage({ tone: "bad", text: errorText(e) }); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const current = status?.current;
  const providers = status?.providers ?? [];
  const spec = providers.find((p) => p.id === form.provider);
  // The provider's live list when fetched, else the documented suggestions.
  const models = (form.provider && remote[form.provider]) || spec?.models || [];
  const live = !!(form.provider && remote[form.provider]);

  const openSheet = () => {
    if (current) {
      const provider = current.provider || providers[0]?.id || "";
      const known = remote[provider] || providers.find((p) => p.id === provider)?.models || [];
      setForm({ provider, model: current.model, api_key: "", base_url: current.base_url, max_retry: current.max_retry });
      setCustomModel(!!current.model && !known.includes(current.model));
    }
    setMessage(null); setShowKey(false); setOpen(true);
  };
  const pickProvider = (id: string) => {
    const p = providers.find((x) => x.id === id);
    const known = remote[id] || p?.models || [];
    const keepModel = known.includes(form.model);
    setForm({ ...form, provider: id, model: keepModel ? form.model : known[0] ?? "", api_key: "", base_url: id === current?.provider ? current.base_url : "" });
    setCustomModel(known.length === 0);
    setMessage(null);
  };
  const pickModel = (v: string) => {
    if (v === CUSTOM) { setCustomModel(true); setForm({ ...form, model: "" }); } else { setCustomModel(false); setForm({ ...form, model: v }); }
  };
  const storedHint = form.provider ? (form.provider === current?.provider ? current.key_hint : current?.saved_keys[form.provider] || "") : "";
  const fetchModels = useCallback(async (provider: string, api_key: string | undefined, base_url: string | undefined, quiet: boolean) => {
    setBusy("list");
    try {
      const r = await studio.listLlmModels({ provider, api_key, base_url });
      if (r.ok && r.models) {
        setRemote((m) => ({ ...m, [provider]: r.models! }));
        if (!quiet) setMessage({ tone: "info", text: t("已从 {0} 拉到 {1} 个模型", [r.source, r.models.length]) });
      } else if (!quiet) setMessage({ tone: "bad", text: t("拉取模型列表失败：{0}", [r.error]) });
    } catch (e) { if (!quiet) setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  }, []);
  // Whenever the sheet shows a provider that has a usable key and no live list yet, fetch its list quietly.
  useEffect(() => {
    if (!open || !form.provider || remote[form.provider] || spec?.needs_base && !form.base_url?.trim()) return;
    if (!storedHint && !form.api_key?.trim()) return;
    fetchModels(form.provider, form.api_key, form.base_url, true);
  }, [open, form.provider, storedHint]); // eslint-disable-line react-hooks/exhaustive-deps
  const keyPlaceholder = storedHint ? t("{0} {1}，留空则沿用", [form.provider === current?.provider && current.key_from_env ? t("沿用 .env 里的") : t("已保存"), storedHint]) : t("粘贴 API Key");
  const canSubmit = !!form.provider && !!form.model.trim() && (!spec?.needs_base || !!form.base_url?.trim()) && (!!form.api_key?.trim() || !!storedHint);

  const test = async () => {
    setBusy("test"); setMessage({ tone: "info", text: t("正在调用模型…") });
    try {
      const r = await studio.testLlmSettings(form);
      setMessage(r.ok ? { tone: "ok", text: t("连接正常：{0} 在 {1}s 内响应{2}", [r.model, r.seconds, r.reply ? t("，回复 “{0}”", [r.reply]) : ""]) } : { tone: "bad", text: t("连接失败：{0}", [r.error]) });
    } catch (e) { setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  };
  const save = async () => {
    setBusy("save"); setMessage(null);
    try {
      const s = await studio.saveLlmSettings(form);
      setStatus(s); setForm({ ...form, api_key: "" }); onSaved();
      setMessage({ tone: "ok", text: t("已保存，之后新启动的研究都用这套设置。") });
    } catch (e) { setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  };

  useEffect(() => { if (live && models.includes(form.model)) setCustomModel(false); }, [live, models, form.model]);
  const headline = !current ? "" : !current.provider ? t("未配置") : !current.has_key ? t("缺 API Key") : current.model;
  const warn = !!current && (!current.provider || !current.has_key);

  return (
    <div className="text-xs">
      <button type="button" onClick={openSheet} aria-haspopup="dialog" aria-expanded={open}
        className="-mx-2.5 flex w-[calc(100%+20px)] items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-left text-foreground transition-colors hover:bg-surface-secondary">
        <span className="w-[22px] text-center text-[17px] leading-none" aria-hidden>⚙︎</span>
        <span className="min-w-0 flex-1 text-[13px] font-medium">{t("模型设置")}</span>
        <span className={`flex min-w-0 items-center gap-1.5 text-[11px] ${warn ? "text-warning" : "text-muted"}`}>
          {warn && <i className="inline-block size-[6px] shrink-0 rounded-full bg-warning" />}
          <span className="truncate" title={headline}>{headline}</span>
        </span>
      </button>
      {open && createPortal(
        <>
          <div className="sheet-backdrop" onClick={() => setOpen(false)} />
          <div className="sheet" role="dialog" aria-label={t("模型设置")}>
            <div className="sheet__head">
              <div>
                <div className="sheet__title">{t("模型设置")}</div>
                <div className="text-[11px] text-muted">研究用的大模型 · 通过 LiteLLM 调用{current?.source === "env" ? t(" · 当前来自启动时的 .env") : current?.updated ? t(" · 保存于 {0}", [current.updated]) : ""}</div>
              </div>
              <Btn kind="text" onClick={() => setOpen(false)}>{t("关闭")}</Btn>
            </div>
            <div className="sheet__body">
              <div className="grid grid-cols-2 gap-3 [&>.mm-field--wide]:col-span-2">
                <Field label={t("提供商")}>
                  <SelectInput value={form.provider} onChange={pickProvider} options={providers.map((p) => ({ value: p.id, label: p.label }))} placeholder={t("选择提供商")} ariaLabel={t("提供商")} />
                </Field>
                <Field label={<>模型{live ? <span className="text-success"> {t("· 实时列表")}</span> : models.length ? <span> {t("· 文档默认")}</span> : null}</>} wide={customModel && models.length > 0}>
                  {models.length > 0 && !customModel
                    ? <SelectInput value={models.includes(form.model) ? form.model : ""} onChange={pickModel} options={[...models.map((m) => ({ value: m, label: m })), { value: CUSTOM, label: t("其他模型…") }]} placeholder={form.model || t("选择模型")} ariaLabel={t("模型")} />
                    : <div className="flex items-center gap-2">
                        <TextInput className="flex-1" value={form.model} onChange={(v) => setForm({ ...form, model: v })} placeholder={spec?.id === "openai_compatible" ? t("接口上的模型名，如 qwen-plus") : t("模型名")} ariaLabel={t("模型名")} />
                        {models.length > 0 && <Btn kind="text" onClick={() => pickModel(models[0])}>{t("列表")}</Btn>}
                      </div>}
                </Field>
                <Field label="API Key" wide hint={spec ? t("保存为环境变量 {0}", [spec.key_env]) : undefined}>
                  <div className="flex items-center gap-2">
                    <input type={showKey ? "text" : "password"} className="mm-control flex-1" value={form.api_key ?? ""} placeholder={keyPlaceholder} autoComplete="off" spellCheck={false} aria-label="API Key"
                      onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
                    <Btn kind="text" onClick={() => setShowKey(!showKey)}>{showKey ? t("隐藏") : t("显示")}</Btn>
                  </div>
                </Field>
                <Field label={spec?.needs_base ? "Base URL" : t("Base URL（可选）")} wide hint={spec ? t("保存为环境变量 {0}", [spec.base_env]) : undefined}>
                  <TextInput value={form.base_url ?? ""} onChange={(v) => setForm({ ...form, base_url: v })} placeholder={spec?.needs_base ? "https://host/v1" : t("留空用官方地址；走代理或中转时填")} ariaLabel="Base URL" />
                </Field>
                <Field label={t("最大重试")} hint={t("一次调用失败（格式错误、超时）后的重试次数")}>
                  <input type="number" className="mm-control" min={1} max={50} value={form.max_retry ?? 10} aria-label={t("最大重试")} onChange={(e) => setForm({ ...form, max_retry: Number(e.target.value) })} />
                </Field>
              </div>
              {message && <div className={message.tone === "bad" ? "text-danger" : message.tone === "ok" ? "text-success" : "text-muted"}>{message.text}</div>}
              <div className="flex flex-wrap items-center gap-2">
                <Btn kind="primary" disabled={!canSubmit || !!busy} onClick={save}>{busy === "save" ? t("保存中…") : t("保存")}</Btn>
                <Btn disabled={!canSubmit || !!busy} onClick={test}>{busy === "test" ? t("测试中…") : t("测试连接")}</Btn>
                <Btn kind="text" disabled={!form.provider || !!busy || (!storedHint && !form.api_key?.trim()) || (!!spec?.needs_base && !form.base_url?.trim())} onClick={() => fetchModels(form.provider, form.api_key, form.base_url, false)}>{busy === "list" ? t("拉取中…") : live ? t("重新拉取模型列表") : t("拉取模型列表")}</Btn>
                {spec?.site && <a className="mm-link ml-auto" href={spec.site} target="_blank" rel="noreferrer">{t("去 {0} 拿 Key ↗", [spec.label])}</a>}
              </div>
              <p className="m-0 border-t border-border pt-3 text-[11px] leading-relaxed text-muted">
                {t("保存后对之后新启动的研究（含“继续研究”）生效，正在跑的不受影响；Key 只写进本机的 traces/studio_data/llm.json（权限 600），不会回传到页面。每个提供商的 Key 各自保存，切换提供商时可以留空沿用。回测与组合搜索不用大模型。")}
              </p>
              {status && <EmbeddingSection status={status} chatProvider={current?.provider || ""} onStatus={(s) => { setStatus(s); onSaved(); }} />}
            </div>
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}

const EMBED_CUSTOM = "__custom__";

/**
 * The embedding model, a record of its own: RD-Agent's knowledge graph embeds every node it stores, and the
 * model-research scenarios do that from their first step. Chat-only providers cannot be picked here; a
 * provider already used for chat reuses its key.
 */
function EmbeddingSection({ status, chatProvider, onStatus }: { status: LlmStatus; chatProvider: string; onStatus: (s: LlmStatus) => void }) {
  const rec = status.embedding;
  const providers = status.providers.filter((p) => p.embeddings.length > 0 || p.id === "openai_compatible");
  const [form, setForm] = useState<EmbeddingForm>({ provider: rec.provider || "", model: rec.model, api_key: "", base_url: rec.base_url });
  const [custom, setCustom] = useState(false);
  const [remote, setRemote] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState<"" | "save" | "test" | "list">("");
  const [message, setMessage] = useState<{ tone: "ok" | "bad" | "info"; text: string } | null>(null);
  useEffect(() => { setForm({ provider: rec.provider || "", model: rec.model, api_key: "", base_url: rec.base_url }); }, [rec.provider, rec.model, rec.base_url]);

  const spec: LlmProvider | undefined = providers.find((p) => p.id === form.provider);
  const models = (form.provider && remote[form.provider]) || spec?.embeddings || [];
  const live = !!(form.provider && remote[form.provider]);
  const storedHint = form.provider ? (form.provider === rec.provider ? rec.key_hint : status.current.saved_keys[form.provider] || (form.provider === chatProvider ? status.current.key_hint : "")) : "";
  const keyKnown = !!spec?.no_key || !!storedHint;
  const canSubmit = !form.provider || (!!form.model.trim() && (!spec?.needs_base || !!form.base_url?.trim()) && (keyKnown || !!form.api_key?.trim()));

  const pick = (id: string) => {
    const p = providers.find((x) => x.id === id);
    const known = remote[id] || p?.embeddings || [];
    setForm({ provider: id, model: known.includes(form.model) ? form.model : known[0] ?? "", api_key: "", base_url: id === rec.provider ? rec.base_url : "" });
    setCustom(known.length === 0); setMessage(null);
  };
  const fetchModels = async (quiet: boolean) => {
    setBusy("list");
    try {
      const r = await studio.listLlmModels({ provider: form.provider, api_key: form.api_key, base_url: form.base_url, kind: "embedding" });
      if (r.ok && r.models) { setRemote((m) => ({ ...m, [form.provider]: r.models! })); if (!quiet) setMessage({ tone: "info", text: t("已从 {0} 拉到 {1} 个模型", [r.source, r.models.length]) }); }
      else if (!quiet) setMessage({ tone: "bad", text: t("拉取模型列表失败：{0}", [r.error]) });
    } catch (e) { if (!quiet) setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  };
  useEffect(() => {
    if (!form.provider || remote[form.provider] || (spec?.needs_base && !form.base_url?.trim()) || (!keyKnown && !form.api_key?.trim())) return;
    fetchModels(true);
  }, [form.provider, keyKnown]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async () => {
    setBusy("save"); setMessage(null);
    try { onStatus(await studio.saveEmbeddingSettings(form)); setMessage({ tone: "ok", text: form.provider ? t("已保存嵌入模型设置。") : t("已清除嵌入模型设置。") }); }
    catch (e) { setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  };
  const test = async () => {
    setBusy("test"); setMessage({ tone: "info", text: t("正在调用嵌入模型…") });
    try {
      const r = await studio.testEmbeddingSettings(form);
      setMessage(r.ok ? { tone: "ok", text: t("嵌入正常：{0} 在 {1}s 内返回 {2} 维向量", [r.model, r.seconds, r.dims]) } : { tone: "bad", text: t("嵌入失败：{0}", [r.error]) });
    } catch (e) { setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  };
  const state = !rec.provider ? t("未配置") : !rec.has_key ? t("缺 API Key") : `${rec.provider === "openai_compatible" ? "" : (status.providers.find((p) => p.id === rec.provider)?.label || rec.provider) + " · "}${rec.model}`;

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3">
      <div>
        <div className="text-[13px] font-semibold">{t("嵌入模型")} <span className={`ml-1 text-[11px] font-normal ${rec.provider && rec.has_key ? "text-muted" : "text-warning"}`}>{state}</span></div>
        <div className="text-[11px] text-muted">{t("模型研发、因子 × 模型联合和论文模型实现会用 RD-Agent 的知识图谱，图谱里每条知识都要算一次向量嵌入；因子研发不用。DeepSeek、Anthropic、Moonshot 没有嵌入接口，需要另配一家，或用本机的 Ollama。")}</div>
      </div>
      <div className="grid grid-cols-2 gap-3 [&>.mm-field--wide]:col-span-2">
        <Field label={t("提供商")}>
          <SelectInput value={form.provider} onChange={pick} options={[{ value: "", label: t("不配置") }, ...providers.map((p) => ({ value: p.id, label: p.label, hint: p.id === chatProvider ? t("沿用聊天模型的 Key") : undefined }))]} placeholder={t("选择提供商")} ariaLabel={t("嵌入提供商")} />
        </Field>
        {form.provider && (
          <Field label={<>{t("模型")}{live ? <span className="text-success"> {t("· 实时列表")}</span> : models.length ? <span> {t("· 文档默认")}</span> : null}</>} wide={custom && models.length > 0}>
            {models.length > 0 && !custom
              ? <SelectInput value={models.includes(form.model) ? form.model : ""} onChange={(v) => { if (v === EMBED_CUSTOM) { setCustom(true); setForm({ ...form, model: "" }); } else { setCustom(false); setForm({ ...form, model: v }); } }} options={[...models.map((m) => ({ value: m, label: m })), { value: EMBED_CUSTOM, label: t("其他模型…") }]} placeholder={form.model || t("选择模型")} ariaLabel={t("嵌入模型")} />
              : <div className="flex items-center gap-2">
                  <TextInput className="flex-1" value={form.model} onChange={(v) => setForm({ ...form, model: v })} placeholder={spec?.id === "openai_compatible" ? t("接口上的模型名，如 BAAI/bge-m3") : t("模型名")} ariaLabel={t("嵌入模型名")} />
                  {models.length > 0 && <Btn kind="text" onClick={() => { setCustom(false); setForm({ ...form, model: models[0] }); }}>{t("列表")}</Btn>}
                </div>}
          </Field>
        )}
        {form.provider && !spec?.no_key && (
          <Field label="API Key" wide hint={spec ? t("保存为环境变量 {0}", [spec.key_env]) : undefined}>
            <input type="password" className="mm-control w-full" value={form.api_key ?? ""} autoComplete="off" spellCheck={false} aria-label={t("嵌入 API Key")}
              placeholder={storedHint ? t("{0} {1}，留空则沿用", [form.provider === chatProvider ? t("聊天模型的 Key") : t("已保存"), storedHint]) : t("粘贴 API Key")}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          </Field>
        )}
        {form.provider && (spec?.needs_base || spec?.no_key || spec?.id === "ollama") && (
          <Field label={spec?.needs_base ? "Base URL" : t("Base URL（可选）")} wide hint={spec ? t("保存为环境变量 {0}", [spec.base_env]) : undefined}>
            <TextInput value={form.base_url ?? ""} onChange={(v) => setForm({ ...form, base_url: v })} placeholder={spec?.needs_base ? "https://api.siliconflow.cn/v1" : "http://localhost:11434"} ariaLabel={t("嵌入 Base URL")} />
          </Field>
        )}
      </div>
      {message && <div className={message.tone === "bad" ? "text-danger" : message.tone === "ok" ? "text-success" : "text-muted"}>{message.text}</div>}
      <div className="flex flex-wrap items-center gap-2">
        <Btn kind="primary" disabled={!canSubmit || !!busy} onClick={save}>{busy === "save" ? t("保存中…") : form.provider ? t("保存嵌入设置") : t("清除嵌入设置")}</Btn>
        {form.provider && <Btn disabled={!canSubmit || !!busy} onClick={test}>{busy === "test" ? t("测试中…") : t("测试嵌入")}</Btn>}
        {form.provider && <Btn kind="text" disabled={!!busy || (!keyKnown && !form.api_key?.trim()) || (!!spec?.needs_base && !form.base_url?.trim())} onClick={() => fetchModels(false)}>{busy === "list" ? t("拉取中…") : live ? t("重新拉取模型列表") : t("拉取模型列表")}</Btn>}
        {spec?.site && <a className="mm-link ml-auto" href={spec.site} target="_blank" rel="noreferrer">{spec.id === "ollama" ? t("安装 Ollama ↗") : t("去 {0} 拿 Key ↗", [spec.label])}</a>}
      </div>
    </div>
  );
}
