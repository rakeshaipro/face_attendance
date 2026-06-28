import { useState } from "react";
import { useAttendanceToday } from "@/lib/queries";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { EmptyState } from "@/components/shared";
import { formatRelative } from "@/lib/utils";
import { getApiKey } from "@/lib/api";
import { Radio, RotateCcw, Video, VideoOff } from "lucide-react";

export function LiveView() {
  const { data: today } = useAttendanceToday();
  const [streamKey, setStreamKey] = useState(0);

  // Persisted camera preview toggle
  const [isFeedActive, setIsFeedActive] = useState(() => {
    const saved = localStorage.getItem("face_attendance_live_preview_active");
    return saved === "true";
  });

  const toggleFeed = () => {
    setIsFeedActive((prev) => {
      const next = !prev;
      localStorage.setItem("face_attendance_live_preview_active", String(next));
      return next;
    });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Camera preview</CardTitle>
            <CardDescription>MJPEG stream from the configured IP camera</CardDescription>
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
          <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-md bg-black">
            {isFeedActive ? (
              <>
                <img
                  key={streamKey}
                  src={`/api/v1/device/stream?key=${encodeURIComponent(getApiKey() ?? "")}`}
                  alt="Live camera stream"
                  className="max-h-full max-w-full"
                  onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0.2")}
                />
                <div className="pointer-events-none absolute bottom-3 left-3 flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">
                  <Radio className="h-3 w-3 animate-pulse text-red-500" /> LIVE
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

      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle>Recent detections</CardTitle>
          <CardDescription>Auto-refreshing · today only</CardDescription>
        </CardHeader>
        <CardContent>
          {!today || today.items.length === 0 ? (
            <EmptyState title="No detections today" hint="Records appear here in real time." />
          ) : (
            <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
              {today.items.map((log) => (
                <li key={log.id} className="rounded-md border p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{log.employee_name}</span>
                    {log.is_manual && <Badge variant="secondary">Manual</Badge>}
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
                    <span>conf {log.confidence.toFixed(4)}</span>
                    <span>{formatRelative(log.timestamp)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
