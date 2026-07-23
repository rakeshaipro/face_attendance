import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  useCreateEmployee,
  useDeleteEmployee,
  useEmployees,
  useImportEmployees,
  useToggleBlock,
  type EmployeeListParams,
} from "@/lib/queries";
import type { Employee } from "@/lib/types";
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
import { EmptyState, ErrorBanner } from "@/components/shared";
import { Ban, CheckCircle2, Download, Plus, Search, Trash2, Upload } from "lucide-react";

export function EmployeeList() {
  const [params, setParams] = useState<EmployeeListParams>({ page: 1, limit: 25 });
  const [qInput, setQInput] = useState("");
  const { data, isLoading, error, isFetching } = useEmployees(params);
  const toggleBlock = useToggleBlock();
  const del = useDeleteEmployee();
  const imp = useImportEmployees();

  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null);
  const [deleteReason, setDeleteReason] = useState("");
  const [importResult, setImportResult] = useState<{ succeeded: number; failed: number; total: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const runSearch = () => setParams((p) => ({ ...p, q: qInput || undefined, page: 1 }));

  const onExport = async () => {
    const blob = await api.download("/api/v1/employees/export");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "employees.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const onImport = async (file: File) => {
    try {
      const res = await imp.mutateAsync(file);
      setImportResult({ succeeded: res.succeeded, failed: res.failed, total: res.total });
    } catch (e) {
      setImportResult({ succeeded: 0, failed: 0, total: 0 });
    }
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-1 items-center gap-2">
          <div className="relative max-w-xs flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search name or ID…"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
              className="pl-9"
            />
          </div>
          <Button variant="outline" size="sm" onClick={runSearch}>
            Search
          </Button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onImport(f);
            e.target.value = "";
          }}
        />
        <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()} className="gap-2">
          <Upload className="h-4 w-4" /> Import CSV
        </Button>
        <Button variant="outline" size="sm" onClick={onExport} className="gap-2">
          <Download className="h-4 w-4" /> Export
        </Button>
        <Button size="sm" onClick={() => setShowCreate(true)} className="gap-2">
          <Plus className="h-4 w-4" /> New employee
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 text-sm">
        <FilterChip
          label="Enrolled"
          active={params.enrolled === true}
          onClick={() => setParams((p) => ({ ...p, enrolled: p.enrolled === true ? undefined : true, page: 1 }))}
        />
        <FilterChip
          label="Not enrolled"
          active={params.enrolled === false}
          onClick={() => setParams((p) => ({ ...p, enrolled: p.enrolled === false ? undefined : false, page: 1 }))}
        />
        <FilterChip
          label="Blocked"
          active={params.blocked === true}
          onClick={() => setParams((p) => ({ ...p, blocked: p.blocked === true ? undefined : true, page: 1 }))}
        />
        {isFetching && <Spinner className="h-4 w-4" />}
      </div>

      {error && <ErrorBanner message={error instanceof Error ? error.message : "Failed to load employees."} />}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-12">
              <Spinner className="mx-auto" />
            </div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState title="No employees found" hint="Create one or adjust your filters." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Employee ID</TH>
                  <TH>Name</TH>
                  <TH>Status</TH>
                  <TH>Enrollment</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {data.items.map((emp) => (
                  <TR key={emp.id}>
                    <TD>
                      <Link to={`/employees/${emp.id}`} className="font-medium text-primary hover:underline">
                        {emp.employee_id}
                      </Link>
                    </TD>
                    <TD>{emp.name}</TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        {emp.is_blocked && <Badge variant="destructive">Blocked</Badge>}
                        {!emp.is_active && <Badge variant="secondary">Inactive</Badge>}
                        {emp.is_active && !emp.is_blocked && <Badge variant="success">Active</Badge>}
                      </div>
                    </TD>
                    <TD>
                      {emp.is_enrolled ? (
                        <Badge variant="default">Enrolled · {(emp.enrollment_quality ?? 0).toFixed(2)}</Badge>
                      ) : (
                        <Badge variant="outline">Not enrolled</Badge>
                      )}
                    </TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          title={emp.is_blocked ? "Unblock" : "Block"}
                          onClick={() => toggleBlock.mutate({ id: emp.id, block: !emp.is_blocked })}
                        >
                          {emp.is_blocked ? <CheckCircle2 className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
                        </Button>
                        <Button variant="ghost" size="icon" title="Delete" onClick={() => setDeleteTarget(emp)}>
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

      {/* Pagination */}
      {data && data.total > data.limit && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Page {data.page} of {Math.ceil(data.total / data.limit)} · {data.total} records
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={data.page <= 1}
              onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) - 1 }))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={data.page * data.limit >= data.total}
              onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) + 1 }))}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <CreateEmployeeDialog open={showCreate} onClose={() => setShowCreate(false)} />
      <DeleteDialog
        employee={deleteTarget}
        reason={deleteReason}
        setReason={setDeleteReason}
        onClose={() => {
          setDeleteTarget(null);
          setDeleteReason("");
        }}
        onConfirm={() => {
          if (deleteTarget) del.mutate({ id: deleteTarget.id, reason: deleteReason || "deleted via UI" });
          setDeleteTarget(null);
          setDeleteReason("");
        }}
      />
      <Dialog
        open={!!importResult}
        onClose={() => setImportResult(null)}
        title="Import result"
        description={importResult ? `${importResult.succeeded} succeeded, ${importResult.failed} failed of ${importResult.total}` : undefined}
      >
        <Button onClick={() => setImportResult(null)}>Close</Button>
      </Dialog>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
        active ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-accent"
      }`}
    >
      {label}
    </button>
  );
}

function CreateEmployeeDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateEmployee();
  const [form, setForm] = useState({ employee_id: "", name: "", phone: "", email: "" });
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await create.mutateAsync({
        employee_id: form.employee_id,
        name: form.name,
        phone: form.phone || null,
        email: form.email || null,
      });
      setForm({ employee_id: "", name: "", phone: "", email: "" });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="New employee" description="Add a new employee record">
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="eid">Employee ID *</Label>
          <Input id="eid" value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })} required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="name">Name *</Label>
          <Input id="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="phone">Phone</Label>
            <Input id="phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
        </div>
        {error && <ErrorBanner message={error} />}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function DeleteDialog({
  employee,
  reason,
  setReason,
  onClose,
  onConfirm,
}: {
  employee: Employee | null;
  reason: string;
  setReason: (s: string) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog
      open={!!employee}
      onClose={onClose}
      title="Delete employee"
      description={`This permanently removes ${employee?.name ?? ""} and all their embeddings and log records.`}
    >
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="reason">Reason (required)</Label>
          <Input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this being deleted?" />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={!reason.trim()} onClick={onConfirm}>
            Delete permanently
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
