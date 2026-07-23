/** TypeScript types mirroring the backend Pydantic schemas (Phases 1–3). */

export interface Envelope<T> {
  success: boolean;
  data: T | null;
  error: string | null;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

// --- Enums -------------------------------------------------------------
export type ServiceState = "running" | "paused" | "stopped";
export type CameraStatus = "online" | "offline";
export type SyncStatus = "pending" | "sent" | "failed" | "manual";

// --- Device / health ---------------------------------------------------
export interface DeviceInfo {
  machine_id: string;
  location_name: string;
  software_version: string;
  server_uptime_seconds: number;
  timezone: string;
  camera_url_masked: string;
  service_state: ServiceState;
  camera_status: CameraStatus;
}

export interface CameraTestResult {
  reachable: boolean;
  latency_ms: number | null;
  width: number | null;
  height: number | null;
  error: string | null;
}

export interface CameraSettings {
  camera_url: string;
  username: string;
  password_set: boolean;
}

export interface CameraSettingsUpdate {
  camera_url?: string;
  username?: string;
  password?: string;
}

export interface EngineStats {
  service_state: ServiceState;
  camera_status: CameraStatus;
  fps: number;
  detections_last_hour: number;
  detections_last_24h: number;
  avg_confidence_24h: number | null;
  last_frame_at: string | null;
}

export interface HealthSummary {
  recognition_service: ServiceState;
  camera_status: CameraStatus;
  disk_free_mb: number;
  enrolled_employees: number;
  total_log_records: number;
  server_uptime_seconds: number;
}

// --- Employees ---------------------------------------------------------
export interface Employee {
  id: string;
  employee_id: string;
  name: string;
  phone: string | null;
  email: string | null;
  is_active: boolean;
  is_blocked: boolean;
  is_enrolled: boolean;
  enrolled_at: string | null;
  enrollment_quality: number | null;
  created_at: string;
  updated_at: string;
}

export interface EmployeeCreate {
  employee_id: string;
  name: string;
  phone?: string | null;
  email?: string | null;
  is_active?: boolean;
}

export interface BulkImportRow {
  row: number;
  employee_id: string;
  status: "ok" | "error";
  error: string | null;
}

export interface BulkImportResult {
  total: number;
  succeeded: number;
  failed: number;
  rows: BulkImportRow[];
}

// --- Enrollment --------------------------------------------------------
export interface PoseStep {
  step: number;
  instruction: string;
  yaw: [number, number] | null;
  pitch: [number, number] | null;
  mandatory: boolean;
}

export interface PoseProtocol {
  steps: PoseStep[];
  mandatory_count: number;
}

export interface Quality {
  score: number;
  sharpness: number;
  brightness: number;
  face_size_ratio: number;
  acceptable: boolean;
}

export interface PoseCheckResult {
  face_detected: boolean;
  face_count: number;
  in_range: boolean;
  yaw: number | null;
  pitch: number | null;
  quality: Quality | null;
  reason: string | null;
}

export interface CaptureOut {
  step: number;
  quality: Quality;
  yaw: number | null;
  pitch: number | null;
  image_path: string;
}

export interface CaptureSummary {
  step: number;
  quality: number;
  yaw: number | null;
  pitch: number | null;
  image_path: string;
}

export interface EnrollmentStatus {
  is_enrolled: boolean;
  enrolled_at: string | null;
  capture_count: number;
  steps_captured: number[];
  overall_quality: number | null;
}

export interface FinalizeResult {
  is_enrolled: boolean;
  overall_quality: number;
  captures: CaptureOut[];
  warning: string | null;
}

export interface VerifyResult {
  face_detected: boolean;
  best_score: number | null;
  threshold: number;
  matched: boolean;
}

// --- Attendance --------------------------------------------------------
export interface AttendanceLog {
  id: string;
  machine_id: string;
  location_name: string;
  employee_id: string;
  employee_name: string;
  timestamp: string;
  confidence: number;
  snapshot_path: string | null;
  snapshot_available: boolean;
  is_manual: boolean;
  manual_reason: string | null;
  sync_status: SyncStatus;
  created_at: string;
}

export interface ManualEntryBody {
  employee_id: string;
  timestamp: string;
  reason: string;
  note?: string | null;
}

// --- Settings (§6.4) ---------------------------------------------------
export type SettingType = "str" | "int" | "float" | "bool" | "enum";

export interface SettingItem {
  key: string;
  value: string;
  value_set: boolean;
  type: SettingType;
  group: string;
  subsection: string;
  label: string;
  help: string;
  sensitive: boolean;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[] | null;
}

export interface SettingsUpdate {
  key: string;
  value: string;
  clear?: boolean;
}

export interface SettingUpdateResult {
  key: string;
  ok: boolean;
  error: string;
}

// --- Time (§3.1.10, §3.1.11) -------------------------------------------
export interface TimeInfo {
  /** ISO-8601 UTC timestamp of the server's clock at response time. */
  server_now_utc: string;
  /** Configured IANA timezone, e.g. "UTC", "Asia/Kolkata". */
  timezone: string;
  /** Configured NTP server hostname / IPv4. */
  ntp_server: string;
  /** Server process uptime in seconds. */
  uptime_seconds: number;
}

export interface TimeUpdate {
  timezone: string;
  ntp_server: string;
}

export interface NtpResult {
  server_now_utc: string;
  ntp_server: string;
  /** Signed clock offset in seconds (negative = server behind NTP). */
  offset_seconds: number;
  /** Round-trip time in milliseconds. */
  rtt_ms: number;
  synchronized: boolean;
}

// --- Backups (§3.10) ---------------------------------------------------
export interface Backup {
  id: string;
  kind: "full" | "database";
  filename: string;
  size_bytes: number;
  origin: string;
  is_scheduled: boolean;
  note: string | null;
  created_at: string;
}

export interface BackupScheduleConfig {
  enabled: boolean;
  frequency: "daily" | "weekly";
  /** HH:MM local time. */
  time: string;
  max_scheduled: number;
}

export interface RestoreResult {
  restored: boolean;
  kind: string;
  filename: string | null;
  error: string | null;
}

// --- System logs (§3.12) ----------------------------------------------
export type LogSeverity = "debug" | "info" | "warning" | "error" | "critical";

export interface SystemLogRow {
  id: string;
  severity: LogSeverity;
  event: string;
  message: string;
  context_json: string | null;
  created_at: string;
}

export interface SystemLogsParams {
  severity?: LogSeverity;
  event?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
}

// --- Monitoring (§3.11) ------------------------------------------------
export interface MonitoringStatus {
  disk_job_next: string | null;
  retention_job_next: string | null;
}
