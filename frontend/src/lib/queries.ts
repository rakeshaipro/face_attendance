import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type {
  AttendanceLog,
  Backup,
  BackupScheduleConfig,
  BulkImportResult,
  CameraSettings,
  CameraSettingsUpdate,
  CameraTestResult,
  CaptureOut,
  CaptureSummary,
  DeviceInfo,
  Employee,
  EngineStats,
  EnrollmentStatus,
  FinalizeResult,
  HealthSummary,
  ManualEntryBody,
  MonitoringStatus,
  NtpResult,
  PoseCheckResult,
  PoseProtocol,
  PoseStep,
  RestoreResult,
  SystemLogRow,
  SystemLogsParams,
  TimeInfo,
  TimeUpdate,
  VerifyResult,
} from "./types";

// --- Reusable invalidation keys.
export const qk = {
  health: ["health"] as const,
  device: ["device"] as const,
  deviceStats: ["device", "stats"] as const,
  employees: (params?: object) => ["employees", params ?? {}] as const,
  employee: (id: string) => ["employee", id] as const,
  blockedEmployees: ["employees", "blocked"] as const,
  enrollmentStatus: (id: string) => ["enrollment", id] as const,
  enrollmentProtocol: ["enrollment", "protocol"] as const,
  enrollmentCaptures: (id: string) => ["enrollment", id, "captures"] as const,
  attendance: (params?: object) => ["attendance", params ?? {}] as const,
  attendanceToday: (params?: object) => ["attendance", "today", params ?? {}] as const,
  backups: ["backups"] as const,
  backupSchedule: ["backups", "schedule"] as const,
  systemLogs: (params?: object) => ["system_logs", params ?? {}] as const,
};

// --- Health / device ----------------------------------------------------
export const useHealth = () =>
  useQuery({ queryKey: qk.health, queryFn: () => api.get<HealthSummary>("/health"), refetchInterval: 10_000 });

export const useDevice = () =>
  useQuery({ queryKey: qk.device, queryFn: () => api.get<DeviceInfo>("/api/v1/device") });

export const useDeviceStats = () =>
  useQuery({
    queryKey: qk.deviceStats,
    queryFn: () => api.get<EngineStats>("/api/v1/device/stats"),
    refetchInterval: 5_000,
  });

export const useCameraSettings = () =>
  useQuery({ queryKey: ["device", "camera"], queryFn: () => api.get<CameraSettings>("/api/v1/device/camera") });

export const useUpdateCameraSettings = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CameraSettingsUpdate) => api.put<CameraSettings>("/api/v1/device/camera", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.device });
      qc.invalidateQueries({ queryKey: ["device", "camera"] });
    },
  });
};

export const useCameraTest = () =>
  useMutation({ mutationFn: (url?: string) => api.post<CameraTestResult>("/api/v1/device/camera/test", url ? { url } : {}) });

export const useServiceAction = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (action: "restart" | "pause" | "resume") =>
      api.post<{ service_state: string }>(`/api/v1/device/service/${action}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.device });
      qc.invalidateQueries({ queryKey: qk.deviceStats });
      qc.invalidateQueries({ queryKey: qk.health });
    },
  });
};

// --- Employees ----------------------------------------------------------
export interface EmployeeListParams {
  q?: string;
  enrolled?: boolean;
  blocked?: boolean;
  active?: boolean;
  page?: number;
  limit?: number;
}

export const useEmployees = (params: EmployeeListParams) =>
  useQuery({
    queryKey: qk.employees(params),
    queryFn: () => api.get<{ items: Employee[]; total: number; page: number; limit: number }>("/api/v1/employees", params as Record<string, unknown>),
    placeholderData: (prev) => prev,
  });

export const useEmployee = (id: string | undefined) =>
  useQuery({
    queryKey: qk.employee(id ?? ""),
    queryFn: () => api.get<Employee>(`/api/v1/employees/${id}`),
    enabled: !!id,
  });

export const useCreateEmployee = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Employee> & { employee_id: string; name: string }) =>
      api.post<Employee>("/api/v1/employees", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["employees"] }),
  });
};

export const useUpdateEmployee = (id: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Employee>) => api.put<Employee>(`/api/v1/employees/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.employee(id) });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });
};

export const useDeleteEmployee = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.del<{ deleted: string }>(`/api/v1/employees/${id}`, { reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["employees"] }),
  });
};

export const useToggleBlock = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, block }: { id: string; block: boolean }) =>
      api.post<Employee>(`/api/v1/employees/${id}/${block ? "block" : "unblock"}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["employees"] }),
  });
};

export const useImportEmployees = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.upload<BulkImportResult>("/api/v1/employees/import", file, file.name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["employees"] }),
  });
};

// --- Enrollment ---------------------------------------------------------
export const useEnrollmentStatus = (id: string | undefined) =>
  useQuery({
    queryKey: qk.enrollmentStatus(id ?? ""),
    queryFn: () => api.get<EnrollmentStatus>(`/api/v1/employees/${id}/face`),
    enabled: !!id,
  });

export const useCapturesSummary = (id: string | undefined) =>
  useQuery({
    queryKey: qk.enrollmentCaptures(id ?? ""),
    queryFn: () => api.get<CaptureSummary[]>(`/api/v1/employees/${id}/face/captures`),
    enabled: !!id,
  });

export const useEnrollmentProtocol = () =>
  useQuery({ queryKey: qk.enrollmentProtocol, queryFn: () => api.get<PoseProtocol>("/api/v1/employees/_/face/protocol") });

export const usePoseCheck = (employeeId: string) =>
  useMutation({
    mutationFn: ({ step, file }: { step: number; file: Blob }) =>
      api.upload<PoseCheckResult>(`/api/v1/employees/${employeeId}/face/pose-check`, file, "frame.jpg", { step }),
  });

export const useCapture = (employeeId: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ step, file }: { step: number; file: Blob }) =>
      api.upload<CaptureOut>(`/api/v1/employees/${employeeId}/face/capture`, file, "frame.jpg", { step }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.enrollmentStatus(employeeId) });
      qc.invalidateQueries({ queryKey: qk.enrollmentCaptures(employeeId) });
    },
  });
};

export const useFinalizeEnrollment = (employeeId: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<FinalizeResult>(`/api/v1/employees/${employeeId}/face/finalize`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.enrollmentStatus(employeeId) });
      qc.invalidateQueries({ queryKey: qk.enrollmentCaptures(employeeId) });
      qc.invalidateQueries({ queryKey: qk.employee(employeeId) });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });
};

export const useReEnroll = (employeeId: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ cleared: boolean }>(`/api/v1/employees/${employeeId}/face/re-enroll`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.enrollmentStatus(employeeId) });
      qc.invalidateQueries({ queryKey: qk.enrollmentCaptures(employeeId) });
      qc.invalidateQueries({ queryKey: qk.employee(employeeId) });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });
};

export const useRemoveFace = (employeeId: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<{ removed: boolean }>(`/api/v1/employees/${employeeId}/face`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.enrollmentStatus(employeeId) });
      qc.invalidateQueries({ queryKey: qk.enrollmentCaptures(employeeId) });
      qc.invalidateQueries({ queryKey: qk.employee(employeeId) });
    },
  });
};

export const useRemoveCapture = (employeeId: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (step: number) =>
      api.del<{ removed: boolean; step: number }>(`/api/v1/employees/${employeeId}/face/captures/${step}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.enrollmentStatus(employeeId) });
      qc.invalidateQueries({ queryKey: qk.enrollmentCaptures(employeeId) });
      qc.invalidateQueries({ queryKey: qk.employee(employeeId) });
    },
  });
};

export const useVerify = (employeeId: string) =>
  useMutation({
    mutationFn: (file: Blob) =>
      api.upload<VerifyResult>(`/api/v1/employees/${employeeId}/face/verify`, file, "frame.jpg"),
  });

// --- Attendance ---------------------------------------------------------
export interface AttendanceListParams {
  employee_id?: string;
  date?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
}

export const useAttendance = (params: AttendanceListParams, enabled = true) =>
  useQuery({
    queryKey: qk.attendance(params),
    queryFn: () =>
      api.get<{ items: AttendanceLog[]; total: number; page: number; limit: number }>("/api/v1/attendance", params as Record<string, unknown>),
    placeholderData: (prev) => prev,
    enabled,
  });

export const useAttendanceToday = (employeeId?: string) =>
  useQuery({
    queryKey: qk.attendanceToday({ employee_id: employeeId }),
    queryFn: () =>
      api.get<{ items: AttendanceLog[]; total: number; page: number; limit: number }>("/api/v1/attendance/today", {
        employee_id: employeeId,
        limit: 50,
      }),
    refetchInterval: 10_000,
  });

export const useManualEntry = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ManualEntryBody) => api.post<AttendanceLog>("/api/v1/attendance/manual", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["attendance"] }),
  });
};

export const useEditLog = (id: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { timestamp?: string; note?: string | null }) =>
      api.put<AttendanceLog>(`/api/v1/attendance/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["attendance"] }),
  });
};

export const useDeleteLog = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api.del<{ deleted: string }>(`/api/v1/attendance/${id}`, { reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["attendance"] }),
  });
};

// --- Reports (§3.9) -----------------------------------------------------
export interface ReportLogParams {
  employee_id?: string;
  date?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
}

export interface ReportLogRow {
  id: string;
  machine_id: string;
  location_name: string;
  employee_id: string;
  employee_name: string;
  timestamp: string;
  confidence: number;
  is_manual: boolean;
  manual_reason: string | null;
  sync_status: string;
  snapshot_available: boolean;
  created_at: string;
}

export const useReportLogs = (params: ReportLogParams) =>
  useQuery({
    queryKey: ["reports", "logs", params],
    queryFn: () =>
      api.get<{ items: ReportLogRow[]; total: number; page: number; limit: number }>("/api/v1/reports/logs", params as Record<string, unknown>),
    placeholderData: (prev) => prev,
  });

export interface AuditLogRow {
  id: string;
  action: string;
  affected_id: string | null;
  source: string;
  actor: string | null;
  old_value: string | null;
  new_value: string | null;
  note: string | null;
  created_at: string;
}

export interface AuditParams {
  action?: string;
  source?: string;
  actor?: string;
  affected_id?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
}

export const useAuditLog = (params: AuditParams) =>
  useQuery({
    queryKey: ["reports", "audit", params],
    queryFn: () =>
      api.get<{ items: AuditLogRow[]; total: number; page: number; limit: number }>("/api/v1/reports/audit", params as Record<string, unknown>),
    placeholderData: (prev) => prev,
  });

// --- Webhooks (§3.6) ----------------------------------------------------
export interface Webhook {
  id: string;
  target_url: string;
  events: string[];
  custom_headers: Record<string, string> | null;
  is_enabled: boolean;
  max_retries: number;
  timeout_ms: number;
  has_secret: boolean;
  created_at: string;
  updated_at: string;
}

export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  attendance_log_id: string | null;
  event_type: string;
  delivery_id: string;
  attempt: number;
  status_code: number | null;
  response_body: string | null;
  latency_ms: number | null;
  error: string | null;
  outcome: string;
  created_at: string;
}

export interface WebhookTestResult {
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
}

export const useWebhooks = () =>
  useQuery({
    queryKey: ["webhooks"],
    queryFn: () => api.get<Webhook[]>("/api/v1/webhooks"),
  });

export const useCreateWebhook = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      target_url: string;
      events: string[];
      secret?: string | null;
      max_retries?: number;
      timeout_ms?: number;
      is_enabled?: boolean;
    }) => api.post<Webhook>("/api/v1/webhooks", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
};

export const useUpdateWebhook = (wid: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<{
      target_url: string;
      events: string[];
      secret: string | null;
      max_retries: number;
      timeout_ms: number;
      is_enabled: boolean;
    }>) => api.put<Webhook>(`/api/v1/webhooks/${wid}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
};

export const useDeleteWebhook = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (wid: string) => api.del<{ deleted: string }>(`/api/v1/webhooks/${wid}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
};

export const useTestWebhook = () =>
  useMutation({
    mutationFn: (wid: string) => api.post<WebhookTestResult>(`/api/v1/webhooks/${wid}/test`),
  });

export const useWebhookDeliveries = (wid: string | undefined) =>
  useQuery({
    queryKey: ["webhooks", wid, "deliveries"],
    queryFn: () =>
      api.get<{ items: WebhookDelivery[]; total: number; page: number; limit: number }>(
        `/api/v1/webhooks/${wid}/deliveries`,
        { limit: 50 },
      ),
    enabled: !!wid,
  });

export const useRetryDelivery = () =>
  useMutation({
    mutationFn: (delivery_db_id: string) =>
      api.post<{ queued: boolean }>(`/api/v1/webhooks/deliveries/${delivery_db_id}/retry`),
  });

export const WEBHOOK_EVENT_TYPES = [
  "employee.detected",
  "device.camera_offline",
  "device.camera_online",
  "device.storage_low",
] as const;

// --- Sync (§3.7) -------------------------------------------------------
export interface SyncCounts {
  pending: number;
  sent: number;
  failed: number;
  manual: number;
  total: number;
}

export interface BatchResult {
  attempted: number;
  delivered: number;
  failed: number;
  batches: number;
  error: string | null;
}

export interface SyncConfig {
  auto_enabled: boolean;
  auto_interval_seconds: number;
  batch_size: number;
  batch_url: string;
}

export const useSyncStatus = () =>
  useQuery({ queryKey: ["sync", "status"], queryFn: () => api.get<SyncCounts>("/api/v1/sync/status"), refetchInterval: 10_000 });

export const useSyncConfig = () =>
  useQuery({ queryKey: ["sync", "config"], queryFn: () => api.get<SyncConfig>("/api/v1/sync/config") });

export const useUpdateSyncConfig = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SyncConfig) => api.put<SyncConfig>("/api/v1/sync/config", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sync"] }),
  });
};

export const useRunBatch = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { date_from?: string; date_to?: string; only_status?: string[] }) =>
      api.post<BatchResult>("/api/v1/sync/batch", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sync"] }),
  });
};

export const useResendBatch = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { date_from?: string; date_to?: string; only_status?: string[] }) =>
      api.post<BatchResult>("/api/v1/sync/resend", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sync"] }),
  });
};

// --- Time (§3.1.10, §3.1.11) ------------------------------------------
// Poll every 60s so the live clock can recompute its server-vs-browser
// skew without per-second requests; the component ticks locally each 1s.
export const useTime = () =>
  useQuery({
    queryKey: ["time"],
    queryFn: () => api.get<TimeInfo>("/api/v1/time"),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });

export const useUpdateTime = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TimeUpdate) => api.put<TimeInfo>("/api/v1/time", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["time"] }),
  });
};

export const useNtpSync = () =>
  useMutation({
    mutationFn: () => api.post<NtpResult>("/api/v1/time/ntp-sync"),
  });

// --- Backups & system logs (§3.10, §3.12) ------------------------------
export const useBackups = () =>
  useQuery({ queryKey: qk.backups, queryFn: () => api.get<Backup[]>("/api/v1/backup") });

export const useBackupSchedule = () =>
  useQuery({ queryKey: qk.backupSchedule, queryFn: () => api.get<BackupScheduleConfig>("/api/v1/backup/schedule") });

export const useUpdateBackupSchedule = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BackupScheduleConfig) => api.put<BackupScheduleConfig>("/api/v1/backup/schedule", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.backupSchedule }),
  });
};

export const useCreateBackup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (kind: "full" | "database") => api.post<Backup>("/api/v1/backup", { kind }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.backups }),
  });
};

export const useDeleteBackup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<{ deleted: string }>(`/api/v1/backup/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.backups }),
  });
};

export const useRestoreBackup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) =>
      api.upload<RestoreResult>("/api/v1/backup/restore", file, file.name, { confirm: true }),
    onSuccess: () => {
      // A successful restore replaces the DB — invalidate everything that
      // reads from it. health/attendance cover the operator-visible state.
      qc.invalidateQueries({ queryKey: ["backups"] });
      qc.invalidateQueries({ queryKey: ["system_logs"] });
      qc.invalidateQueries({ queryKey: ["health"] });
      qc.invalidateQueries({ queryKey: ["employees"] });
      qc.invalidateQueries({ queryKey: ["attendance"] });
    },
  });
};

export const useSystemLogs = (params: SystemLogsParams) =>
  useQuery({
    queryKey: qk.systemLogs(params),
    queryFn: () =>
      api.get<{ items: SystemLogRow[]; total: number; page: number; limit: number }>(
        "/api/v1/system/logs",
        params as Record<string, unknown>,
      ),
    placeholderData: (prev) => prev,
  });

// --- Monitoring (§3.11) ------------------------------------------------
export const useMonitoringStatus = () =>
  useQuery({
    queryKey: ["monitoring", "status"],
    queryFn: () => api.get<MonitoringStatus>("/api/v1/monitoring/status"),
    refetchInterval: 30_000,
  });

// --- Generic settings (read/write key-value pairs from /api/v1/settings)
import type { SettingItem, SettingUpdateResult, SettingsUpdate } from "./types";

export function useAllSettings() {
  return useQuery({
    queryKey: ["settings", "all"],
    queryFn: () => api.get<{ items: SettingItem[] }>("/api/v1/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (updates: SettingsUpdate[]): Promise<{ items: SettingUpdateResult[] }> => {
      return api.put<{ items: SettingUpdateResult[] }>("/api/v1/settings", { items: updates });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export { type PoseStep };
