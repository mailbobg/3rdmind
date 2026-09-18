import { useState } from "react";
import type { AttentionItem, Job } from "../api/studio";
import { ATTENTION_LABELS } from "../hooks/useAttention";
import { JOB_KIND_LABELS } from "../hooks/useJobs";
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
  const waiting = items.length ? <WaitingBar items={items} now={now} prefs={prefs} setPrefs={setPrefs} onOpen={onOpen} /> : null;
  const failed = failures.length ? <FailureList failures={failures} now={now} onOpen={onOpenJob} onDismiss={onDismissFailure} /> : null;
  if (!waiting && !failed) return null;
  return <>{waiting}{failed}</>;
}

function WaitingBar({ items, now, prefs, setPrefs, onOpen }: {
  items: AttentionItem[]; now: number; prefs: NotifyPrefs; setPrefs: (p: Partial<NotifyPrefs>) => void; onOpen: (i: AttentionItem) => void }) {
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

/**
 * Failed jobs, every one of them visible at once: a header with the count and "dismiss all", then one row per
 * failure (kind, label, when, the error on one line, expandable to the full text, jump and dismiss buttons).
 */
function FailureList({ failures, now, onOpen, onDismiss }: { failures: Job[]; now: number; onOpen?: (j: Job) => void; onDismiss?: (id: string) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <section className="fails" role="status" aria-label={t("失败的任务")}>
      <header className="fails__head">
        <span className="fails__title">{failures.length === 1 ? t("1 个任务失败") : t("{0} 个任务失败", [failures.length])}</span>
        <span className="fails__hint">{t("失败的任务留在这里，直到你忽略它；完整错误在运行记录里也能看到。")}</span>
        {onDismiss && failures.length > 1 && <Btn kind="text" onClick={() => failures.forEach((f) => onDismiss(f.id))}>{t("全部忽略")}</Btn>}
      </header>
      <ul className="fails__list">
        {failures.map((f) => {
          const ago = f.finished ? now - new Date(f.finished).getTime() : null;
          const open = expanded === f.id;
          return (
            <li key={f.id} className="fails__row">
              <span className="fails__kind">{JOB_KIND_LABELS[f.kind] || f.kind}</span>
              <span className="fails__main">
                <span className="fails__label">{f.label}{ago != null && ago > 0 ? <span className="fails__when"> · {t("{0} 前", [fmtDuration(ago)])}</span> : null}</span>
                {f.error && (
                  <button type="button" className={`fails__error ${open ? "fails__error--open" : ""}`} title={open ? t("收起") : t("展开完整错误")} onClick={() => setExpanded(open ? null : f.id)}>
                    {f.error}
                  </button>
                )}
              </span>
              <span className="fails__actions">
                {onOpen && f.link?.page && <Btn onClick={() => onOpen(f)}>{t("查看")}</Btn>}
                {onDismiss && <Btn kind="text" onClick={() => onDismiss(f.id)}>{t("忽略")}</Btn>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
