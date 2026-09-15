import type { ReactNode } from "react";
import { Description, Label, ListBox, NumberField, Select, TextField, Input, Tabs } from "@heroui/react";

/**
 * Compact labelled controls for the parameter rows. Every control is 32px high with a 12px label above,
 * so a row of mixed fields lines up on one baseline.
 */
export function NumberBox({ label, value, onChange, hint, min, max, step, width = 100, isDisabled }:
  { label: string; value: number; onChange: (v: number) => void; hint?: string; min?: number; max?: number; step?: number; width?: number; isDisabled?: boolean }) {
  return (
    <NumberField value={value} onChange={(v) => { if (Number.isFinite(v)) onChange(v); }} minValue={min} maxValue={max} step={step} isDisabled={isDisabled} style={{ width }} formatOptions={{ maximumFractionDigits: 6, useGrouping: false }}>
      <Label className="field-label" title={hint}>{label}</Label>
      <NumberField.Group><NumberField.Input className="w-full" /></NumberField.Group>
    </NumberField>
  );
}

export function TextBox({ label, value, onChange, placeholder, width = 130 }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; width?: number }) {
  return (
    <TextField value={value} onChange={onChange} style={{ width }}>
      <Label className="field-label">{label}</Label>
      <Input placeholder={placeholder} />
    </TextField>
  );
}

/** Native date input styled like the HeroUI inputs: ISO strings in and out, which is what the backend expects. */
export function DateBox({ label, value, onChange, width = 136 }: { label: string; value: string; onChange: (v: string) => void; width?: number }) {
  return (
    <label className="flex flex-col gap-1 field-label" style={{ width }}>{label}
      <input type="date" value={value} onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-lg border border-border bg-surface px-2.5 text-[13px] text-foreground shadow-xs outline-none focus:border-accent" />
    </label>
  );
}

export function SelectBox<T extends string>({ label, value, onChange, options, width = 150, placeholder, isLabelHidden }:
  { label: string; value: T | null; onChange: (v: T) => void; options: { value: T; label: string; description?: string }[]; width?: number; placeholder?: string; isLabelHidden?: boolean }) {
  return (
    <Select selectedKey={value} onSelectionChange={(k) => k != null && onChange(String(k) as T)} placeholder={placeholder} style={{ width }} aria-label={isLabelHidden ? label : undefined}>
      {!isLabelHidden && <Label className="field-label">{label}</Label>}
      <Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
      <Select.Popover>
        <ListBox>
          {options.map((o) => (
            <ListBox.Item key={o.value} id={o.value} textValue={o.label}>
              <Label>{o.label}</Label>
              {o.description && <Description>{o.description}</Description>}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

export function TabBar({ value, onChange, items, label }: { value: string; onChange: (v: string) => void; items: { key: string; label: ReactNode }[]; label: string }) {
  return (
    <Tabs selectedKey={value} onSelectionChange={(k) => onChange(String(k))}>
      <Tabs.ListContainer>
        <Tabs.List aria-label={label}>
          {items.map((t) => <Tabs.Tab key={t.key} id={t.key} className="whitespace-nowrap">{t.label}<Tabs.Indicator /></Tabs.Tab>)}
        </Tabs.List>
      </Tabs.ListContainer>
    </Tabs>
  );
}

/** A labelled group inside a parameter row: caption on the left, fields on the right, separated from the next group. */
export function ParamGroup({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div className="flex items-end gap-2 border-r border-border pr-3 last:border-r-0 last:pr-0">
      <span className="field-label pb-2">{caption}</span>
      {children}
    </div>
  );
}

/** One row in a list-style middle panel: click to select, optional leading control, trailing metrics. */
export function ListRow({ selected, onSelect, leading, children, trailing }: { selected?: boolean; onSelect?: () => void; leading?: ReactNode; children: ReactNode; trailing?: ReactNode }) {
  return (
    <div role={onSelect ? "button" : undefined} tabIndex={onSelect ? 0 : undefined} onClick={onSelect} onKeyDown={(e) => { if (onSelect && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSelect(); } }}
      className={`flex items-center gap-3 border-b border-border px-3 py-2 last:border-b-0 ${onSelect ? "cursor-pointer hover:bg-surface-secondary" : ""} ${selected ? "bg-accent/8 shadow-[inset_3px_0_0_var(--accent)]" : ""}`}>
      {leading && <div className="shrink-0" onClick={(e) => e.stopPropagation()}>{leading}</div>}
      <div className="min-w-0 flex-1">{children}</div>
      {trailing && <div className="flex shrink-0 items-center gap-3">{trailing}</div>}
    </div>
  );
}

/** Small right-aligned number with a caption, for ListRow trailing slots. */
export function Stat({ label, children, width = 72 }: { label: string; children: ReactNode; width?: number }) {
  return (
    <div className="flex flex-col items-end" style={{ width }}>
      <span className="text-[11px] text-muted">{label}</span>
      <span className="text-[13px] tabular-nums">{children}</span>
    </div>
  );
}
