import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "./AuthContext";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label } from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { ScanFace } from "lucide-react";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [key, setKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    // Stage the key so the API wrapper can send it on the validation call.
    login(key.trim());
    try {
      await api.get("/api/v1/device");
      navigate("/");
    } catch (err) {
      logout();
      const msg = err instanceof Error ? err.message : "Validation failed";
      setError(msg || "Invalid API key.");
    } finally {
      setLoading(false);
    }
  };

  const { logout } = useAuth();

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <ScanFace className="h-6 w-6" />
          </div>
          <CardTitle>Face Attendance</CardTitle>
          <CardDescription>Sign in with an API key to access the admin dashboard.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="key">API key</Label>
              <Input
                id="key"
                type="password"
                placeholder="fa_…"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                autoFocus
                required
              />
            </div>
            {error && <ErrorBanner message={error} />}
            <Button type="submit" className="w-full" disabled={loading || !key.trim()}>
              {loading ? "Validating…" : "Sign in"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Create a key with <code className="rounded bg-muted px-1">python -m app.cli create-api-key --scope admin</code>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
