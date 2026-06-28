import { useState } from "react";
import {
  useResendBatch,
  useRunBatch,
  useSyncConfig,
  useSyncStatus,
  useUpdateSyncConfig,
  type BatchResult,
  type SyncConfig,
} from "@/lib/queries";
import {
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
} from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, RefreshCw, Send, XCircle } from "lucide-react";

export function Sync() {
  const qc = useQueryClient();
  const { data: status, isLoading, error } = useSyncStatus();
  const { data: config } = useSyncConfig();
  const updateConfig = useUpdateSyncConfig();
  const runBatch = useRunBatch();
  const resend = useResendBatch();
  const [result, setResult] = useState<{ title: string; data: BatchResult } | null>(null);

  const onRunBatch = async () => {
    try {
      const r = await runBatch.mutateAsync({});
      setResult({ title: "Batch send", data: r });
      qc.invalidateQueries({ queryKey: ["sync"] });
    } catch { /* surfaced via mutation */ }
  };
  const onResend = async () => {
    try {
      const r = await resend.mutateAsync({});
      setResult({ title: "Resend", data: r });
      qc.invalidateQueries({ queryKey: ["sync"] });
    } catch { /* surfaced via mutation */ }
  };

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error instanceof Error ? error.message : "Failed to load sync status."} />}

      {/* Status */}
      <Card>
        <CardHeader>
          <CardTitle>Sync status</CardTitle>
          <CardDescription>Attendance log records and their delivery state to the HRMS.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading || !status ? (
            <Spinner className="h-4 w-4" />
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Counter icon={<Clock className="h-4 w-4 text-amber-600" />} label="Pending" value={status.pending} variant="warning" />
              <Counter icon={<CheckCircle2 className="h-4 w-4 text-emerald-600" />} label="Sent" value={status.sent} variant="success" />
              <Counter icon={<XCircle className="h-4 w-4 text-destructive" />} label="Failed" value={status.failed} variant="destructive" />
              <Counter icon={<Clock className="h-4 w-4 text-muted-foreground" />} label="Manual" value={status.manual} variant="secondary" />
              <Counter icon={<RefreshCw className="h-4 w-4 text-muted-foreground" />} label="Total" value={status.total} />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Manual sync actions</CardTitle>
          <CardDescription>Run a one-off batch send or re-send already-sent records (§3.7.3 / §3.7.9).</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {!config?.batch_url && (
            <ErrorBanner message="No batch URL configured. Set one in the schedule config below first." />
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={onRunBatch}
              disabled={runBatch.isPending || !config?.batch_url}
              className="gap-2"
            >
              <Send className="h-4 w-4" /> {runBatch.isPending ? "Sending…" : "Send pending batch"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={onResend}
              disabled={resend.isPending || !config?.batch_url}
              className="gap-2"
            >
              <RefreshCw className="h-4 w-4" /> {resend.isPending ? "Resending…" : "Re-send already-sent"}
            </Button>
          </div>
          {result && (
            <div className="rounded-md border p-3 text-sm">
              <strong>{result.title}:</strong> attempted {result.data.attempted}, delivered {result.data.delivered}, failed {result.data.failed} ({result.data.batches} batch{result.data.batches !== 1 ? "es" : ""})
              {result.data.error && <div className="mt-1 text-xs text-destructive">{result.data.error}</div>}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Schedule config */}
      {config && (
        <ScheduleCard
          config={config}
          onSave={async (next) => {
            await updateConfig.mutateAsync(next);
          }}
          saving={updateConfig.isPending}
        />
      )}

      <ResultDialog data={result} onClose={() => setResult(null)} />
    </div>
  );
}

function Counter({ icon, label, value, variant }: { icon: React.ReactNode; label: string; value: number; variant?: "default" | "secondary" | "destructive" | "warning" | "success" }) {
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-muted-foreground">
        {icon} {label}
      </div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

function ScheduleCard({ config, onSave, saving }: { config: SyncConfig; onSave: (c: SyncConfig) => Promise<void>; saving: boolean }) {
  const [draft, setDraft] = useState<SyncConfig>(config);
  const [dirty, setDirty] = useState(false);

  // Reset when the loaded config changes (e.g. after refetch).
  useState(() => setDraft(config));

  const update = <K extends keyof SyncConfig>(key: K, value: SyncConfig[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setDirty(true);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Auto-sync schedule (§3.7.10)</CardTitle>
        <CardDescription>Periodically flush pending + failed records to the HRMS batch URL.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="batch-url">Batch URL</Label>
          <Input
            id="batch-url"
            value={draft.batch_url}
            onChange={(e) => update("batch_url", e.target.value)}
            placeholder="https://hrms.example/api/attendance/batch"
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <Label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={draft.auto_enabled}
                onChange={(e) => update("auto_enabled", e.target.checked)}
              />
              Auto-sync enabled
            </Label>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="auto-interval">Interval (seconds)</Label>
            <Input
              id="auto-interval"
              type="number"
              min={30}
              value={draft.auto_interval_seconds}
              onChange={(e) => update("auto_interval_seconds", parseInt(e.target.value || "300"))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batch-size">Batch size</Label>
            <Input
              id="batch-size"
              type="number"
              min={1}
              value={draft.batch_size}
              onChange={(e) => update("batch_size", parseInt(e.target.value || "100"))}
            />
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

function ResultDialog({ data, onClose }: { data: { title: string; data: BatchResult } | null; onClose: () => void }) {
  return (
    <Dialog open={!!data} onClose={onClose} title={data?.title || ""}>
      {data && (
        <pre className="overflow-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(data.data, null, 2)}
        </pre>
      )}
    </Dialog>
  );
}