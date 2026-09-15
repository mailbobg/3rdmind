import type { ReactNode } from "react";
import { Card } from "@heroui/react";

/** A results-column block: heading row with a muted note on the right, then content. */
export function Section(p: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <Card className="gap-2 p-3">
      <div className="flex items-center justify-between gap-2.5">
        <span className="text-xs font-semibold text-foreground">{p.title}</span>
        {p.note && <span className="text-[11px] text-muted">{p.note}</span>}
      </div>
      <div className="flex flex-col gap-2">{p.children}</div>
    </Card>
  );
}
