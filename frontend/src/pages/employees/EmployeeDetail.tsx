import { Link, useParams } from "react-router-dom";
import { useAttendance, useEmployee } from "@/lib/queries";
import { Enrollment } from "./Enrollment";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Spinner } from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { formatConfidence, formatDateTime, formatRelative } from "@/lib/utils";
import { ArrowLeft } from "lucide-react";

export function EmployeeDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: emp, isLoading, error } = useEmployee(id);
  const {
    data: logs,
    isLoading: logsLoading,
    error: logsError,
  } = useAttendance({ employee_id: emp?.id, limit: 10 }, !!emp?.id);

  if (isLoading) return <Spinner className="mx-auto mt-12" />;
  if (error || !emp)
    return <ErrorBanner message={error instanceof Error ? error.message : "Employee not found."} />;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/employees" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Back to employees
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Profile */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>{emp.name}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Detail label="Employee ID" value={<code className="rounded bg-muted px-1.5">{emp.employee_id}</code>} />
            <Detail label="Phone" value={emp.phone || "—"} />
            <Detail label="Email" value={emp.email || "—"} />
            <Detail
              label="Status"
              value={
                emp.is_blocked ? (
                  <Badge variant="destructive">Blocked</Badge>
                ) : emp.is_active ? (
                  <Badge variant="success">Active</Badge>
                ) : (
                  <Badge variant="secondary">Inactive</Badge>
                )
              }
            />
            <Detail
              label="Enrolled"
              value={
                emp.is_enrolled ? (
                  <Badge variant="default">Yes · quality {formatConfidence(emp.enrollment_quality)}</Badge>
                ) : (
                  <Badge variant="outline">No</Badge>
                )
              }
            />
            <Detail label="Enrolled at" value={formatDateTime(emp.enrolled_at)} />
            <Detail label="Created" value={formatRelative(emp.created_at)} />
            <Detail label="Updated" value={formatRelative(emp.updated_at)} />
          </CardContent>
        </Card>

        {/* Enrollment flow */}
        <div className="lg:col-span-2">
          <Enrollment employeeId={emp.id} employeeName={emp.name} />
        </div>
      </div>

      {/* Recent detections for this employee */}
      <Card>
        <CardHeader>
          <CardTitle>Recent detections</CardTitle>
        </CardHeader>
        <CardContent>
          {logsLoading ? (
            <Spinner className="h-5 w-5" />
          ) : logsError ? (
            <ErrorBanner message={logsError instanceof Error ? logsError.message : "Failed to load attendance records."} />
          ) : !logs || logs.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No attendance records yet.</p>
          ) : (
            <ul className="divide-y text-sm">
              {logs.items.map((log) => (
                <li key={log.id} className="flex items-center justify-between py-2">
                  <div>
                    <span className="font-medium">{formatDateTime(log.timestamp)}</span>
                    {log.is_manual && <Badge variant="secondary" className="ml-2">Manual</Badge>}
                  </div>
                  <span className="text-muted-foreground">confidence {formatConfidence(log.confidence)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
