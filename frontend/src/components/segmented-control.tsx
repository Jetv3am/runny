"use client";

import { useId } from "react";

export type SegmentOption<T extends string> = { value: T; label: React.ReactNode };

/**
 * Ramp-style segmented control, built on native radios: arrow keys, focus, and
 * screen-reader semantics come for free. One implementation for every toggle in the app.
 */
export function SegmentedControl<T extends string>({ label, options, value, onChange, size = "md" }: {
  /** Accessible group name (visually hidden). */
  label: string;
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  const name = useId(); // unique per instance: several controls can share a page
  const pad = size === "sm" ? "h-7 px-2.5 text-[13px]" : "h-8 px-3 text-[13px]";
  return (
    <fieldset className="inline-flex max-w-full overflow-x-auto rounded-lg bg-hover p-0.5">
      <legend className="sr-only">{label}</legend>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <label
            key={option.value}
            className={`flex shrink-0 cursor-pointer items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ink ${pad} ${
              selected ? "bg-surface text-ink shadow-hairline ring-1 ring-line" : "text-ink-muted hover:text-ink"
            }`}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={selected}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        );
      })}
    </fieldset>
  );
}
