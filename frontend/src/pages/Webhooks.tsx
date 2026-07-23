import { useState } from "react";
import {
  WEBHOOK_EVENT_TYPES,
  useCreateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  useUpdateWebhook,
  useWebhookDeliveries,
  useWebhooks,
  type Webhook,
  type WebhookDelivery,
} from "@/lib/queries";
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
import { formatDateTime } from "@/lib/utils";
import { Plus, Send, TestTube2, Trash2 } from "lucide-react";

export function Webhooks() {
  const { data: webhooks, isLoading, error, isFetching } = useWebhooks();
  const testMut = useTestWebhook();
  const [selected, setSelected] = useState<Webhook | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            Outbound subscriptions for {WEBHOOK_EVENT_TYPES.length} event types. Each subscription is HMAC-signed; secret never leaves the server.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isFetching && <Spinner className="h-4 w-4" />}
          <Button size="sm" onClick={() => setShowCreate(true)} className="gap-2">
            <Plus className="h-4 w-4" /> New subscription
          </Button>
        </div>
      </div>

      {error && <ErrorBanner message={error instanceof Error ? error.message : "Failed to load webhooks."} />}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-12"><Spinner className="mx-auto" /></div>
          ) : !webhooks || webhooks.length === 0 ? (
            <EmptyState title="No webhook subscriptions" hint="Create one to start receiving events at your HRMS." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Target</TH>
                  <TH>Events</TH>
                  <TH>Retries</TH>
                  <TH>Status</TH>
                  <TH>Updated</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {webhooks.map((wh) => (
                  <TR key={wh.id} className="cursor-pointer" onClick={() => setSelected(wh)}>
                    <TD className="font-medium">
                      <div className="max-w-xs truncate">{wh.target_url}</div>
                      {wh.has_secret && (
                        <span className="ml-2 text-xs text-muted-foreground">HMAC signed</span>
                      )}
                    </TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        {wh.events.map((e) => (
                          <Badge key={e} variant="outline">{e}</Badge>
                        ))}
                      </div>
                    </TD>
                    <TD>{wh.max_retries}</TD>
                    <TD>
                      <Badge variant={wh.is_enabled ? "success" : "secondary"}>
                        {wh.is_enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </TD>
                    <TD className="text-xs text-muted-foreground">{formatDateTime(wh.updated_at)}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Send test"
                          onClick={() => testMut.mutate(wh.id)}
                          disabled={testMut.isPending}
                        >
                          <Send className="h-4 w-4" />
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

      <CreateWebhookDialog open={showCreate} onClose={() => setShowCreate(false)} />
      <WebhookDetailDialog webhook={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function CreateWebhookDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateWebhook();
  const [form, setForm] = useState({
    target_url: "",
    events: [] as string[],
    secret: "",
    max_retries: 3,
    timeout_ms: 5000,
  });
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.events.length === 0) {
      setError("Select at least one event type.");
      return;
    }
    try {
      await create.mutateAsync({
        target_url: form.target_url,
        events: form.events,
        secret: form.secret || null,
        max_retries: form.max_retries,
        timeout_ms: form.timeout_ms,
      });
      onClose();
      setForm({ target_url: "", events: [], secret: "", max_retries: 3, timeout_ms: 5000 });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="New webhook subscription" description="Receive HMAC-signed event POSTs at the target URL.">
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="wh-url">Target URL *</Label>
          <Input id="wh-url" value={form.target_url} onChange={(e) => setForm({ ...form, target_url: e.target.value })} placeholder="https://hrms.example/webhooks/face" required />
        </div>
        <div className="space-y-1.5">
          <Label>Events</Label>
          <div className="flex flex-wrap gap-2">
            {WEBHOOK_EVENT_TYPES.map((evt) => (
              <label key={evt} className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
                <input
                  type="checkbox"
                  checked={form.events.includes(evt)}
                  onChange={(e) => {
                    setForm((f) => ({
                      ...f,
                      events: e.target.checked ? [...f.events, evt] : f.events.filter((x) => x !== evt),
                    }));
                  }}
                />
                <code>{evt}</code>
              </label>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wh-secret">HMAC secret (recommended)</Label>
          <Input id="wh-secret" type="password" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} placeholder="Leave blank for unsigned" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="wh-retries">Max retries</Label>
            <Input id="wh-retries" type="number" min={0} max={10} value={form.max_retries} onChange={(e) => setForm({ ...form, max_retries: parseInt(e.target.value || "0") })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wh-timeout">Timeout (ms)</Label>
            <Input id="wh-timeout" type="number" min={500} max={30000} value={form.timeout_ms} onChange={(e) => setForm({ ...form, timeout_ms: parseInt(e.target.value || "5000") })} />
          </div>
        </div>
        {error && <ErrorBanner message={error} />}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create"}</Button>
        </div>
      </form>
    </Dialog>
  );
}

function WebhookDetailDialog({ webhook, onClose }: { webhook: Webhook | null; onClose: () => void }) {
  const update = useUpdateWebhook(webhook?.id ?? "");
  const del = useDeleteWebhook();
  const testMut = useTestWebhook();
  const deliveries = useWebhookDeliveries(webhook?.id);
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const [editEvents, setEditEvents] = useState<string[]>([]);
  const [editEnabled, setEditEnabled] = useState(true);
  const [delReason, setDelReason] = useState("");

  if (webhook && editEvents.length === 0) {
    // Lazy-init form state on open.
    setEditEvents(webhook.events);
    setEditEnabled(webhook.is_enabled);
  }

  const saveEdit = async () => {
    await update.mutateAsync({
      events: editEvents,
      is_enabled: editEnabled,
    });
    setMode("view");
  };

  return (
    <Dialog open={!!webhook} onClose={onClose} title={webhook ? `Webhook · ${webhook.target_url}` : "Webhook"} className="max-w-3xl">
      {webhook && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Field label="ID" value={<code className="text-xs">{webhook.id}</code>} />
            <Field label="HMAC" value={webhook.has_secret ? "✓ signed" : "unsigned"} />
            <Field label="Retries" value={`${webhook.max_retries} (timeout ${webhook.timeout_ms} ms)`} />
            <Field label="Enabled" value={webhook.is_enabled ? "yes" : "no"} />
          </div>

          {mode === "edit" ? (
            <div className="space-y-2 rounded-md border p-3">
              <div className="space-y-1.5">
                <Label>Events</Label>
                <div className="flex flex-wrap gap-2">
                  {WEBHOOK_EVENT_TYPES.map((evt) => (
                    <label key={evt} className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
                      <input
                        type="checkbox"
                        checked={editEvents.includes(evt)}
                        onChange={(e) => {
                          setEditEvents((cur) =>
                            e.target.checked ? [...cur, evt] : cur.filter((x) => x !== evt),
                          );
                        }}
                      />
                      <code>{evt}</code>
                    </label>
                  ))}
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={editEnabled} onChange={(e) => setEditEnabled(e.target.checked)} />
                Enabled
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <Button size="sm" variant="outline" onClick={() => setMode("view")}>Cancel</Button>
                <Button size="sm" onClick={saveEdit} disabled={update.isPending}>Save</Button>
              </div>
            </div>
          ) : mode === "delete" ? (
            <div className="space-y-2 rounded-md border p-3">
              <Label>Reason (required for audit)</Label>
              <Input value={delReason} onChange={(e) => setDelReason(e.target.value)} placeholder="Why is this being deleted?" />
              <div className="flex justify-end gap-2 pt-2">
                <Button size="sm" variant="outline" onClick={() => setMode("view")}>Cancel</Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={!delReason.trim() || del.isPending}
                  onClick={async () => {
                    await del.mutateAsync(webhook.id);
                    onClose();
                  }}
                >
                  Delete permanently
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => testMut.mutate(webhook.id)} disabled={testMut.isPending} className="gap-2">
                <TestTube2 className="h-4 w-4" /> Test delivery
              </Button>
              <Button size="sm" variant="outline" onClick={() => setMode("edit")}>Edit events</Button>
              <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setMode("delete")}>
                <Trash2 className="mr-1 h-4 w-4" /> Delete
              </Button>
            </div>
          )}

          {testMut.isError && <ErrorBanner message={testMut.error instanceof Error ? testMut.error.message : "Test failed."} />}
          {testMut.data && (
            <div className="rounded-md border p-3 text-sm">
              Test delivery → <strong>{testMut.data.ok ? "OK" : "FAILED"}</strong>
              {testMut.data.status_code && ` (HTTP ${testMut.data.status_code})`}
              {testMut.data.latency_ms != null && ` · ${testMut.data.latency_ms} ms`}
              {testMut.data.error && <div className="mt-1 text-xs text-destructive">{testMut.data.error}</div>}
            </div>
          )}

          <div>
            <h3 className="mb-2 text-sm font-semibold">Recent deliveries</h3>
            <DeliveryList deliveries={deliveries.data?.items ?? []} loading={deliveries.isLoading} />
          </div>
        </div>
      )}
    </Dialog>
  );
}

function DeliveryList({ deliveries, loading }: { deliveries: WebhookDelivery[]; loading: boolean }) {
  if (loading) return <Spinner className="h-4 w-4" />;
  if (deliveries.length === 0)
    return <p className="text-xs text-muted-foreground">No delivery attempts yet.</p>;
  return (
    <Table>
      <THead>
        <TR>
          <TH>When</TH>
          <TH>Event</TH>
          <TH>Attempt</TH>
          <TH>Status</TH>
          <TH>Latency</TH>
          <TH>Outcome</TH>
        </TR>
      </THead>
      <TBody>
        {deliveries.map((d) => (
          <TR key={d.id}>
            <TD className="text-xs">{formatDateTime(d.created_at)}</TD>
            <TD><code className="text-xs">{d.event_type}</code></TD>
            <TD>{d.attempt}</TD>
            <TD>{d.status_code ?? <span className="text-muted-foreground">—</span>}</TD>
            <TD>{d.latency_ms != null ? `${d.latency_ms} ms` : "—"}</TD>
            <TD>
              <span className={`text-xs ${d.outcome === "ok" ? "text-emerald-600" : d.outcome === "failed" ? "text-destructive" : "text-amber-600"}`}>
                {d.outcome}
              </span>
              {d.error && <div className="text-xs text-muted-foreground">{d.error}</div>}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}