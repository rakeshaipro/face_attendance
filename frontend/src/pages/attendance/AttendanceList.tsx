import { useState } from "react";
import { useAttendance, useDeleteLog, useEditLog, useManualEntry, type AttendanceListParams } from "@/lib/queries";
import type { AttendanceLog } from "@/lib/types";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  CardContent,
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
import { EmptyState, ErrorBanner, SyncStatusBadge } from "@/components/shared";
import { formatConfidence, formatDateTime } from "@/lib/utils";
import { Plus, Search } from "lucide-react";

export function AttendanceList() {
  const [params, setParams] = useState<AttendanceListParams>({ page: 1, limit: 25 });
  const [q, setQ] = useState("");
  const [date, setDate] = useState("");
  const { data, isLoading, error, isFetching } = useAttendance(params);
  const manual = useManualEntry();

  const [showManual, setShowManual] = useState(false);
  const [detail, setDetail] = useState<AttendanceLog | null>(null);

  const runSearch = () => setParams((p) => ({ ...p, employee_id: q || undefined, date: date || undefined, page: 1 }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative max-w-xs flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Employee ID or name…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" onKeyDown={(e) => e.key === "Enter" && runSearch()} />
        </div>
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-40" />
        <Button variant="outline" size="sm" onClick={runSearch}>Filter</Button>
        {isFetching && <Spinner className="h-4 w-4" />}
        <div className="flex-1" />
        <Button size="sm" onClick={() => setShowManual(true)} className="gap-2">
          <Plus className="h-4 w-4" /> Manual entry
        </Button>
      </div>

      {error && <ErrorBanner message={error instanceof Error ? error.message : "Failed to load logs."} />}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-12"><Spinner className="mx-auto" /></div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState title="No attendance records" hint="Adjust filters or wait for detections." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Timestamp</TH>
                  <TH>Employee</TH>
                  <TH>Confidence</TH>
                  <TH>Type</TH>
                  <TH>Sync</TH>
                  <TH>Snapshot</TH>
                </TR>
              </THead>
              <TBody>
                {data.items.map((log) => (
                  <TR key={log.id} className="cursor-pointer" onClick={() => setDetail(log)}>
                    <TD className="font-medium">{formatDateTime(log.timestamp)}</TD>
                    <TD>
                      <div>{log.employee_name}</div>
                      <div className="text-xs text-muted-foreground">{log.location_name}</div>
                    </TD>
                    <TD>{log.is_manual ? "—" : formatConfidence(log.confidence)}</TD>
                    <TD>{log.is_manual ? <Badge variant="secondary">Manual</Badge> : <Badge variant="outline">Detection</Badge>}</TD>
                    <TD><SyncStatusBadge status={log.sync_status} /></TD>
                    <TD>
                      {log.snapshot_available ? (
                        <SnapshotThumb logId={log.id} />
                      ) : (
                        <span className="text-xs text-muted-foreground">purged</span>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {data && data.total > data.limit && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>Page {data.page} of {Math.ceil(data.total / data.limit)} · {data.total} records</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={data.page <= 1} onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) - 1 }))}>Previous</Button>
            <Button size="sm" variant="outline" disabled={data.page * data.limit >= data.total} onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) + 1 }))}>Next</Button>
          </div>
        </div>
      )}

      <ManualEntryDialog open={showManual} onClose={() => setShowManual(false)} onSubmit={async (body) => { await manual.mutateAsync(body); setShowManual(false); }} />
      <LogDetailDialog log={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

function SnapshotThumb({ logId }: { logId: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  useState(() => {
    api.download(`/api/v1/attendance/${logId}/snapshot`).then((b) => setSrc(URL.createObjectURL(b))).catch(() => setErr(true));
  });
  if (err) return <span className="text-xs text-muted-foreground">—</span>;
  if (!src) return <Spinner className="h-4 w-4" />;
  return <img src={src} alt="snapshot" className="h-12 w-16 rounded object-cover" />;
}

function ManualEntryDialog({ open, onClose, onSubmit }: { open: boolean; onClose: () => void; onSubmit: (body: { employee_id: string; timestamp: string; reason: string; note?: string }) => Promise<void> }) {
  const [form, setForm] = useState({ employee_id: "", timestamp: new Date().toISOString().slice(0, 16), reason: "", note: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await onSubmit({ employee_id: form.employee_id, timestamp: new Date(form.timestamp).toISOString(), reason: form.reason, note: form.note || undefined });
      setForm({ employee_id: "", timestamp: new Date().toISOString().slice(0, 16), reason: "", note: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Manual entry failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Manual attendance entry" description="Creates a record flagged as manual (no webhook).">
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="m-eid">Employee ID *</Label>
          <Input id="m-eid" value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })} required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="m-ts">Timestamp *</Label>
          <Input id="m-ts" type="datetime-local" value={form.timestamp} onChange={(e) => setForm({ ...form, timestamp: e.target.value })} required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="m-reason">Reason *</Label>
          <Input id="m-reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="m-note">Note</Label>
          <Input id="m-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </div>
        {error && <ErrorBanner message={error} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        </div>
      </form>
    </Dialog>
  );
}

function LogDetailDialog({ log, onClose }: { log: AttendanceLog | null; onClose: () => void }) {
  const edit = useEditLog(log?.id ?? "");
  const del = useDeleteLog();
  const [editTs, setEditTs] = useState("");
  const [delReason, setDelReason] = useState("");
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");

  useState(() => {
    if (log) {
      setEditTs(log.timestamp.slice(0, 16));
      setDelReason("");
      setMode("view");
    }
  });

  return (
    <Dialog open={!!log} onClose={onClose} title="Attendance record" className="max-w-xl">
      {log && (
        <div className="space-y-4">
          {log.snapshot_available && <SnapshotFull logId={log.id} />}
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Field label="Employee" value={log.employee_name} />
            <Field label="Location" value={log.location_name} />
            <Field label="Timestamp" value={formatDateTime(log.timestamp)} />
            <Field label="Confidence" value={log.is_manual ? "—" : formatConfidence(log.confidence)} />
            <Field label="Type" value={log.is_manual ? "Manual" : "Detection"} />
            <Field label="Sync" value={<SyncStatusBadge status={log.sync_status} />} />
            {log.manual_reason && <Field label="Reason" value={log.manual_reason} />}
            <Field label="Machine ID" value={log.machine_id} />
          </div>

          {mode === "edit" ? (
            <div className="space-y-2 rounded-md border p-3">
              <Label>New timestamp</Label>
              <Input type="datetime-local" value={editTs} onChange={(e) => setEditTs(e.target.value)} />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" onClick={() => setMode("view")}>Cancel</Button>
                <Button
                  size="sm"
                  onClick={async () => {
                    await edit.mutateAsync({ timestamp: new Date(editTs).toISOString() });
                    setMode("view");
                    onClose();
                  }}
                >
                  Save
                </Button>
              </div>
            </div>
          ) : mode === "delete" ? (
            <div className="space-y-2 rounded-md border p-3">
              <Label>Reason (required)</Label>
              <Input value={delReason} onChange={(e) => setDelReason(e.target.value)} placeholder="Why is this being deleted?" />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" onClick={() => setMode("view")}>Cancel</Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={!delReason.trim()}
                  onClick={async () => {
                    await del.mutateAsync({ id: log.id, reason: delReason });
                    onClose();
                  }}
                >
                  Delete
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setMode("edit")}>Edit timestamp</Button>
              <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setMode("delete")}>Delete</Button>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}

function SnapshotFull({ logId }: { logId: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useState(() => {
    api.download(`/api/v1/attendance/${logId}/snapshot`).then((b) => setSrc(URL.createObjectURL(b)));
  });
  if (!src) return <Spinner className="mx-auto" />;
  return <img src={src} alt="snapshot" className="mx-auto max-h-72 rounded-md object-contain" />;
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}
