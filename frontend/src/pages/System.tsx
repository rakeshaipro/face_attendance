import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import {
  useAllSettings,
  useBackups,
  useBackupSchedule,
  useCreateBackup,
  useDeleteBackup,
  useMonitoringStatus,
  useNtpSync,
  useRestoreBackup,
  useSystemLogs,
  useTime,
  useUpdateBackupSchedule,
  useUpdateSettings,
  useUpdateTime,
} from "@/lib/queries";
import type { BackupScheduleConfig, LogSeverity, NtpResult, SettingItem } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  Input,
  Label,
  Spinner,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import { EmptyState, ErrorBanner } from "@/components/shared";
import { SettingsCard } from "@/components/SettingsField";
import { resultsToErrorMap } from "@/components/settingsUtils";
import { formatBytes, formatDateTime, formatRelative } from "@/lib/utils";
import { Download, Trash2, Upload } from "lucide-react";

export function System() {
  const [tab, setTab] = useState<"backups" | "logs" | "monitoring" | "settings" | "time">("backups");
  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b">
        <TabBtn active={tab === "backups"} onClick={() => setTab("backups")}>Backups</TabBtn>
        <TabBtn active={tab === "logs"} onClick={() => setTab("logs")}>System logs</TabBtn>
        <TabBtn active={tab === "monitoring"} onClick={() => setTab("monitoring")}>Monitoring</TabBtn>
        <TabBtn active={tab === "settings"} onClick={() => setTab("settings")}>Settings</TabBtn>
        <TabBtn active={tab === "time"} onClick={() => setTab("time")}>Time</TabBtn>
      </div>
      {tab === "backups" && <BackupsTab />}
      {tab === "logs" && <SystemLogsTab />}
      {tab === "monitoring" && <MonitoringTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "time" && <TimeTab />}
    </div>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
        active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

// --- Backups tab --------------------------------------------------------
function BackupsTab() {
  const backups = useBackups();
  const schedule = useBackupSchedule();
  const updateSchedule = useUpdateBackupSchedule();
  const createMut = useCreateBackup();
  const deleteMut = useDeleteBackup();
  const restoreMut = useRestoreBackup();

  const fileRef = useRef<HTMLInputElement>(null);
  const [restoreTarget, setRestoreTarget] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onDownload = async (id: string) => {
    try {
      const blob = await api.download(`/api/v1/backup/${id}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    }
  };

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}

      {/* Create + restore */}
      <Card>
        <CardHeader>
          <CardTitle>Backup & restore</CardTitle>
          <CardDescription>Full backups include the database + snapshots + enrollment images.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => createMut.mutate("database")} disabled={createMut.isPending}>
            {createMut.isPending ? "Creating…" : "Create database backup"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => createMut.mutate("full")} disabled={createMut.isPending}>
            Create full backup
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) setRestoreTarget(f);
              e.target.value = "";
            }}
          />
          <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()} className="gap-2">
            <Upload className="h-4 w-4" /> Upload to restore…
          </Button>
        </CardContent>
      </Card>

      {/* Schedule */}
      {schedule.data && (
        <ScheduleCard
          config={schedule.data}
          saving={updateSchedule.isPending}
          onSave={async (cfg) => {
            await updateSchedule.mutateAsync(cfg);
          }}
        />
      )}

      {/* History */}
      <Card>
        <CardContent className="p-0">
          {backups.isLoading ? (
            <div className="p-12"><Spinner className="mx-auto" /></div>
          ) : !backups.data || backups.data.length === 0 ? (
            <EmptyState title="No backups yet" hint="Create one above to get started." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Created</TH>
                  <TH>Kind</TH>
                  <TH>Origin</TH>
                  <TH>Size</TH>
                  <TH>Note</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {backups.data.map((b) => (
                  <TR key={b.id}>
                    <TD>
                      <div>{formatDateTime(b.created_at)}</div>
                      <div className="text-xs text-muted-foreground">{formatRelative(b.created_at)}</div>
                    </TD>
                    <TD><Badge variant={b.kind === "full" ? "default" : "outline"}>{b.kind}</Badge></TD>
                    <TD><Badge variant="secondary">{b.origin}</Badge></TD>
                    <TD>{formatBytes(b.size_bytes)}</TD>
                    <TD className="text-xs text-muted-foreground">{b.note || "—"}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="icon" title="Download" onClick={() => onDownload(b.id)}>
                          <Download className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Delete"
                          onClick={() => {
                            if (confirm(`Delete backup ${b.filename}? This cannot be undone.`)) {
                              deleteMut.mutate(b.id);
                            }
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={!!restoreTarget}
        onClose={() => setRestoreTarget(null)}
        title="Restore from backup ZIP"
        description="This will overwrite the current database. The engine will be restarted."
      >
        {restoreTarget && (
          <div className="space-y-3">
            <p className="text-sm">
              File: <code className="rounded bg-muted px-1.5 py-0.5">{restoreTarget.name}</code>
              <span className="ml-2 text-xs text-muted-foreground">({formatBytes(restoreTarget.size)})</span>
            </p>
            {restoreMut.isError && (
              <ErrorBanner message={restoreMut.error instanceof Error ? restoreMut.error.message : "Restore failed."} />
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setRestoreTarget(null)}>Cancel</Button>
              <Button
                variant="destructive"
                disabled={restoreMut.isPending}
                onClick={async () => {
                  try {
                    await restoreMut.mutateAsync(restoreTarget);
                    setRestoreTarget(null);
                  } catch { /* surfaced */ }
                }}
              >
                {restoreMut.isPending ? "Restoring…" : "Overwrite and restore"}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}

function ScheduleCard({ config, onSave, saving }: { config: BackupScheduleConfig; onSave: (c: BackupScheduleConfig) => Promise<void>; saving: boolean }) {
  const [draft, setDraft] = useState<BackupScheduleConfig>(config);
  const [dirty, setDirty] = useState(false);
  useState(() => setDraft(config));

  const update = <K extends keyof BackupScheduleConfig>(key: K, value: BackupScheduleConfig[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setDirty(true);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Scheduled backups (§3.10.8)</CardTitle>
        <CardDescription>Auto-sync APScheduler; max-scheduled enforced on every run (§3.10.9).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={draft.enabled} onChange={(e) => update("enabled", e.target.checked)} />
          Enable scheduled backups
        </label>
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="sched-freq">Frequency</Label>
            <select
              id="sched-freq"
              value={draft.frequency}
              onChange={(e) => update("frequency", e.target.value as "daily" | "weekly")}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly (Monday)</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sched-time">Time (HH:MM)</Label>
            <Input id="sched-time" value={draft.time} onChange={(e) => update("time", e.target.value)} placeholder="02:00" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sched-max">Max scheduled to keep</Label>
            <Input id="sched-max" type="number" min={1} max={365} value={draft.max_scheduled} onChange={(e) => update("max_scheduled", parseInt(e.target.value || "14"))} />
          </div>
        </div>
        <div className="flex justify-end">
          <Button size="sm" disabled={!dirty || saving} onClick={() => onSave(draft).then(() => setDirty(false))}>
            {saving ? "Saving…" : "Save schedule"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// --- System logs tab ---------------------------------------------------
function SystemLogsTab() {
  const [severity, setSeverity] = useState<LogSeverity | "">("");
  const [event, setEvent] = useState("");
  const [page, setPage] = useState(1);
  const limit = 25;

  const params = {
    page,
    limit,
    severity: severity || undefined,
    event: event || undefined,
  };
  const logs = useSystemLogs(params);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={severity}
          onChange={(e) => {
            setSeverity(e.target.value as LogSeverity | "");
            setPage(1);
          }}
          className="h-10 rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="">Any severity</option>
          <option value="debug">Debug</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
        </select>
        <Input
          placeholder="Event (e.g. engine.start)"
          value={event}
          onChange={(e) => {
            setEvent(e.target.value);
            setPage(1);
          }}
          className="max-w-xs"
        />
      </div>

      {logs.error && <ErrorBanner message={logs.error instanceof Error ? logs.error.message : "Failed to load logs."} />}

      <Card>
        <CardContent className="p-0">
          {logs.isLoading ? (
            <div className="p-12"><Spinner className="mx-auto" /></div>
          ) : !logs.data || logs.data.items.length === 0 ? (
            <EmptyState title="No system logs" hint="Filter by severity or event to broaden." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Severity</TH>
                  <TH>Event</TH>
                  <TH>Message</TH>
                </TR>
              </THead>
              <TBody>
                {logs.data.items.map((l) => (
                  <TR key={l.id}>
                    <TD className="text-xs">{formatDateTime(l.created_at)}</TD>
                    <TD>
                      <Badge variant={l.severity === "error" || l.severity === "critical" ? "destructive" : l.severity === "warning" ? "warning" : "secondary"}>
                        {l.severity}
                      </Badge>
                    </TD>
                    <TD><code className="text-xs">{l.event}</code></TD>
                    <TD className="max-w-lg text-sm">
                      <div>{l.message}</div>
                      {l.context_json && (
                        <code className="mt-1 block max-h-12 overflow-auto rounded bg-muted px-1.5 py-0.5 text-xs">
                          {l.context_json}
                        </code>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {logs.data && logs.data.total > limit && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>Page {logs.data.page} of {Math.ceil(logs.data.total / limit)} · {logs.data.total} records</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
            <Button size="sm" variant="outline" disabled={page * limit >= logs.data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      )}
    </div>
  );
}

// --- Settings tab (§6.4) -----------------------------------------------
// Renders every `group === "system"` setting, grouped by subsection into
// the same SettingsCard used on the Device page. Per-key validation and
// type-aware inputs come from the shared component.
function SettingsTab() {
  const { data: settings, isLoading, error } = useAllSettings();
  const update = useUpdateSettings();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [globalError, setGlobalError] = useState<string | null>(null);

  // Group the system settings by subsection, preserving the order returned
  // by the backend (matches engine.defaults.META ordering).
  const groups = useMemo(() => {
    const map: Record<string, SettingItem[]> = {};
    for (const it of settings?.items ?? []) {
      if (it.group !== "system") continue;
      const key = it.subsection || "Other";
      if (!map[key]) map[key] = [];
      map[key].push(it);
    }
    return map;
  }, [settings]);

  const save = (items: { key: string; value: string; clear: boolean }[]) => {
    setGlobalError(null);
    setErrors({});
    update.mutate(items, {
      onSuccess: (res) => {
        setErrors(resultsToErrorMap(res.items));
        if (res.items.every((r) => r.ok)) setErrors({});
      },
      onError: (e) => {
        setGlobalError(e instanceof Error ? e.message : "Save failed.");
      },
    });
  };

  if (isLoading) return <Spinner className="mx-auto mt-12" />;
  if (error) {
    return <ErrorBanner message={error instanceof Error ? error.message : "Could not load settings."} />;
  }

  const order = Object.keys(groups);
  if (order.length === 0) {
    return (
      <EmptyState title="No system settings" hint="The settings store returned no system-grouped keys." />
    );
  }

  return (
    <div className="space-y-4">
      {globalError && <ErrorBanner message={globalError} />}
      <p className="text-sm text-muted-foreground">
        Retention, storage, sync, SMTP, and system-log retention. Changes are saved individually
        and reported per-row.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {order.map((subsection) => (
          <SettingsCard
            key={subsection}
            title={subsection}
            items={groups[subsection]}
            saving={update.isPending}
            globalError={globalError ?? undefined}
            onSave={save}
          />
        ))}
      </div>
      {Object.values(errors).some(Boolean) && (
        <p className="text-xs text-muted-foreground">
          Some rows reported errors — see the red hint below the affected field.
        </p>
      )}
    </div>
  );
}

// --- Monitoring tab (Phase 8) -------------------------------------------
function MonitoringTab() {
  const status = useMonitoringStatus();

  return (
    <div className="space-y-4">
      {status.error && <ErrorBanner message={status.error instanceof Error ? status.error.message : "Failed to load monitoring status."} />}

      <Card>
        <CardHeader>
          <CardTitle>Scheduled jobs</CardTitle>
          <CardDescription>APScheduler job status for monitoring and retention.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {status.isLoading || !status.data ? (
            <Spinner className="h-4 w-4" />
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              <JobCard title="Disk-space monitor" next={status.data.disk_job_next} interval="Every 5 minutes" />
              <JobCard title="Retention purge" next={status.data.retention_job_next} interval="Daily at 04:00" />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>What is monitored</CardTitle>
          <CardDescription>Operational background tasks scheduled by the backend.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
            <li>Free disk space checked every 5 min; fires <code className="rounded bg-muted px-1">device.storage_low</code> when below threshold.</li>
            <li>Attendance logs, snapshots, and system logs purged daily according to retention settings.</li>
            <li>Camera offline and storage-low email alerts sent via SMTP when configured.</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function JobCard({ title, next, interval }: { title: string; next: string | null; interval: string }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-sm font-medium">{title}</div>
      <div className="text-xs text-muted-foreground">{interval}</div>
      <div className="mt-1 text-xs">
        Next run:{" "}
        <span className="font-mono text-muted-foreground">{next ? formatDateTime(next) : "—"}</span>
      </div>
    </div>
  );
}

// --- Time tab (§3.1.10, §3.1.11) ----------------------------------------
// Backend is the time source. We poll /time every 60s (via useTime) to
// capture server_now_utc + compute a skew; locally tick the displayed
// clock every 1s with Date.now() + skew, formatted in the configured tz.
const COMMON_TIMEZONES: string[] = [
  "UTC", "Africa/Cairo", "Africa/Johannesburg", "America/Anchorage",
  "America/Argentina/Buenos_Aires", "America/Chicago", "America/Denver",
  "America/Los_Angeles", "America/New_York", "America/Sao_Paulo",
  "America/Toronto", "Asia/Bangkok", "Asia/Dubai", "Asia/Hong_Kong",
  "Asia/Kolkata", "Asia/Seoul", "Asia/Shanghai", "Asia/Singapore",
  "Asia/Tokyo", "Australia/Sydney", "Canada/Atlantic", "Europe/Amsterdam",
  "Europe/Berlin", "Europe/London", "Europe/Madrid", "Europe/Moscow",
  "Europe/Paris", "Pacific/Auckland", "Pacific/Honolulu", "US/Eastern",
];

function tzFormatter(tz: string): Intl.DateTimeFormat {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "UTC",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  }
}

function dateFormatter(tz: string): Intl.DateTimeFormat {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      weekday: "long", year: "numeric", month: "long", day: "numeric",
    });
  } catch {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "UTC",
      weekday: "long", year: "numeric", month: "long", day: "numeric",
    });
  }
}

function TimeTab() {
  const timeQ = useTime();
  const updateTime = useUpdateTime();
  const ntpSync = useNtpSync();

  const [nowMs, setNowMs] = useState<number>(Date.now());
  const skewRef = useRef<number>(0);
  const [skewSec, setSkewSec] = useState<number>(0);

  const [draftTz, setDraftTz] = useState<string>("");
  const [draftNtp, setDraftNtp] = useState<string>("");
  const [dirty, setDirty] = useState<boolean>(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<NtpResult | null>(null);

  const data = timeQ.data;

  // Recompute skew whenever a fresh server_now_utc arrives, and sync the
  // draft editor with the latest server-side values.
  useEffect(() => {
    if (!data) return;
    const serverMs = Date.parse(data.server_now_utc);
    if (!Number.isNaN(serverMs)) {
      const skew = serverMs - Date.now();
      skewRef.current = skew;
      setSkewSec(skew / 1000);
    }
    setDraftTz(data.timezone);
    setDraftNtp(data.ntp_server);
    setDirty(false);
  }, [data?.server_now_utc, data?.timezone, data?.ntp_server]); // eslint-disable-line react-hooks/exhaustive-deps

  // Local 1s tick using the captured skew.
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const onField = <T extends "tz" | "ntp">(which: T, v: string) => {
    if (which === "tz") setDraftTz(v);
    else setDraftNtp(v);
    setDirty(true);
  };

  const onSave = async () => {
    setSaveError(null);
    try {
      await updateTime.mutateAsync({ timezone: draftTz.trim(), ntp_server: draftNtp.trim() });
      setDirty(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save time settings.");
    }
  };

  const onSync = async () => {
    setLastSync(null);
    try {
      const res = await ntpSync.mutateAsync();
      setLastSync(res);
    } catch {
      // surfaced via ntpSync.error below
    }
  };

  if (timeQ.isLoading) {
    return <div className="p-12"><Spinner className="mx-auto" /></div>;
  }
  if (timeQ.error && !data) {
    return <ErrorBanner message={timeQ.error instanceof Error ? timeQ.error.message : "Failed to load time settings."} />;
  }

  const tz = data?.timezone ?? "UTC";
  const clockStr = tzFormatter(tz).format(nowMs + skewRef.current);
  const dateStr = dateFormatter(tz).format(nowMs + skewRef.current);
  const absSkew = Math.abs(skewSec);
  const driftStr = absSkew < 0.1
    ? "Server clock matches your browser"
    : `Server is ${absSkew.toFixed(1)}s ${skewSec >= 0 ? "ahead of" : "behind"} your clock`;
  const offsetMs = lastSync ? Math.round(lastSync.offset_seconds * 1000) : 0;
  const offsetStr = `${offsetMs >= 0 ? "+" : ""}${offsetMs} ms`;
  const ntpError = ntpSync.isError
    ? (ntpSync.error instanceof Error ? ntpSync.error.message : "NTP sync failed.")
    : null;

  return (
    <div className="space-y-4">
      {/* Live clock */}
      <Card>
        <CardHeader>
          <CardTitle>Server time</CardTitle>
          <CardDescription>
            Live clock in the configured timezone ({tz}). Polled every 60s; ticks locally between polls.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          <div className="font-mono text-5xl tabular-nums tracking-tight">{clockStr}</div>
          <div className="text-sm text-muted-foreground">{dateStr}</div>
          <div className="text-xs text-muted-foreground">{driftStr}</div>
        </CardContent>
      </Card>

      {/* Timezone + NTP editor */}
      <Card>
        <CardHeader>
          <CardTitle>Timezone &amp; NTP server</CardTitle>
          <CardDescription>Used for output-stamping and clock sync probing. Stored timestamps remain UTC.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <datalist id="tz-list">
            {COMMON_TIMEZONES.map((z) => <option key={z} value={z} />)}
          </datalist>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="tz-input">Timezone (IANA)</Label>
              <Input
                id="tz-input"
                list="tz-list"
                autoComplete="off"
                value={draftTz}
                onChange={(e) => onField("tz", e.target.value)}
                placeholder="Asia/Kolkata"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ntp-input">NTP server</Label>
              <Input
                id="ntp-input"
                autoComplete="off"
                value={draftNtp}
                onChange={(e) => onField("ntp", e.target.value)}
                placeholder="pool.ntp.org"
              />
            </div>
          </div>
          {saveError && <ErrorBanner message={saveError} />}
          <div className="flex justify-end">
            <Button size="sm" disabled={!dirty || updateTime.isPending} onClick={onSave}>
              {updateTime.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* NTP sync */}
      <Card>
        <CardHeader>
          <CardTitle>NTP synchronisation</CardTitle>
          <CardDescription>
            Probes the configured server once and reports the measured offset. Does not set the OS clock.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={onSync} disabled={ntpSync.isPending}>
              {ntpSync.isPending ? "Syncing…" : "Sync now"}
            </Button>
            {data && <span className="text-xs text-muted-foreground">Server: {data.ntp_server}</span>}
          </div>

          {ntpError && <ErrorBanner message={ntpError} />}

          {lastSync && (
            <div className="grid grid-cols-3 gap-3 rounded-md border border-input bg-muted/30 p-3 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Offset</div>
                <div className="font-mono tabular-nums">{offsetStr}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Round-trip</div>
                <div className="font-mono tabular-nums">{lastSync.rtt_ms.toFixed(1)} ms</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Status</div>
                <Badge variant={lastSync.synchronized ? "default" : "destructive"}>
                  {lastSync.synchronized ? "✓ Synchronized" : "✗ Failed"}
                </Badge>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
