import { useEffect, useRef, useState } from "react";
import type { SettingItem } from "@/lib/types";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label } from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { AlertCircle, Eye, EyeOff, RotateCcw, Save } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Renders a single settings row. Type-aware:
 *   str  → <input type="text">
 *   int  → <input type="number">
 *   float→ <input type="number" step>
 *   bool → checkbox
 *   enum → <select>
 *
 * Sensitive keys get a password input with "show / hide" toggle and a
 * "clear" button that resets to the default value.
 */
export function SettingField({
  item,
  error,
  onChange,
}: {
  item: SettingItem;
  error?: string;
  onChange: (next: { value: string; clear: boolean; touched: boolean }) => void;
}) {
  const inputId = `setting-${item.key.replace(/\./g, "-")}`;
  const helpId = `${inputId}-help`;
  const [showSecret, setShowSecret] = useState(false);

  if (item.sensitive) {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={inputId}>{item.label}</Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Input
              id={inputId}
              type={showSecret ? "text" : "password"}
              value=""
              placeholder={item.value_set ? "•••••••• (unchanged)" : "not set"}
              onChange={(e) => onChange({ value: e.target.value, clear: false, touched: true })}
              autoComplete="off"
              className="pr-9"
            />
            <button
              type="button"
              onClick={() => setShowSecret((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
              aria-label={showSecret ? "Hide" : "Show"}
            >
              {showSecret ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange({ value: "", clear: true, touched: true })}
            disabled={!item.value_set}
            className="gap-1.5"
            title="Reset to default"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Clear
          </Button>
        </div>
        <p id={helpId} className="text-xs text-muted-foreground">
          {item.help || "Leave blank to keep the current value."}
        </p>
        {error && <FieldError error={error} />}
      </div>
    );
  }

  if (item.type === "bool") {
    return (
      <div className="space-y-1.5">
        <label htmlFor={inputId} className="flex items-center gap-2 text-sm font-medium leading-none">
          <input
            id={inputId}
            type="checkbox"
            checked={item.value === "true"}
            onChange={(e) => onChange({ value: e.target.checked ? "true" : "false", clear: false, touched: true })}
            className="h-4 w-4 rounded border-input"
          />
          {item.label}
        </label>
        {item.help && (
          <p id={helpId} className="text-xs text-muted-foreground">
            {item.help}
          </p>
        )}
        {error && <FieldError error={error} />}
      </div>
    );
  }

  if (item.type === "enum") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={inputId}>{item.label}</Label>
        <select
          id={inputId}
          value={item.value}
          onChange={(e) => onChange({ value: e.target.value, clear: false, touched: true })}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {(item.choices ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        {item.help && (
          <p id={helpId} className="text-xs text-muted-foreground">
            {item.help}
          </p>
        )}
        {error && <FieldError error={error} />}
      </div>
    );
  }

  const isNumeric = item.type === "int" || item.type === "float";
  const step = item.step ?? (item.type === "int" ? 1 : 0.01);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={inputId}>
        {item.label}
        {isNumeric && item.min != null && item.max != null && (
          <span className="ml-1.5 text-xs font-normal text-muted-foreground">
            ({item.min}–{item.max})
          </span>
        )}
      </Label>
      <Input
        id={inputId}
        type={isNumeric ? "number" : "text"}
        step={step}
        min={item.min ?? undefined}
        max={item.max ?? undefined}
        value={item.value}
        onChange={(e) => onChange({ value: e.target.value, clear: false, touched: true })}
      />
      {item.help && (
        <p id={helpId} className="text-xs text-muted-foreground">
          {item.help}
        </p>
      )}
      {error && <FieldError error={error} />}
    </div>
  );
}

function FieldError({ error }: { error: string }) {
  return (
    <p className="flex items-center gap-1 text-xs text-destructive">
      <AlertCircle className="h-3 w-3" /> {error}
    </p>
  );
}

/**
 * A full settings card. Pass the settings that belong to this card
 * and a save handler. Edits are buffered locally so the API is only
 * hit when the user clicks Save; sensitive fields with no value
 * entered are skipped (treat as "keep current").
 */
export function SettingsCard({
  title,
  description,
  items,
  onSave,
  saving,
  globalError,
  saveLabel = "Save",
}: {
  title: string;
  description?: string;
  items: SettingItem[];
  onSave: (updates: { key: string; value: string; clear: boolean }[]) => void;
  saving: boolean;
  globalError?: string;
  saveLabel?: string;
}) {
  // Local edits: {key -> {value, clear, touched}}
  const [edits, setEdits] = useState<
    Record<string, { value: string; clear: boolean; touched: boolean }>
  >({});
  // Server-side validation errors: {key -> error message}.
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Per-field local validation errors (range / type).
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});

  const setEdit = (key: string, next: { value: string; clear: boolean; touched: boolean }) => {
    setEdits((prev) => ({ ...prev, [key]: next }));
    setErrors((prev) => {
      const rest = { ...prev };
      delete rest[key];
      return rest;
    });
    setLocalErrors((prev) => {
      const rest = { ...prev };
      delete rest[key];
      return rest;
    });
  };

  const dirty = Object.values(edits).some((e) => e.touched);

  const validateLocally = (): boolean => {
    const errs: Record<string, string> = {};
    for (const it of items) {
      const ed = edits[it.key];
      if (!ed || !ed.touched || ed.clear) continue;
      if (it.sensitive) continue; // empty value means "keep current"
      const raw = ed.value.trim();
      if (it.type === "int" || it.type === "float") {
        const v = it.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
        if (raw === "" || Number.isNaN(v)) {
          errs[it.key] = it.type === "int" ? "Must be a whole number." : "Must be a number.";
          continue;
        }
        if (it.min != null && v < it.min) errs[it.key] = `Must be ≥ ${it.min}.`;
        if (it.max != null && v > it.max) errs[it.key] = `Must be ≤ ${it.max}.`;
      }
    }
    setLocalErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const submit = () => {
    if (!dirty) return;
    if (!validateLocally()) return;
    const updates = items
      .map((it) => {
        const ed = edits[it.key];
        if (!ed || !ed.touched) return null;
        // Skip empty sensitive values → "keep current".
        if (it.sensitive && !ed.clear && ed.value === "") return null;
        return { key: it.key, value: ed.value, clear: ed.clear };
      })
      .filter((u): u is { key: string; value: string; clear: boolean } => u !== null);
    if (updates.length === 0) return;
    onSave(updates);
  };

  // Reset edits + errors after a successful save (parent does this via
  // the `saving` flag flipping back to false and `items` reloading).
  // We also clear edits when the underlying items refresh so the form
  // is in sync with what's now stored on the server.
  const itemSig = items.map((i) => `${i.key}:${i.value}:${i.value_set ? 1 : 0}:${i.sensitive ? 1 : 0}`).join("|");
  // Track last-applied signature; clear edits when it changes.
  useEffectReset(itemSig, () => {
    setEdits({});
    setErrors({});
    setLocalErrors({});
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-5">
        {items.map((it) => (
          <SettingField
            key={it.key}
            item={{
              ...it,
              value: edits[it.key]?.touched && !it.sensitive
                ? edits[it.key]!.value
                : it.value,
            }}
            error={errors[it.key] ?? localErrors[it.key]}
            onChange={(next) => setEdit(it.key, next)}
          />
        ))}
        {globalError && <ErrorBanner message={globalError} />}
        <div className="flex items-center gap-2 pt-1">
          <Button
            type="button"
            onClick={submit}
            disabled={!dirty || saving}
            className="gap-2"
          >
            <Save className="h-4 w-4" /> {saving ? "Saving…" : saveLabel}
          </Button>
          {!dirty && (
            <span className="text-xs text-muted-foreground">No unsaved changes.</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/** Tiny hook: re-runs `effect` whenever `sig` changes. */
function useEffectReset(sig: string, effect: () => void) {
  const prev = useRef(sig);
  useEffect(() => {
    if (prev.current !== sig) {
      prev.current = sig;
      effect();
    }
  }, [sig, effect]);
}

/**
 * Renders a small two-column key/value row inside the read-only
 * sections of the Device page (e.g. service uptime, software version).
 */
export function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className={cn("flex items-start justify-between gap-4")}>
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}
