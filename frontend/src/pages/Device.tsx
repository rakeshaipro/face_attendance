import { useMemo, useState } from "react";
import {
  useAllSettings,
  useCameraTest,
  useDevice,
  useDeviceStats,
  useServiceAction,
  useUpdateSettings,
} from "@/lib/queries";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Spinner,
} from "@/components/ui";
import { CameraBadge, ErrorBanner, ServiceStateBadge } from "@/components/shared";
import { Field, SettingsCard } from "@/components/SettingsField";
import { resultsToErrorMap } from "@/components/settingsUtils";
import { formatUptime } from "@/lib/utils";
import { getApiKey } from "@/lib/api";
import { Camera, Pause, Play, RotateCcw, Video, VideoOff } from "lucide-react";
import { DeviceCameraSettings } from "./DeviceCameraSettings";
import type { SettingItem } from "@/lib/types";

/**
 * Device page (SRS §3.1).
 *
 * Three editor groups live here:
 *  - Identity   : machine_id, location, timezone, NTP
 *  - Camera URL : existing dedicated form (password-aware) for the
 *                 RTSP/MJPEG URL + creds.
 *  - Recognition: read/detect FPS, similarity threshold, cooldown,
 *                 min-face ratio. Hot-reloaded on the next 5s tick.
 */
export function Device() {
  const { data: device, isLoading, error } = useDevice();
  const { data: stats } = useDeviceStats();
  const { data: settings, isLoading: settingsLoading } = useAllSettings();
  const cameraTest = useCameraTest();
  const service = useServiceAction();
  const update = useUpdateSettings();
  const [streamKey, setStreamKey] = useState(0);
  const [lastResults, setLastResults] = useState<Record<string, string>>({});

  // Persisted camera preview toggle
  const [isFeedActive, setIsFeedActive] = useState(() => {
    const saved = localStorage.getItem("face_attendance_preview_active");
    return saved === "true";
  });

  const toggleFeed = () => {
    setIsFeedActive((prev) => {
      const next = !prev;
      localStorage.setItem("face_attendance_preview_active", String(next));
      return next;
    });
  };

  // Group the settings into the cards rendered on this page.
  const groups = useMemo(() => {
    const byGroup: Record<string, SettingItem[]> = { Identity: [], Recognition: [] };
    for (const it of settings?.items ?? []) {
      if (it.group !== "device") continue;
      const bucket = byGroup[it.subsection];
      if (bucket) bucket.push(it);
    }
    return byGroup;
  }, [settings]);

  if (isLoading || settingsLoading) return <Spinner className="mx-auto mt-12" />;
  if (error || !device) {
    return <ErrorBanner message={error instanceof Error ? error.message : "Could not load device info."} />;
  }

  const save = (items: { key: string; value: string; clear: boolean }[]) =>
    update.mutate(items, {
      onSuccess: (res) => {
        setLastResults(resultsToErrorMap(res.items));
        if (res.items.every((r) => r.ok)) {
          setLastResults({});
        }
      },
      onError: (e) => {
        // Surface as a global error on every card.
        setLastResults({ __all: e instanceof Error ? e.message : "Save failed." });
      },
    });

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Identity */}
      <SettingsCard
        title="Device identity"
        description="Machine ID, location, and clock configuration"
        items={groups.Identity}
        saving={update.isPending}
        globalError={lastResults.__all}
        onSave={save}
      />

      {/* Recognition engine — read-only stats + editor + controls */}
      <div className="space-y-6">
        <SettingsCard
          title="Recognition engine"
          description="Live matching parameters. Changes apply within ~5s — no restart required."
          items={groups.Recognition}
          saving={update.isPending}
          globalError={lastResults.__all}
          saveLabel="Apply"
          onSave={save}
        />

        <Card>
          <CardHeader>
            <CardTitle>Service control</CardTitle>
            <CardDescription>Pause or restart the recognition engine</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Field label="State" value={<ServiceStateBadge state={stats?.service_state ?? device.service_state} />} />
              <Field label="FPS" value={stats ? stats.fps.toFixed(1) : "—"} />
              <Field label="Detections (1h)" value={stats ? String(stats.detections_last_hour) : "—"} />
              <Field label="Detections (24h)" value={stats ? String(stats.detections_last_24h) : "—"} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => service.mutate("pause")}
                disabled={service.isPending}
                className="gap-2"
              >
                <Pause className="h-4 w-4" /> Pause
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => service.mutate("resume")}
                disabled={service.isPending}
                className="gap-2"
              >
                <Play className="h-4 w-4" /> Resume
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => service.mutate("restart")}
                disabled={service.isPending}
                className="gap-2"
              >
                <RotateCcw className="h-4 w-4" /> Restart
              </Button>
            </div>
            {service.isError && (
              <ErrorBanner message={service.error instanceof Error ? service.error.message : "Service action failed."} />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Camera connection (URL + basic-auth) — existing dedicated form */}
      <div className="lg:col-span-2">
        <DeviceCameraSettings />
      </div>

      {/* Camera test */}
      <Card>
        <CardHeader>
          <CardTitle>Camera test</CardTitle>
          <CardDescription>Check reachability, latency, and resolution</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button size="sm" onClick={() => cameraTest.mutate(undefined)} disabled={cameraTest.isPending} className="gap-2">
            <Camera className="h-4 w-4" /> {cameraTest.isPending ? "Testing…" : "Run test"}
          </Button>
          {cameraTest.data && (
            <div className="rounded-md border p-3 text-sm">
              <Field label="Reachable" value={cameraTest.data.reachable ? "yes" : "no"} />
              <Field label="Latency" value={cameraTest.data.latency_ms != null ? `${cameraTest.data.latency_ms} ms` : "—"} />
              <Field
                label="Resolution"
                value={
                  cameraTest.data.width && cameraTest.data.height
                    ? `${cameraTest.data.width}×${cameraTest.data.height}`
                    : "—"
                }
              />
              {cameraTest.data.error && <ErrorBanner message={cameraTest.data.error} className="mt-2" />}
            </div>
          )}
        </CardContent>
      </Card>

      {/* System info (read-only) */}
      <Card>
        <CardHeader>
          <CardTitle>System</CardTitle>
          <CardDescription>Software version and uptime</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <Field label="Machine ID" value={<code className="rounded bg-muted px-1.5 py-0.5">{device.machine_id}</code>} />
          <Field label="Location" value={device.location_name} />
          <Field label="Software version" value={device.software_version} />
          <Field label="Timezone" value={device.timezone} />
          <Field label="Uptime" value={formatUptime(device.server_uptime_seconds)} />
          <Field label="Service state" value={<ServiceStateBadge state={device.service_state} />} />
          <Field label="Camera status" value={<CameraBadge status={device.camera_status} />} />
          <Field
            label="Camera URL"
            value={<code className="block break-all rounded bg-muted px-1.5 py-0.5 text-xs">{device.camera_url_masked}</code>}
          />
        </CardContent>
      </Card>

      {/* Live preview */}
      <Card className="lg:col-span-2">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Live camera preview</CardTitle>
            <CardDescription>Camera stream (RTSP) proxied through the backend</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={isFeedActive ? "destructive" : "default"}
              onClick={toggleFeed}
              className="gap-2"
            >
              {isFeedActive ? (
                <>
                  <VideoOff className="h-4 w-4" /> Turn feed off
                </>
              ) : (
                <>
                  <Video className="h-4 w-4" /> Turn feed on
                </>
              )}
            </Button>
            {isFeedActive && (
              <Button size="sm" variant="ghost" onClick={() => setStreamKey((k) => k + 1)} className="gap-2">
                <RotateCcw className="h-4 w-4" /> Reconnect
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div id="camera-preview" className="relative flex aspect-video items-center justify-center overflow-hidden rounded-md bg-black">
            {isFeedActive ? (
              <>
                <img
                  key={streamKey}
                  src={`/api/v1/device/stream?key=${encodeURIComponent(getApiKey() ?? "")}`}
                  alt="Camera stream"
                  className="max-h-full max-w-full"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
                <div className="absolute text-xs text-white/60 pointer-events-none">
                  <Video className="mx-auto mb-1 h-5 w-5" /> Waiting for stream…
                </div>
              </>
            ) : (
              <div className="text-center text-xs text-white/60">
                <VideoOff className="mx-auto mb-1.5 h-6 w-6 text-muted-foreground" />
                <span>Camera feed is turned off</span>
                <p className="mt-1 text-[10px] text-white/40">Camera is not being accessed</p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
