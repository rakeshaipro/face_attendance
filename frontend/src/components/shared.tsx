import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { CameraStatus, ServiceState, SyncStatus } from "@/lib/types";
import { AlertCircle, CheckCircle2, Clock, PauseCircle, Power, XCircle } from "lucide-react";

export function ServiceStateBadge({ state }: { state: ServiceState }) {
  switch (state) {
    case "running":
      return (
        <Badge variant="success" className="gap-1">
          <CheckCircle2 className="h-3 w-3" /> Running
        </Badge>
      );
    case "paused":
      return (
        <Badge variant="warning" className="gap-1">
          <PauseCircle className="h-3 w-3" /> Paused
        </Badge>
      );
    default:
      return (
        <Badge variant="secondary" className="gap-1">
          <Power className="h-3 w-3" /> Stopped
        </Badge>
      );
  }
}

export function CameraBadge({ status }: { status: CameraStatus }) {
  return status === "online" ? (
    <Badge variant="success" className="gap-1">
      <CheckCircle2 className="h-3 w-3" /> Camera online
    </Badge>
  ) : (
    <Badge variant="destructive" className="gap-1">
      <XCircle className="h-3 w-3" /> Camera offline
    </Badge>
  );
}

export function SyncStatusBadge({ status }: { status: SyncStatus }) {
  const map: Record<SyncStatus, { variant: "default" | "secondary" | "destructive" | "warning"; icon: typeof Clock }> = {
    sent: { variant: "default", icon: CheckCircle2 },
    pending: { variant: "warning", icon: Clock },
    failed: { variant: "destructive", icon: XCircle },
    manual: { variant: "secondary", icon: AlertCircle },
  };
  const cfg = map[status];
  const Icon = cfg.icon;
  return (
    <Badge variant={cfg.variant} className="gap-1 capitalize">
      <Icon className="h-3 w-3" /> {status}
    </Badge>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-12 text-center text-muted-foreground">
      <AlertCircle className="h-8 w-8 opacity-50" />
      <p className="font-medium text-foreground">{title}</p>
      {hint && <p className="text-sm">{hint}</p>}
    </div>
  );
}

export function ComingSoon({ section, phase }: { section: string; phase: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-16 text-center">
      <Clock className="h-10 w-10 text-muted-foreground" />
      <h2 className="text-xl font-semibold">{section}</h2>
      <p className="max-w-md text-muted-foreground">
        This section is part of <span className="font-medium">{phase}</span> and not yet implemented.
        The backend endpoint group currently returns HTTP 501.
      </p>
    </div>
  );
}

export function ErrorBanner({ message, className }: { message: string; className?: string }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive",
        className,
      )}
    >
      <AlertCircle className="h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}
