import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const TITLES: Record<string, { title: string; subtitle?: string }> = {
  "/": { title: "Dashboard", subtitle: "System health and live operational metrics" },
  "/live": { title: "Live View", subtitle: "Camera preview and recent detections" },
  "/employees": { title: "Employees", subtitle: "Manage employee records and enrollments" },
  "/attendance": { title: "Attendance", subtitle: "Detection log, manual entries, and snapshots" },
  "/reports": { title: "Reports", subtitle: "Log queries and exports" },
  "/sync": { title: "Sync", subtitle: "HRMS synchronisation status" },
  "/webhooks": { title: "Webhooks", subtitle: "Outgoing event subscriptions" },
  "/device": { title: "Device", subtitle: "This installation's identity and camera" },
  "/system": { title: "System", subtitle: "Settings, backups, and API keys" },
};

export function AppShell() {
  const { pathname } = useLocation();
  const meta = TITLES[pathname] ?? { title: "Face Attendance" };

  return (
    <div className="flex h-screen overflow-hidden bg-muted/20">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar title={meta.title} subtitle={meta.subtitle} />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
