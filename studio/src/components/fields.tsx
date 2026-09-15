import { Description, Label, ListBox, Select } from "@heroui/react";

/** Labelled HeroUI select for the results column (backtest history); the work column uses the native `SelectInput`. */
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
