import { useMemo, useState } from "react";
import { useAllSettings, useUpdateSettings } from "@/lib/queries";
import { Card, CardContent, Spinner } from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { SettingsCard } from "@/components/SettingsField";
import { resultsToErrorMap } from "@/components/settingsUtils";
import type { SettingItem } from "@/lib/types";

/**
 * System page — every setting that is NOT specific to the local
 * device. Card layout matches the META `subsection` taxonomy
 * defined in `engine/defaults.py`:
 *
 *   - Enrollment    (§3.3)
 *   - Retention     (§3.12.3, §3.12.4)
 *   - Storage       (§3.11.2)
 *   - Sync          (§3.7.6, §3.7.10)
 *   - Email alerts  (§3.11.4)
 *   - Backups       (§3.10.8, §3.10.9)
 *   - System        (§3.12.6)
 */
const SUBSECTIONS: { key: string; title: string; description: string }[] = [
  { key: "Enrollment",   title: "Enrollment quality",   description: "Per-capture and overall quality gates for new enrollments." },
  { key: "Retention",    title: "Data retention",       description: "How long attendance logs and snapshot images are kept." },
  { key: "Storage",      title: "Storage monitoring",   description: "Free-disk threshold that triggers the storage_low alert." },
  { key: "Sync",         title: "HRMS batch sync",      description: "Bulk push of attendance records to the HRMS." },
  { key: "Email alerts", title: "Email alerts (SMTP)",  description: "Outbound email for camera-offline and storage alerts." },
  { key: "Backups",      title: "Scheduled backups",    description: "Automatic backup schedule and retention." },
  { key: "System",       title: "System logs",          description: "Retention of internal system log rows." },
];

export function System() {
  const { data, isLoading, error } = useAllSettings();
  const update = useUpdateSettings();
  const [resultsBySection, setResultsBySection] = useState<Record<string, string>>({});

  // Group system settings by their card subsection.
  const sections = useMemo(() => {
    const bySub: Record<string, SettingItem[]> = {};
    for (const sub of SUBSECTIONS) bySub[sub.key] = [];
    for (const it of data?.items ?? []) {
      if (it.group !== "system") continue;
      (bySub[it.subsection] ??= []).push(it);
    }
    return bySub;
  }, [data]);

  if (isLoading) return <Spinner className="mx-auto mt-12" />;
  if (error || !data) {
    return <ErrorBanner message={error instanceof Error ? error.message : "Could not load settings."} />;
  }

  const save = (sectionKey: string) => (items: { key: string; value: string; clear: boolean }[]) =>
    update.mutate(items, {
      onSuccess: (res) => {
        const errs = resultsToErrorMap(res.items);
        setResultsBySection((prev) => ({ ...prev, [sectionKey]: errs.__all ?? "" }));
        // The card component itself renders per-key errors; here we
        // only care about a top-level "all failed" message.
        if (res.items.every((r) => r.ok)) {
          setResultsBySection((prev) => ({ ...prev, [sectionKey]: "" }));
        }
      },
      onError: (e) =>
        setResultsBySection((prev) => ({
          ...prev,
          [sectionKey]: e instanceof Error ? e.message : "Save failed.",
        })),
    });

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {SUBSECTIONS.map((sub) => {
        const items = sections[sub.key] ?? [];
        // Hide empty cards (e.g. when META hasn't been filled in for a
        // subsection) so the page never renders an empty editor.
        if (items.length === 0) return null;
        return (
          <SettingsCard
            key={sub.key}
            title={sub.title}
            description={sub.description}
            items={items}
            saving={update.isPending}
            globalError={resultsBySection[sub.key]}
            onSave={save(sub.key)}
          />
        );
      })}

      {/* Footer hint */}
      <Card className="lg:col-span-2">
        <CardContent className="pt-6 text-sm text-muted-foreground">
          All settings are stored in the <code className="rounded bg-muted px-1.5 py-0.5">system_settings</code> table
          and applied live. Restart-dependent services (sync scheduler, backup scheduler, SMTP) pick up
          changes on their next cycle; the recognition engine refreshes within ~5&nbsp;seconds.
        </CardContent>
      </Card>
    </div>
  );
}
