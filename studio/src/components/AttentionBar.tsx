import type { AttentionItem, Job } from "../api/studio";
import { ATTENTION_LABELS } from "../hooks/useAttention";
import type { NotifyPrefs } from "../hooks/useAttention";
import { shortName } from "../hooks/studioContext";
import { fmtDuration } from "../hooks/progress";
import { Btn } from "./minimal";
import { t } from "../i18n";

/**
 * The thin banner above every page while a run waits on the user: who is waiting, for what, since when, a
 * jump button, and the two notification switches.
 */
export function AttentionBar({ items, now, prefs, setPrefs, onOpen, failures = [], onOpenJob, onDismissFailure }: {
  items: AttentionItem[]; now: number; prefs: NotifyPrefs; setPrefs: (p: Partial<NotifyPrefs>) => void; onOpen: (i: AttentionItem) => void;
  failures?: Job[]; onOpenJob?: (j: Job) => void; onDismissFailure?: (id: string) => void }) {
  if (!items.length) {
    if (!failures.length) return null;
    const [f, ...more] = failures;
    return (
      <div className="attn attn--bad" role="status">
        <i className="attn__dot attn__dot--bad" aria-hidden />
        <span className="attn__text"><strong>{f.label}</strong> 失败{f.error ? <span className="mm-dim">：{f.error.slice(0, 140)}</span> : null}{more.length ? <span className="mm-dim"> {t("· 还有 {0} 个", [more.length])}</span> : null}</span>
        {onOpenJob && f.link?.page && <Btn onClick={() => onOpenJob(f)}>{t("查看")}</Btn>}
        {onDismissFailure && <Btn kind="text" onClick={() => onDismissFailure(f.id)}>{t("忽略")}</Btn>}
      </div>
    );
  }
  const [head, ...rest] = items;
  const since = head.since ? now - new Date(head.since).getTime() : null;
  return (
    <div className="attn" role="status">
      <i className="live__dot attn__dot" aria-hidden />
      <span className="attn__text">
        <strong>{shortName(head.trace)}</strong> 在等你确认{ATTENTION_LABELS[head.kind]}{head.round ? t("（第 {0} 轮）", [head.round]) : ""}
        {since != null && since > 30_000 ? <span className="mm-dim"> {t("· 已等 {0}", [fmtDuration(since)])}</span> : null}
        {rest.length ? <span className="mm-dim"> {t("· 还有 {0} 个", [rest.length])}</span> : null}
      </span>
      <Btn kind="primary" onClick={() => onOpen(head)}>{t("去确认 →")}</Btn>
      <span className="attn__prefs">
        <label className="attn__pref"><input type="checkbox" className="mm-check" checked={prefs.desktop} onChange={(e) => setPrefs({ desktop: e.target.checked })} /> {t("桌面通知")}</label>
        <label className="attn__pref"><input type="checkbox" className="mm-check" checked={prefs.sound} onChange={(e) => setPrefs({ sound: e.target.checked })} /> {t("提示音")}</label>
      </span>
    </div>
  );
}
