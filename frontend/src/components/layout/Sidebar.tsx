import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Radio,
  Users,
  CalendarCheck,
  FileBarChart,
  RefreshCw,
  Webhook,
  Cpu,
  Settings,
  ScanFace,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
}

const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Overview",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/live", label: "Live View", icon: Radio },
    ],
  },
  {
    group: "People",
    items: [{ to: "/employees", label: "Employees", icon: Users }],
  },
  {
    group: "Records",
    items: [
      { to: "/attendance", label: "Attendance", icon: CalendarCheck },
      { to: "/reports", label: "Reports", icon: FileBarChart },
    ],
  },
  {
    group: "Integration",
    items: [
      { to: "/sync", label: "Sync", icon: RefreshCw },
      { to: "/webhooks", label: "Webhooks", icon: Webhook },
    ],
  },
  {
    group: "System",
    items: [
      { to: "/device", label: "Device", icon: Cpu },
      { to: "/system", label: "System", icon: Settings },
    ],
  },
];

export function Sidebar() {
  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-r bg-card">
      <div className="flex h-14 items-center gap-2 border-b px-5">
        <ScanFace className="h-5 w-5 text-primary" />
        <span className="font-semibold tracking-tight">Face Attendance</span>
      </div>
      <nav className="flex-1 space-y-6 overflow-y-auto p-3">
        {NAV.map((section) => (
          <div key={section.group}>
            <p className="mb-1 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {section.group}
            </p>
            <div className="space-y-0.5">
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                    )
                  }
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
