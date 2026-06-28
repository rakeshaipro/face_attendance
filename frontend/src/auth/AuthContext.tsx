import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { clearApiKey, getApiKey, registerUnauthorizedHandler, setApiKey } from "@/lib/api";

interface AuthState {
  apiKey: string | null;
  login: (key: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKeyState] = useState<string | null>(() => getApiKey());

  const logout = useCallback(() => {
    clearApiKey();
    setApiKeyState(null);
  }, []);

  // Force-logout on any 401 from the API layer.
  useEffect(() => {
    registerUnauthorizedHandler(logout);
  }, [logout]);

  const login = useCallback((key: string) => {
    setApiKey(key);
    setApiKeyState(key);
  }, []);

  const value = useMemo(() => ({ apiKey, login, logout }), [apiKey, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
