import { useState } from "react";
import { useAuditLog, useReportLogs, type AuditParams, type ReportLogParams } from "@/lib/queries";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Input,
  Spinner,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui";
import { EmptyState, ErrorBanner, SyncStatusBadge } from "@/components/shared";
import { formatDateTime } from "@/lib/utils";
import { Download, FileSpreadsheet, FileText, Search } from "lucide-react";

type Tab = "logs" | "audit";

export function Reports() {
  const [tab, setTab] = useState<Tab>("logs");
  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b">
        <TabButton active={tab === "logs"} onClick={() => setTab("logs")}>
          Attendance logs
        </TabButton>
        <TabButton active={tab === "audit"} onClick={() => setTab("audit")}>
          Audit log
        </TabButton>
      </div>
      {tab === "logs" ? <LogsTab /> : <AuditTab />}
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
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

// --- Logs tab -----------------------------------------------------------
function LogsTab() {
  const [params, setParams] = useState<ReportLogParams>({ page: 1, limit: 25 });
  const [q, setQ] = useState("");
  const [date, setDate] = useState("");
  const { data, isLoading, error, isFetching } = useReportLogs(params);

  const runSearch = () => setParams((p) => ({ ...p, employee_id: q || undefined, date: date || undefined, page: 1 }));

  const exportFile = async (format: "csv" | "xlsx") => {
    const qs = new URLSearchParams();
    if (params.employee_id) qs.set("employee_id", params.employee_id);
    if (params.date) qs.set("date", params.date);
    qs.set("format", format);
    const blob = await api.download(`/api/v1/reports/logs/export?${qs.toString()}`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `attendance_logs.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative max-w-xs flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Employee ID or name…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            className="pl-9"
          />
        </div>
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-40" />
        <Button variant="outline" size="sm" onClick={runSearch}>
          Filter
        </Button>
        {isFetching && <Spinner className="h-4 w-4" />}
        <div className="flex-1" />
        <Button variant="outline" size="sm" onClick={() => exportFile("csv")} className="gap-2">
          <FileText className="h-4 w-4" /> CSV
        </Button>
        <Button variant="outline" size="sm" onClick={() => exportFile("xlsx")} className="gap-2">
          <FileSpreadsheet className="h-4 w-4" /> XLSX
        </Button>
      </div>

      {error && <ErrorBanner message={error instanceof Error ? error.message : "Failed to load logs."} />}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-12"><Spinner className="mx-auto" /></div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState title="No log records" hint="Adjust filters to see results." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Timestamp</TH>
                  <TH>Employee</TH>
                  <TH>Location</TH>
                  <TH>Confidence</TH>
                  <TH>Type</TH>
                  <TH>Sync</TH>
                </TR>
              </THead>
              <TBody>
                {data.items.map((log) => (
                  <TR key={log.id}>
                    <TD className="font-medium">{formatDateTime(log.timestamp)}</TD>
                    <TD>
                      <div>{log.employee_name}</div>
                      <div className="text-xs text-muted-foreground">{log.employee_id}</div>
                    </TD>
                    <TD>{log.location_name}</TD>
                    <TD>{log.is_manual ? "—" : log.confidence.toFixed(4)}</TD>
                    <TD>{log.is_manual ? <Badge variant="secondary">Manual</Badge> : <Badge variant="outline">Detection</Badge>}</TD>
                    <TD><SyncStatusBadge status={log.sync_status as "pending" | "sent" | "failed" | "manual"} /></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {data && data.total > data.limit && (
        <Pagination
          page={data.page}
          total={data.total}
          limit={data.limit}
          onPrev={() => setParams((p) => ({ ...p, page: (p.page ?? 1) - 1 }))}
          onNext={() => setParams((p) => ({ ...p, page: (p.page ?? 1) + 1 }))}
        />
      )}
    </div>
  );
}

// --- Audit tab ----------------------------------------------------------
function AuditTab() {
  const [params, setParams] = useState<AuditParams>({ page: 1, limit: 25 });
  const [action, setAction] = useState("");
  const [source, setSource] = useState("");
  const { data, isLoading, error, isFetching } = useAuditLog(params);

  const runSearch = () => setParams((p) => ({ ...p, action: action || undefined, source: source || undefined, page: 1 }));

  const exportCsv = async () => {
    const qs = new URLSearchParams();
    if (params.action) qs.set("action", params.action);
    if (params.source) qs.set("source", params.source);
    const blob = await api.download(`/api/v1/reports/audit/export?${qs.toString()}`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "audit_log.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Action (e.g. employee.create)"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="max-w-xs"
        />
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="">Any source</option>
          <option value="api">API</option>
          <option value="dashboard">Dashboard</option>
        </select>
        <Button variant="outline" size="sm" onClick={runSearch}>
          Filter
        </Button>
        {isFetching && <Spinner className="h-4 w-4" />}
        <div className="flex-1" />
        <Button variant="outline" size="sm" onClick={exportCsv} className="gap-2">
          <Download className="h-4 w-4" /> Export CSV
        </Button>
      </div>

      {error && <ErrorBanner message={error instanceof Error ? error.message : "Failed to load audit log."} />}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-12"><Spinner className="mx-auto" /></div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState title="No audit entries" hint="Administrative actions will appear here." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Action</TH>
                  <TH>Actor</TH>
                  <TH>Source</TH>
                  <TH>Details</TH>
                </TR>
              </THead>
              <TBody>
                {data.items.map((row) => (
                  <TR key={row.id}>
                    <TD className="font-medium">{formatDateTime(row.created_at)}</TD>
                    <TD><Badge variant="outline">{row.action}</Badge></TD>
                    <TD>{row.actor || "—"}</TD>
                    <TD>
                      <Badge variant={row.source === "api" ? "secondary" : "default"}>{row.source}</Badge>
                    </TD>
                    <TD className="max-w-md">
                      {row.note ? (
                        <span className="text-sm">{row.note}</span>
                      ) : row.new_value ? (
                        <code className="block max-h-12 overflow-auto rounded bg-muted px-1.5 py-0.5 text-xs">
                          {row.old_value ? `${row.old_value} → ` : ""}{row.new_value}
                        </code>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
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
        <Pagination
          page={data.page}
          total={data.total}
          limit={data.limit}
          onPrev={() => setParams((p) => ({ ...p, page: (p.page ?? 1) - 1 }))}
          onNext={() => setParams((p) => ({ ...p, page: (p.page ?? 1) + 1 }))}
        />
      )}
    </div>
  );
}

function Pagination({ page, total, limit, onPrev, onNext }: { page: number; total: number; limit: number; onPrev: () => void; onNext: () => void }) {
  return (
    <div className="flex items-center justify-between text-sm text-muted-foreground">
      <span>
        Page {page} of {Math.ceil(total / limit)} · {total} records
      </span>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={onPrev}>
          Previous
        </Button>
        <Button size="sm" variant="outline" disabled={page * limit >= total} onClick={onNext}>
          Next
        </Button>
      </div>
    </div>
  );
}
