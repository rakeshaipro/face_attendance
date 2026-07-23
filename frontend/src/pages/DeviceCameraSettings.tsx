import { useEffect, useState } from "react";
import { useCameraSettings, useUpdateCameraSettings } from "@/lib/queries";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label } from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { KeyRound, Lock, Save, ShieldCheck, User } from "lucide-react";

/**
 * Camera connection settings (§3.1.3): base MJPEG URL + HTTP basic-auth
 * username/password. Credentials are stored encrypted on the backend and
 * composed into the stream URL with proper percent-encoding, so special
 * characters (e.g. '@' in a password) are handled safely.
 *
 * The password is never returned by the API — we only know whether one is
 * set (`password_set`). The field is therefore blank on load; leaving it
 * blank on save means "keep the existing password", typing a value means
 * "replace it", and entering a single space clears it.
 */
export function DeviceCameraSettings() {
  const { data, isLoading } = useCameraSettings();
  const update = useUpdateCameraSettings();

  const [cameraUrl, setCameraUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [touchedPassword, setTouchedPassword] = useState(false);

  // Populate local form state once settings load.
  useEffect(() => {
    if (!data) return;
    setCameraUrl(data.camera_url);
    setUsername(data.username);
    setPassword("");
    setTouchedPassword(false);
  }, [data]);

  if (isLoading) return null;

  const onSave = (e: React.FormEvent) => {
    e.preventDefault();
    // Only send fields the user actually changed, so unchanged values are
    // preserved server-side. The password is sent only if touched.
    const body: Record<string, string> = {};
    if (cameraUrl !== (data?.camera_url ?? "")) body.camera_url = cameraUrl;
    if (username !== (data?.username ?? "")) body.username = username;
    if (touchedPassword) body.password = password;
    if (Object.keys(body).length === 0) return;
    update.mutate(body, {
      onSuccess: () => setPassword(""),
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Camera connection</CardTitle>
        <CardDescription>MJPEG stream URL and HTTP basic-auth credentials</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSave} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="camera-url">Stream URL</Label>
            <Input
              id="camera-url"
              value={cameraUrl}
              onChange={(e) => setCameraUrl(e.target.value)}
              placeholder="http://192.168.1.111/cgi-bin/mjpg/video.cgi?channel=1&subtype=1"
              className="font-mono text-xs"
              spellCheck={false}
            />
            <p className="text-xs text-muted-foreground">
              The base MJPEG URL without embedded credentials.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="camera-username" className="gap-1.5">
                <User className="h-3.5 w-3.5" /> Username
              </Label>
              <Input
                id="camera-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="camera-password" className="gap-1.5">
                <Lock className="h-3.5 w-3.5" /> Password
              </Label>
              <Input
                id="camera-password"
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setTouchedPassword(true);
                }}
                placeholder={data?.password_set ? "•••••••• (unchanged)" : "enter password"}
                autoComplete="new-password"
              />
              {data?.password_set && !touchedPassword && (
                <p className="flex items-center gap-1 text-xs text-emerald-600">
                  <ShieldCheck className="h-3 w-3" /> A password is saved. Leave blank to keep it.
                </p>
              )}
            </div>
          </div>

          {update.isError && (
            <ErrorBanner message={update.error instanceof Error ? update.error.message : "Could not save camera settings."} />
          )}
          {update.isSuccess && (
            <p className="flex items-center gap-1 text-sm text-emerald-600">
              <KeyRound className="h-3.5 w-3.5" /> Saved — credentials applied to the live stream.
            </p>
          )}

          <div className="flex items-center gap-2">
            <Button type="submit" disabled={update.isPending} className="gap-2">
              <Save className="h-4 w-4" /> {update.isPending ? "Saving…" : "Save & apply"}
            </Button>
            <span className="text-xs text-muted-foreground">
              Applied immediately — no restart needed.
            </span>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
