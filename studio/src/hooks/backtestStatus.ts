export const BACKTEST_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

export function backtestStatusLabel(status: string): string {
  return BACKTEST_STATUS_LABELS[status] || status;
}
