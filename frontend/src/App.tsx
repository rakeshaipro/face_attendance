import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Login } from "./auth/Login";
import { AppShell } from "./components/layout/AppShell";
import { Dashboard } from "./pages/Dashboard";
import { LiveView } from "./pages/LiveView";
import { EmployeeList } from "./pages/employees/EmployeeList";
import { EmployeeDetail } from "./pages/employees/EmployeeDetail";
import { AttendanceList } from "./pages/attendance/AttendanceList";
import { Device } from "./pages/Device";
import { Reports } from "./pages/Reports";
import { Sync } from "./pages/Sync";
import { Webhooks } from "./pages/Webhooks";
import { System } from "./pages/System";
import { ComingSoon } from "./components/shared";

function Protected({ children }: { children: React.ReactNode }) {
  const { apiKey } = useAuth();
  if (!apiKey) return <Login />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={<Login />}
      />
      <Route
        element={
          <Protected>
            <AppShell />
          </Protected>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="live" element={<LiveView />} />
        <Route path="employees" element={<EmployeeList />} />
        <Route path="employees/:id" element={<EmployeeDetail />} />
        <Route path="attendance" element={<AttendanceList />} />
        <Route path="device" element={<Device />} />
        <Route path="reports" element={<Reports />} />
        <Route path="sync" element={<Sync />} />
        <Route path="webhooks" element={<Webhooks />} />
        <Route path="system" element={<System />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
