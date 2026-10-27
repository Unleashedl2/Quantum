import { FormEvent, useEffect, useState } from "react";
import { api, usd } from "../api";
import { Bank, PaymentInfo } from "../types";

function BankInput({ label, banks, value, onChange, required }: { label: string; banks: Bank[]; value: number | null; onChange: (id: number | null) => void; required?: boolean }) {
  const text = (b: Bank) => `${b.code} - ${b.name}`;
  const [t, setT] = useState("");
  useEffect(() => { const b = banks.find(x => x.id === value); setT(b ? text(b) : ""); }, [value, banks]);
  const id = `dl-${label.replace(/\W/g, "")}`;
  return (<label>{label}
    <input list={id} value={t} required={required} placeholder="Escribe para buscar…" onChange={e => { setT(e.target.value); onChange(banks.find(b => text(b) === e.target.value)?.id ?? null); }} />
    <datalist id={id}>{banks.map(b => <option key={b.id} value={text(b)} />)}</datalist></label>);
}

const STATUS_MSG: Record<string, string> = { declared: "Pago declarado. Un administrador lo verificará; declararlo no significa que ya esté aprobado.", pending_review: "Tu pago está siendo revisado por un administrador.", approved: "¡Pago aprobado!" };

export default function PaymentSection({ number, orderStatus, onChange }: { number: string; orderStatus: string; onChange: () => void }) {
  const [info, setInfo] = useState<PaymentInfo | null>(null);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ origin: null as number | null, receiving: null as number | null, reference: "", paid_at: "", amount: "", cash_modality: "advance_paid", network: "", tx_hash: "", note: "" });
  const load = () => api<PaymentInfo>(`/api/orders/${number}/payment`).then(setInfo).catch(e => setErr((e as Error).message));
  useEffect(() => { load(); api<Bank[]>("/api/banks").then(setBanks).catch(() => setBanks([])); }, [number]);   // eslint-disable-line
  if (!info) return err ? <p className="err" role="alert">{err}</p> : <p className="muted">Cargando pago…</p>;
  const m = info.method; const p = info.payment;
  const canForm = !p || p.status === "rejected" || p.status === "needs_info";
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setErr(null); setOk(null);
    const body = { origin_bank_id: f.origin, receiving_bank_id: f.receiving, reference: f.reference || null, paid_at: f.paid_at || null,
      amount: f.amount || "0", cash_modality: m?.code === "cash" ? f.cash_modality : null, network: f.network || null, tx_hash: f.tx_hash || null, note: f.note || null };
    try { await api(`/api/orders/${number}/payment`, { method: p?.status === "needs_info" ? "PUT" : "POST", body }); await load(); onChange(); setOk("Pago registrado"); }
    catch (x) { setErr((x as Error).message); } finally { setBusy(false); } };

  const upload = async (file?: File) => { if (!file) return; setBusy(true); setErr(null); setOk(null);
    const fd = new FormData(); fd.append("file", file);
    try { await api(`/api/orders/${number}/payment/proof`, { method: "POST", form: fd }); await load(); setOk("Comprobante adjuntado"); }
    catch (x) { setErr((x as Error).message); } finally { setBusy(false); } };

  return (<div className="panel"><h2>Pago</h2>
    {m && <p className="muted">Método: <b>{m.name}</b> · Importe del pedido: <b>{usd(info.amount_due_usd)}</b></p>}
    {p && <p className={p.status === "approved" ? "okmsg" : p.status === "rejected" || p.status === "needs_info" ? "err" : ""} role="status">
      {STATUS_MSG[p.status] ?? ""}{p.status === "rejected" && `Pago rechazado. Motivo: ${p.reason}. Puedes declarar un nuevo pago.`}{p.status === "needs_info" && `Necesitamos más información: ${p.reason}`}</p>}
    {p && ["declared", "pending_review", "needs_info"].includes(p.status) && <label className="btn ghost filebtn">{p.has_proof ? "Reemplazar comprobante" : "Adjuntar comprobante (opcional)"}
      <input type="file" hidden accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e => { upload(e.target.files?.[0]); e.target.value = ""; }} /></label>}
    {canForm && m && orderStatus !== "cancelled" && <>
      {m.instructions && <p>{m.instructions}</p>}
      {m.accounts.length > 0 && <div className="accts">{m.accounts.map((a, i) => <p key={i}><b>{a.bank}</b> · {a.holder}<br />{a.number}{a.document ? ` · ${a.document}` : ""}</p>)}</div>}
      {m.code === "usdt" && m.usdt_address && <p>Dirección receptora: <code>{m.usdt_address}</code><br /><small className="muted">Envía solo por una de estas redes: {m.networks.join(", ")}</small></p>}
      <form className="form inner" onSubmit={submit}>
        {(m.code === "bank_transfer" || m.code === "mobile_payment") && <>
          <BankInput label={m.code === "bank_transfer" ? "Banco de origen" : "Banco emisor"} banks={banks} value={f.origin} onChange={id => setF(s => ({ ...s, origin: id }))} required />
          <BankInput label={m.code === "bank_transfer" ? "Banco receptor (opcional)" : "Banco receptor"} banks={banks} value={f.receiving} onChange={id => setF(s => ({ ...s, receiving: id }))} required={m.code === "mobile_payment"} />
          <label>Número de referencia<input value={f.reference} onChange={set("reference")} required pattern="[A-Za-z0-9\-]{4,40}" /></label>
          <label>Fecha del pago<input type="date" value={f.paid_at} onChange={set("paid_at")} required max={new Date().toISOString().slice(0, 10)} /></label>
          <label>Importe pagado (USD)<input type="number" step="0.01" min="0.01" value={f.amount} onChange={set("amount")} required /></label></>}
        {m.code === "cash" && <>
          <label>Modalidad<select value={f.cash_modality} onChange={set("cash_modality")}><option value="advance_paid">Efectivo ya entregado / depositado</option><option value="on_delivery">Pagaré al recibir el pedido</option></select></label>
          {f.cash_modality === "advance_paid" && <label>Importe entregado (USD)<input type="number" step="0.01" min="0.01" value={f.amount} onChange={set("amount")} required /></label>}</>}
        {m.code === "usdt" && <>
          <label>Red utilizada<select value={f.network} onChange={set("network")} required><option value="">Selecciona…</option>{m.networks.map(n => <option key={n}>{n}</option>)}</select></label>
          <label>Cantidad enviada (USDT)<input type="number" step="0.000001" min="0.000001" value={f.amount} onChange={set("amount")} required /></label>
          <label>Hash de la transacción<input value={f.tx_hash} onChange={set("tx_hash")} required pattern="(0x)?[A-Fa-f0-9]{64}" /></label></>}
        <label>Comentario (opcional)<textarea value={f.note} onChange={set("note")} maxLength={500} rows={2} /></label>
        <button className="btn" disabled={busy}>{busy ? "Enviando…" : p?.status === "needs_info" ? "Enviar información" : "Declarar pago"}</button>
      </form></>}
    {ok && <p className="okmsg" role="status">{ok}</p>}{err && <p className="err" role="alert">{err}</p>}
  </div>);
}
