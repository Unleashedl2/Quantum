import { FormEvent, useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { fmtDate } from "../types";

interface BankRow { id: number; code: string; name: string; is_active: boolean; verified_at: string | null; source_note: string | null }
interface MethodRow { id: number; code: string; name: string; is_active: boolean; instructions: string | null; config: { accounts?: { bank: string; holder: string; number: string; document?: string | null }[]; address?: string | null; networks?: Record<string, { min_confirmations: number }> } }

function MethodEditor({ m, onSaved, onError }: { m: MethodRow; onSaved: () => void; onError: (t: string) => void }) {
  const [active, setActive] = useState(m.is_active);
  const [ins, setIns] = useState(m.instructions ?? "");
  const [accts, setAccts] = useState((m.config.accounts ?? []).map(a => [a.bank, a.holder, a.number, a.document ?? ""].join(" | ")).join("\n"));
  const [addr, setAddr] = useState(m.config.address ?? "");
  const [nets, setNets] = useState(Object.entries(m.config.networks ?? {}).map(([k, v]) => `${k}:${v.min_confirmations}`).join(", "));
  const save = async () => {
    const accounts = accts.split("\n").map(l => l.trim()).filter(Boolean).map(l => { const [bank, holder, number, document] = l.split("|").map(x => x.trim()); return { bank, holder, number, document: document || null }; });
    const networks: Record<string, { min_confirmations: number }> = {};
    nets.split(",").map(x => x.trim()).filter(Boolean).forEach(x => { const [k, v] = x.split(":"); networks[k.trim().toUpperCase()] = { min_confirmations: Number(v) || 20 }; });
    try { await api(`/api/admin/payment-methods/${m.id}`, { method: "PUT", body: { is_active: active, instructions: ins, config: { accounts, address: addr || null, networks } } }); onSaved(); }
    catch (e) { onError((e as Error).message); }
  };
  return (<div className="panel"><h3>{m.name}</h3>
    <label className="chk"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} /> Habilitado para los clientes</label>
    <label>Instrucciones para el cliente<textarea rows={2} value={ins} onChange={e => setIns(e.target.value)} maxLength={2000} /></label>
    {(m.code === "bank_transfer" || m.code === "mobile_payment") && <label>Cuentas receptoras (una por línea: Banco | Titular | Cuenta o teléfono | Documento)<textarea rows={3} value={accts} onChange={e => setAccts(e.target.value)} /></label>}
    {m.code === "usdt" && <><label>Dirección receptora<input value={addr} onChange={e => setAddr(e.target.value)} /></label>
      <label>Redes y confirmaciones mínimas (ej.: TRC20:20, ERC20:12)<input value={nets} onChange={e => setNets(e.target.value)} /></label></>}
    <button className="btn" onClick={save}>Guardar</button></div>);
}

export default function AdminBanks() {
  const { can, loading } = useAuth();
  const [q, setQ] = useState("");
  const [banks, setBanks] = useState<BankRow[]>([]);
  const [methods, setMethods] = useState<MethodRow[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const load = useCallback(async () => {
    try {
      setBanks(await api<BankRow[]>(`/api/admin/banks?q=${encodeURIComponent(q)}`));
      if (can("settings.general")) setMethods(await api<MethodRow[]>("/api/admin/payment-methods"));
    } catch (e) { setMsg({ ok: false, t: (e as Error).message }); }
  }, [q, can]);
  useEffect(() => { if (can("banks.manage")) load(); }, [load, can]);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!can("banks.manage")) return <Navigate to="/" replace />;
  const run = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, t: ok }); await load(); } catch (e) { setMsg({ ok: false, t: (e as Error).message }); } };
  const add = (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); const form = e.currentTarget;
    run(async () => { await api("/api/admin/banks", { method: "POST", body: { code: f.get("code"), name: f.get("name"), source_note: f.get("note") || null } }); form.reset(); }, "Banco creado"); };
  return (<div><h1>Bancos y métodos de pago</h1>
    {msg && <p className={msg.ok ? "okmsg" : "err"} role="status">{msg.t}</p>}
    <p className="muted">La carga inicial de bancos debe contrastarse con el listado vigente de SUDEBAN. Marca «Verificado» cuando lo hayas hecho.</p>
    <form className="form inner" onSubmit={add}><h2>Nuevo banco</h2>
      <label>Código (4 dígitos)<input name="code" required pattern="\d{4}" /></label><label>Nombre<input name="name" required minLength={3} /></label>
      <label>Fuente / nota (opcional)<input name="note" /></label><button className="btn">Añadir</button></form>
    <div className="sech"><h2>Bancos</h2><input placeholder="Buscar por nombre o código…" value={q} onChange={e => setQ(e.target.value)} aria-label="Buscar" /></div>
    <div className="scroll"><table className="tbl"><thead><tr><th>Código</th><th>Nombre</th><th>Activo</th><th>Verificación</th><th>Acciones</th></tr></thead>
      <tbody>{banks.map(b => <tr key={b.id}><td>{b.code}</td><td>{b.name}</td><td>{b.is_active ? "Sí" : "No"}</td><td>{b.verified_at ? `Verificado ${fmtDate(b.verified_at)}` : "Sin verificar"}</td>
        <td className="acts"><button className="btn ghost" onClick={() => run(() => api(`/api/admin/banks/${b.id}`, { method: "PATCH", body: { is_active: !b.is_active } }), "Banco actualizado")}>{b.is_active ? "Desactivar" : "Activar"}</button>
          {!b.verified_at && <button className="btn ghost" onClick={() => run(() => api(`/api/admin/banks/${b.id}/verify`, { method: "POST" }), "Banco verificado")}>Marcar verificado</button>}
          <button className="btn ghost" onClick={() => { const n = window.prompt("Nuevo nombre del banco:", b.name); if (n && n.trim().length >= 3) run(() => api(`/api/admin/banks/${b.id}`, { method: "PATCH", body: { name: n.trim() } }), "Nombre actualizado"); }}>Renombrar</button></td></tr>)}</tbody></table></div>
    {can("settings.general") && <><h2>Métodos de pago</h2>{methods.map(m => <MethodEditor key={m.id + String(m.is_active)} m={m} onSaved={() => { setMsg({ ok: true, t: "Método guardado" }); load(); }} onError={t => setMsg({ ok: false, t })} />)}</>}
  </div>);
}
