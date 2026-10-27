import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, usd } from "../api";
import { useAuth } from "../auth";
import { AdminPaymentDetail, AdminPaymentRow, FLAG_LABEL, fmtDate, PAY_LABEL } from "../types";

export default function AdminPayments() {
  const { can, loading } = useAuth();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<{ items: AdminPaymentRow[]; total: number; page_size: number } | null>(null);
  const [sel, setSel] = useState<AdminPaymentDetail | null>(null);
  const [note, setNote] = useState(""); const [verified, setVerified] = useState(""); const [conf, setConf] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const loadList = useCallback(async () => {
    try { setRows(await api(`/api/admin/payments?page=${page}&q=${encodeURIComponent(q)}${status ? `&status=${status}` : ""}`)); }
    catch (e) { setMsg({ ok: false, t: (e as Error).message }); }
  }, [page, q, status]);
  useEffect(() => { if (can("payments.review")) loadList(); }, [loadList, can]);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!can("payments.review")) return <Navigate to="/" replace />;

  const open = async (id: number) => { setMsg(null); setNote(""); setVerified(""); setConf(""); setSel(await api<AdminPaymentDetail>(`/api/admin/payments/${id}`)); };
  const act = async (action: string) => {
    if (!sel) return; setBusy(true); setMsg(null);
    try {
      await api(`/api/admin/payments/${sel.id}/review`, { method: "POST", body: { action, note: note || null, verified_with: verified || null, confirmations: conf === "" ? null : Number(conf) } });
      setMsg({ ok: true, t: "Acción registrada" }); await open(sel.id); await loadList();
    } catch (e) { setMsg({ ok: false, t: (e as Error).message }); } finally { setBusy(false); }
  };
  const prepare = async () => { if (!sel) return; setBusy(true);
    try { await api(`/api/admin/orders/${sel.order_number}/prepare`, { method: "POST" }); setMsg({ ok: true, t: "Pedido en preparación" }); await open(sel.id); }
    catch (e) { setMsg({ ok: false, t: (e as Error).message }); } finally { setBusy(false); } };
  const pages = rows ? Math.max(1, Math.ceil(rows.total / rows.page_size)) : 1;
  const reviewable = sel && ["declared", "pending_review"].includes(sel.status);

  return (<div><h1>Centro de validación de pagos</h1>
    <div className="sech"><div className="acts">{["", "declared", "pending_review", "needs_info", "approved", "rejected"].map(s =>
      <button key={s} className={`btn ${status === s ? "" : "ghost"}`} onClick={() => { setStatus(s); setPage(1); }}>{s ? PAY_LABEL[s] : "Todos"}</button>)}</div>
      <input placeholder="Pedido, referencia o cliente…" value={q} onChange={e => { setQ(e.target.value); setPage(1); }} aria-label="Buscar" /></div>
    {msg && !sel && <p className={msg.ok ? "okmsg" : "err"} role="status">{msg.t}</p>}
    <div className="scroll"><table className="tbl"><thead><tr><th>Pedido</th><th>Fecha</th><th>Cliente</th><th>Productos</th><th>Total</th><th>Método</th><th>Bancos</th><th>Referencia</th><th>Estado</th></tr></thead>
      <tbody>{rows?.items.map(r => <tr key={r.id} className="click" onClick={() => open(r.id)}>
        <td><b>{r.order_number}</b></td><td>{fmtDate(r.created_at)}</td><td>{r.customer}</td><td>{r.products.join(", ")}</td><td>{usd(r.order_total_usd)}</td>
        <td>{r.method}</td><td>{[r.origin_bank, r.receiving_bank].filter(Boolean).join(" → ") || "—"}</td><td>{r.reference ?? "—"}{r.has_proof && " 📎"}</td>
        <td><span className="st">{PAY_LABEL[r.status]}</span>{r.flags.length > 0 && <span title={r.flags.map(f => FLAG_LABEL[f] ?? f).join("\n")}> ⚠</span>}</td></tr>)}</tbody></table></div>
    {rows && rows.items.length === 0 && <p className="muted">No hay pagos con ese filtro.</p>}
    {pages > 1 && <nav className="pager"><button className="btn ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button><span>Página {page} de {pages}</span><button className="btn ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>Siguiente</button></nav>}

    {sel && <div className="panel"><div className="sech"><h2>Pedido {sel.order_number} · {PAY_LABEL[sel.status]}</h2><button className="btn ghost" onClick={() => setSel(null)}>Cerrar</button></div>
      <div className="two"><div>
        <p><b>{sel.customer.name}</b> · {sel.customer.phone ?? "sin teléfono"} · {sel.customer.email}</p>
        <p>{sel.method} · Declarado: <b>{usd(sel.declared_usd)}</b> de <b>{usd(sel.order_total_usd)}</b> · Ref: <b>{sel.reference ?? "—"}</b>{sel.paid_at && ` · Fecha del pago: ${fmtDate(sel.paid_at)}`}</p>
        {sel.details && ((sel.details.flags as string[] | undefined) ?? []).map(f => <p key={f} className="err" role="alert">⚠ {FLAG_LABEL[f] ?? f}{f === "duplicate_reference" && sel.details?.duplicate_of_orders ? `: ${(sel.details.duplicate_of_orders as string[]).join(", ")}` : ""}</p>)}
        {sel.details?.network != null && <p>Red: {String(sel.details.network)} · Hash: <code>{String(sel.details.tx_hash)}</code> · Mínimo de confirmaciones: {sel.min_confirmations}</p>}
        {sel.details?.cash_modality != null && <p>Efectivo: {String(sel.details.cash_modality) === "on_delivery" ? "pagará al recibir (aún no cobrado)" : "entregado"}</p>}
        {sel.details?.customer_note != null && <p className="muted">Comentario del cliente: {String(sel.details.customer_note)}</p>}
        {sel.proof_url ? <p><a href={sel.proof_url} target="_blank" rel="noopener noreferrer">Ver comprobante</a> <small className="muted">(enlace temporal)</small></p> : <p className="muted">Sin comprobante.</p>}
        <p className="muted">Una referencia o una captura no prueban que el dinero llegó. Verifica en el banco o en el explorador de la red antes de aprobar.</p>
      </div><div>
        <h3>Historial de validación</h3>
        <ul className="tl">{sel.events.map((e, i) => <li key={i} className="done"><i /><div><b>{e.action}</b> {e.actor && <small>· {e.actor}</small>}<br /><small className="muted">{fmtDate(e.at)}{e.note ? ` — ${e.note}` : ""}</small></div></li>)}</ul>
      </div></div>
      {(reviewable || sel.status === "needs_info") && <div className="form inner">
        <label>Observación / motivo<textarea rows={2} value={note} onChange={e => setNote(e.target.value)} maxLength={1000} /></label>
        {reviewable && <><label>Medio de verificación (obligatorio para aprobar)<input value={verified} onChange={e => setVerified(e.target.value)} placeholder="Ej.: estado de cuenta Banesco 26/10" /></label>
          {sel.method_code === "usdt" && <label>Confirmaciones observadas en la red (mín. {sel.min_confirmations})<input type="number" min="0" value={conf} onChange={e => setConf(e.target.value)} /></label>}</>}
        <div className="acts">
          {sel.status === "declared" && <button className="btn ghost" disabled={busy} onClick={() => act("start_review")}>Tomar para revisión</button>}
          {reviewable && <button className="btn" disabled={busy} onClick={() => act("approve")}>Aprobar pago</button>}
          <button className="btn ghost" disabled={busy} onClick={() => act("reject")}>Rechazar</button>
          {reviewable && <button className="btn ghost" disabled={busy} onClick={() => act("request_info")}>Solicitar información</button>}
          <button className="btn ghost" disabled={busy} onClick={() => act("note")}>Solo añadir observación</button></div></div>}
      {sel.status === "approved" && sel.order_status === "payment_validation" && can("shipping.manage") && <button className="btn" disabled={busy} onClick={prepare}>Pasar pedido a preparación</button>}
      {msg && <p className={msg.ok ? "okmsg" : "err"} role="status">{msg.t}</p>}</div>}
  </div>);
}
