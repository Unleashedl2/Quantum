import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api, setCsrf } from "./api";
import { Me } from "./types";

interface Ctx { me: Me | null; loading: boolean; login(email: string, password: string): Promise<Me>; logout(): Promise<void>; refresh(): Promise<void>; can(p: string): boolean }
const AuthCtx = createContext<Ctx>(null!);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const apply = (m: Me | null) => { setMe(m); setCsrf(m?.csrf_token ?? ""); };
  const refresh = async () => { try { apply(await api<Me>("/api/auth/me")); } catch { apply(null); } };
  useEffect(() => { refresh().finally(() => setLoading(false)); }, []);
  const login = async (email: string, password: string) => { const m = await api<Me>("/api/auth/login", { method: "POST", body: { email, password } }); apply(m); return m; };
  const logout = async () => { try { await api("/api/auth/logout", { method: "POST" }); } finally { apply(null); } };
  const can = (p: string) => !!me && me.permissions.includes(p) && !me.must_change_password;
  return <AuthCtx.Provider value={{ me, loading, login, logout, refresh, can }}>{children}</AuthCtx.Provider>;
}
