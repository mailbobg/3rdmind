import type { ReactNode } from "react";
import { Description, Label, ListBox, NumberField, Select, TextField, Input, Tabs } from "@heroui/react";

/** Compact labelled controls for the parameter bars. */
export function NumberBox({ label, value, onChange, hint, min, max, step, width = 110, isDisabled }:
  { label: string; value: number; onChange: (v: number) => void; hint?: string; min?: number; max?: number; step?: number; width?: number; isDisabled?: boolean }) {
  return (
    <NumberField value={value} onChange={(v) => { if (Number.isFinite(v)) onChange(v); }} minValue={min} maxValue={max} step={step} isDisabled={isDisabled} style={{ width }} formatOptions={{ maximumFractionDigits: 6, useGrouping: false }}>
      <Label className="text-[11px] text-muted" title={hint}>{label}</Label>
      <NumberField.Group><NumberField.Input className="w-full" /></NumberField.Group>
    </NumberField>
  );
}

export function TextBox({ label, value, onChange, placeholder, width = 130 }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; width?: number }) {
  return (
    <TextField value={value} onChange={onChange} style={{ width }}>
      <Label className="text-[11px] text-muted">{label}</Label>
      <Input placeholder={placeholder} />
    </TextField>
  );
}

/** Native date input inside a HeroUI-styled shell: ISO strings in and out, matching what the backend expects. */
export function DateBox({ label, value, onChange, width = 140 }: { label: string; value: string; onChange: (v: string) => void; width?: number }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-muted" style={{ width }}>{label}
      <input type="date" value={value} onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-foreground shadow-sm outline-none focus:border-accent" />
    </label>
  );
}

export function SelectBox<T extends string>({ label, value, onChange, options, width = 150, placeholder, isLabelHidden }:
  { label: string; value: T | null; onChange: (v: T) => void; options: { value: T; label: string; description?: string }[]; width?: number; placeholder?: string; isLabelHidden?: boolean }) {
  return (
    <Select selectedKey={value} onSelectionChange={(k) => k != null && onChange(String(k) as T)} placeholder={placeholder} style={{ width }} aria-label={isLabelHidden ? label : undefined}>
      {!isLabelHidden && <Label className="text-[11px] text-muted">{label}</Label>}
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
