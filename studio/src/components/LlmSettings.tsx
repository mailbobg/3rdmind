import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as studio from "../api/studio";
import type { LlmForm, LlmStatus } from "../api/studio";
import { errorText } from "../hooks/studioContext";
import { Btn, Field, SelectInput, TextInput } from "./minimal";

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
        if (!quiet) setMessage({ tone: "info", text: `已从 ${r.source} 拉到 ${r.models.length} 个模型` });
      } else if (!quiet) setMessage({ tone: "bad", text: `拉取模型列表失败：${r.error}` });
    } catch (e) { if (!quiet) setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  }, []);
  // Whenever the sheet shows a provider that has a usable key and no live list yet, fetch its list quietly.
  useEffect(() => {
    if (!open || !form.provider || remote[form.provider] || spec?.needs_base && !form.base_url?.trim()) return;
    if (!storedHint && !form.api_key?.trim()) return;
    fetchModels(form.provider, form.api_key, form.base_url, true);
  }, [open, form.provider, storedHint]); // eslint-disable-line react-hooks/exhaustive-deps
  const keyPlaceholder = storedHint ? `${form.provider === current?.provider && current.key_from_env ? "沿用 .env 里的" : "已保存"} ${storedHint}，留空则沿用` : "粘贴 API Key";
  const canSubmit = !!form.provider && !!form.model.trim() && (!spec?.needs_base || !!form.base_url?.trim()) && (!!form.api_key?.trim() || !!storedHint);

  const test = async () => {
    setBusy("test"); setMessage({ tone: "info", text: "正在调用模型…" });
    try {
      const r = await studio.testLlmSettings(form);
      setMessage(r.ok ? { tone: "ok", text: `连接正常：${r.model} 在 ${r.seconds}s 内响应${r.reply ? `，回复 “${r.reply}”` : ""}` } : { tone: "bad", text: `连接失败：${r.error}` });
    } catch (e) { setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  };
  const save = async () => {
    setBusy("save"); setMessage(null);
    try {
      const s = await studio.saveLlmSettings(form);
      setStatus(s); setForm({ ...form, api_key: "" }); onSaved();
      setMessage({ tone: "ok", text: "已保存，之后新启动的研究都用这套设置。" });
    } catch (e) { setMessage({ tone: "bad", text: errorText(e) }); } finally { setBusy(""); }
  };

  useEffect(() => { if (live && models.includes(form.model)) setCustomModel(false); }, [live, models, form.model]);
  const headline = !current ? "" : !current.provider ? "未配置" : !current.has_key ? "缺 API Key" : current.model;
  const warn = !!current && (!current.provider || !current.has_key);

  return (
    <div className="text-xs">
      <button type="button" onClick={openSheet} aria-haspopup="dialog" aria-expanded={open}
        className="-mx-2.5 flex w-[calc(100%+20px)] items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-left text-foreground transition-colors hover:bg-surface-secondary">
        <span className="w-[22px] text-center text-[17px] leading-none" aria-hidden>⚙︎</span>
        <span className="min-w-0 flex-1 text-[13px] font-medium">模型设置</span>
        <span className={`flex min-w-0 items-center gap-1.5 text-[11px] ${warn ? "text-warning" : "text-muted"}`}>
          {warn && <i className="inline-block size-[6px] shrink-0 rounded-full bg-warning" />}
          <span className="truncate" title={headline}>{headline}</span>
        </span>
      </button>
      {open && createPortal(
        <>
          <div className="sheet-backdrop" onClick={() => setOpen(false)} />
          <div className="sheet" role="dialog" aria-label="模型设置">
            <div className="sheet__head">
              <div>
                <div className="sheet__title">模型设置</div>
                <div className="text-[11px] text-muted">研究用的大模型 · 通过 LiteLLM 调用{current?.source === "env" ? " · 当前来自启动时的 .env" : current?.updated ? ` · 保存于 ${current.updated}` : ""}</div>
              </div>
              <Btn kind="text" onClick={() => setOpen(false)}>关闭</Btn>
            </div>
            <div className="sheet__body">
              <div className="grid grid-cols-2 gap-3 [&>.mm-field--wide]:col-span-2">
                <Field label="提供商">
                  <SelectInput value={form.provider} onChange={pickProvider} options={providers.map((p) => ({ value: p.id, label: p.label }))} placeholder="选择提供商" ariaLabel="提供商" />
                </Field>
                <Field label={<>模型{live ? <span className="text-success"> · 实时列表</span> : models.length ? <span> · 文档默认</span> : null}</>} wide={customModel && models.length > 0}>
                  {models.length > 0 && !customModel
                    ? <SelectInput value={models.includes(form.model) ? form.model : ""} onChange={pickModel} options={[...models.map((m) => ({ value: m, label: m })), { value: CUSTOM, label: "其他模型…" }]} placeholder={form.model || "选择模型"} ariaLabel="模型" />
                    : <div className="flex items-center gap-2">
                        <TextInput className="flex-1" value={form.model} onChange={(v) => setForm({ ...form, model: v })} placeholder={spec?.id === "openai_compatible" ? "接口上的模型名，如 qwen-plus" : "模型名"} ariaLabel="模型名" />
                        {models.length > 0 && <Btn kind="text" onClick={() => pickModel(models[0])}>列表</Btn>}
                      </div>}
                </Field>
                <Field label="API Key" wide hint={spec ? `保存为环境变量 ${spec.key_env}` : undefined}>
                  <div className="flex items-center gap-2">
                    <input type={showKey ? "text" : "password"} className="mm-control flex-1" value={form.api_key ?? ""} placeholder={keyPlaceholder} autoComplete="off" spellCheck={false} aria-label="API Key"
                      onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
                    <Btn kind="text" onClick={() => setShowKey(!showKey)}>{showKey ? "隐藏" : "显示"}</Btn>
                  </div>
                </Field>
                <Field label={spec?.needs_base ? "Base URL" : "Base URL（可选）"} wide hint={spec ? `保存为环境变量 ${spec.base_env}` : undefined}>
                  <TextInput value={form.base_url ?? ""} onChange={(v) => setForm({ ...form, base_url: v })} placeholder={spec?.needs_base ? "https://host/v1" : "留空用官方地址；走代理或中转时填"} ariaLabel="Base URL" />
                </Field>
                <Field label="最大重试" hint="一次调用失败（格式错误、超时）后的重试次数">
                  <input type="number" className="mm-control" min={1} max={50} value={form.max_retry ?? 10} aria-label="最大重试" onChange={(e) => setForm({ ...form, max_retry: Number(e.target.value) })} />
                </Field>
              </div>
              {message && <div className={message.tone === "bad" ? "text-danger" : message.tone === "ok" ? "text-success" : "text-muted"}>{message.text}</div>}
              <div className="flex flex-wrap items-center gap-2">
                <Btn kind="primary" disabled={!canSubmit || !!busy} onClick={save}>{busy === "save" ? "保存中…" : "保存"}</Btn>
                <Btn disabled={!canSubmit || !!busy} onClick={test}>{busy === "test" ? "测试中…" : "测试连接"}</Btn>
                <Btn kind="text" disabled={!form.provider || !!busy || (!storedHint && !form.api_key?.trim()) || (!!spec?.needs_base && !form.base_url?.trim())} onClick={() => fetchModels(form.provider, form.api_key, form.base_url, false)}>{busy === "list" ? "拉取中…" : live ? "重新拉取模型列表" : "拉取模型列表"}</Btn>
                {spec?.site && <a className="mm-link ml-auto" href={spec.site} target="_blank" rel="noreferrer">去 {spec.label} 拿 Key ↗</a>}
              </div>
              <p className="m-0 border-t border-border pt-3 text-[11px] leading-relaxed text-muted">
                保存后对之后新启动的研究（含"继续研究"）生效，正在跑的不受影响；Key 只写进本机的 traces/studio_data/llm.json（权限 600），不会回传到页面。每个提供商的 Key 各自保存，切换提供商时可以留空沿用。回测与组合搜索不用大模型。
              </p>
            </div>
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
