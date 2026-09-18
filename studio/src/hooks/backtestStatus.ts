import { t } from "../i18n";
export const BACKTEST_STATUS_LABELS: Record<string, string> = {
  queued: t("排队中"),
  running: t("运行中"),
  completed: t("已完成"),
  failed: t("失败"),
};

export function backtestStatusLabel(status: string): string {
  return BACKTEST_STATUS_LABELS[status] || status;
}
