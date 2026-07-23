import { useHealth, useDeviceStats, useAttendanceToday } from "@/lib/queries";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Spinner } from "@/components/ui";
import { CameraBadge, EmptyState, ServiceStateBadge } from "@/components/shared";
import { cn, formatMb, formatRelative, formatUptime } from "@/lib/utils";
import { Activity, CalendarCheck, Cpu, HardDrive, Users } from "lucide-react";

export function Dashboard() {
  const { data: health, isLoading: hLoading, error: hError } = useHealth();
  const { data: stats } = useDeviceStats();
  const { data: today } = useAttendanceToday();

  if (hLoading) return <Spinner className="mx-auto mt-12" />;
  if (hError || !health) {
    return (
      <EmptyState
        title="Could not load system health"
        hint={hError instanceof Error ? hError.message : "Is the backend running on :8000?"}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Status cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Metric
          icon={<Activity className="h-4 w-4" />}
          label="Recognition service"
          value={<ServiceStateBadge state={health.recognition_service} />}
        />
        <Metric
          icon={<Cpu className="h-4 w-4" />}
          label="Camera"
          value={<CameraBadge status={health.camera_status} />}
        />
        <Metric
          icon={<HardDrive className="h-4 w-4" />}
          label="Disk free"
          value={<span className="text-2xl font-semibold">{formatMb(health.disk_free_mb)}</span>}
        />
        <Metric
          icon={<Users className="h-4 w-4" />}
          label="Enrolled employees"
          value={<span className="text-2xl font-semibold">{health.enrolled_employees}</span>}
        />
        <Metric
          icon={<CalendarCheck className="h-4 w-4" />}
          label="Total log records"
          value={<span className="text-2xl font-semibold">{health.total_log_records}</span>}
        />
        <Metric
          icon={<Activity className="h-4 w-4" />}
          label="Server uptime"
          value={<span className="text-2xl font-semibold">{formatUptime(health.server_uptime_seconds)}</span>}
        />
      </div>

      {/* Engine stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="Processing FPS" value={stats ? stats.fps.toFixed(1) : "—"} />
        <StatCard label="Detections (1h)" value={stats ? String(stats.detections_last_hour) : "—"} />
        <StatCard label="Detections (24h)" value={stats ? String(stats.detections_last_24h) : "—"} />
        <StatCard
          label="Avg confidence (24h)"
          value={stats?.avg_confidence_24h != null ? stats.avg_confidence_24h.toFixed(4) : "—"}
        />
      </div>

      {/* Recent detections */}
      <Card>
        <CardHeader>
          <CardTitle>Today's detections</CardTitle>
          <CardDescription>Most recent attendance records today</CardDescription>
        </CardHeader>
        <CardContent>
          {!today || today.items.length === 0 ? (
            <EmptyState title="No detections yet today" hint="Records will appear here as faces are recognised." />
          ) : (
            <ul className="divide-y">
              {today.items.slice(0, 8).map((log) => (
                <li key={log.id} className="flex items-center justify-between py-3">
                  <div>
                    <p className="font-medium">{log.employee_name}</p>
                    <p className="text-xs text-muted-foreground">
                      {log.is_manual ? "Manual entry" : `confidence ${log.confidence.toFixed(4)}`}
                    </p>
                  </div>
                  <span className="text-sm text-muted-foreground">{formatRelative(log.timestamp)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-5">
        <div>
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {icon} {label}
          </p>
          <div className="mt-2">{value}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function StatCard({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <Card className={cn(className)}>
      <CardContent className="p-5">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
        <p className="mt-2 text-2xl font-semibold">{value}</p>
      </CardContent>
    </Card>
  );
}
