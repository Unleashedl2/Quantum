import { ChangeEvent, FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

function Err({ msg }: { msg: string | null }) { return msg ? <p className="err" role="alert">{msg}</p> : null; }

export function Login() {
  const { login } = useAuth(); const nav = useNavigate();
  const [email, setEmail] = useState(""); const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setErr(null);
    try { await login(email, pw); nav("/"); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); } };
  return (<form className="form" onSubmit={submit}><h1>Ingresar</h1>
    <label>Correo<input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" /></label>
    <label>Contraseña<input type="password" value={pw} onChange={e => setPw(e.target.value)} required autoComplete="current-password" /></label>
    <Err msg={err} /><button className="btn" disabled={busy}>{busy ? "Ingresando…" : "Ingresar"}</button>
    <p><Link to="/registro">Crear cuenta</Link></p></form>);
}

export function Register() {
  const nav = useNavigate();
  const [f, setF] = useState({ first_name: "", last_name: "", national_id: "", state: "", municipality: "", address: "", phone: "", email: "", password: "", password_confirm: "", accept_terms: false });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false); const [done, setDone] = useState(false);
  const up = (k: string) => (e: ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setErr(null);
    try { await api("/api/auth/register", { method: "POST", body: f }); setDone(true); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); } };
  if (done) return <div className="form"><h1>¡Cuenta creada!</h1><p>Ya puedes ingresar. La verificación de correo se enviará cuando se configure el servidor SMTP.</p><button className="btn" onClick={() => nav("/ingresar")}>Ingresar</button></div>;
  const F = (k: keyof typeof f & string, label: string, type = "text", extra: object = {}) => <label>{label}<input type={type} value={String(f[k])} onChange={up(k)} required {...extra} /></label>;
  return (<form className="form" onSubmit={submit}><h1>Crear cuenta</h1>
    {F("first_name", "Nombres")}{F("last_name", "Apellidos")}
    {F("national_id", "Cédula (ej. V12345678)", "text", { pattern: "[VEve]?-?\\d{5,9}" })}
    {F("state", "Estado de residencia")}{F("municipality", "Municipio")}{F("address", "Dirección residencial")}
    {F("phone", "Teléfono (ej. +584121234567)", "tel", { pattern: "\\+?\\d{10,15}" })}
    {F("email", "Correo electrónico", "email", { autoComplete: "email" })}
    {F("password", "Contraseña (mín. 12, mayúsculas, minúsculas, número y símbolo)", "password", { autoComplete: "new-password" })}
    {F("password_confirm", "Confirmar contraseña", "password", { autoComplete: "new-password" })}
    <label className="chk"><input type="checkbox" checked={f.accept_terms} onChange={up("accept_terms")} required /> Acepto las condiciones de compra y la política de privacidad</label>
    <Err msg={err} /><button className="btn" disabled={busy}>{busy ? "Creando…" : "Crear cuenta"}</button></form>);
}

export function ChangePassword({ forced = false }: { forced?: boolean }) {
  const { refresh, logout } = useAuth(); const nav = useNavigate();
  const [cur, setCur] = useState(""); const [nw, setNw] = useState(""); const [nw2, setNw2] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => { e.preventDefault(); setErr(null);
    if (nw !== nw2) return setErr("Las contraseñas nuevas no coinciden");
    setBusy(true);
    try { await api("/api/auth/change-password", { method: "POST", body: { current_password: cur, new_password: nw } }); await refresh(); nav("/"); }
    catch (x) { setErr((x as Error).message); } finally { setBusy(false); } };
  return (<form className="form" onSubmit={submit}><h1>{forced ? "Debes cambiar tu contraseña temporal" : "Cambiar contraseña"}</h1>
    {forced && <p>Por seguridad, define una contraseña nueva y robusta antes de continuar.</p>}
    <label>Contraseña actual<input type="password" value={cur} onChange={e => setCur(e.target.value)} required autoComplete="current-password" /></label>
    <label>Nueva contraseña<input type="password" value={nw} onChange={e => setNw(e.target.value)} required autoComplete="new-password" /></label>
    <label>Confirmar nueva contraseña<input type="password" value={nw2} onChange={e => setNw2(e.target.value)} required autoComplete="new-password" /></label>
    <Err msg={err} /><button className="btn" disabled={busy}>{busy ? "Guardando…" : "Guardar"}</button>
    {forced && <button type="button" className="btn ghost" onClick={() => logout()}>Salir</button>}</form>);
}
