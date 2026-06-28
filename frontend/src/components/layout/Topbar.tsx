import { useHealth } from "@/lib/queries";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui";
import { CameraBadge, ServiceStateBadge } from "@/components/shared";
import { LogOut } from "lucide-react";

interface TopbarProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export function Topbar({ title, subtitle, actions }: TopbarProps) {
  const { logout } = useAuth();
  const { data: health } = useHealth();

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b bg-background px-6">
      <div>
        <h1 className="text-lg font-semibold leading-none">{title}</h1>
        {subtitle && <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-3">
        {actions}
        {health && (
          <div className="hidden items-center gap-2 md:flex">
            <ServiceStateBadge state={health.recognition_service} />
            <CameraBadge status={health.camera_status} />
          </div>
        )}
        <Button variant="ghost" size="sm" onClick={logout} className="gap-2">
          <LogOut className="h-4 w-4" /> Sign out
        </Button>
      </div>
    </header>
  );
}
