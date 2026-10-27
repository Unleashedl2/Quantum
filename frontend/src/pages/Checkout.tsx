import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, usd } from "../api";
import { useAuth } from "../auth";
import { useCart } from "../cart";
import { Address, Method, OrderT, Summary } from "../types";

const EMPTY = { recipient_name: "", phone: "", state: "", municipality: "", full_address: "", reference: "" };

export default function Checkout() {
  const { me, loading } = useAuth();
  const { cart, refresh } = useCart();
  const nav = useNavigate();
  const [addrs, setAddrs] = useState<Address[]>([]);
  const [ships, setShips] = useState<Method[]>([]);
  const [pays, setPays] = useState<Method[]>([]);
  const [addrId, setAddrId] = useState<number | null>(null);
  const [shipId, setShipId] = useState<number | null>(null);
  const [payId, setPayId] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [newAddr, setNewAddr] = useState(EMPTY);
  const [showNew, setShowNew] = useState(false);
  const [sum, setSum] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const idemKey = useRef(crypto.randomUUID());   // misma clave si el cliente pulsa dos veces

  useEffect(() => {
    if (!me) return;
    Promise.all([api<Address[]>("/api/me/addresses"), api<Method[]>("/api/shipping-methods"), api<Method[]>("/api/payment-methods")])
      .then(([a, s, p]) => { setAddrs(a); setShips(s); setPays(p); setAddrId((a.find(x => x.is_default) ?? a[0])?.id ?? null); setShowNew(a.length === 0); })
      .catch(e => setErr((e as Error).message));
  }, [me]);

  const ready = addrId && shipId && payId;
  useEffect(() => {
    if (!ready) { setSum(null); return; }
    api<Summary>("/api/checkout/summary", { method: "POST", body: { address_id: addrId, shipping_method_id: shipId, payment_method_id: payId } })
      .then(s => { setSum(s); setErr(null); }).catch(e => { setSum(null); setErr((e as Error).message); });
  }, [ready, addrId, shipId, payId, cart]);

  const payInfo = useMemo(() => pays.find(p => p.id === payId), [pays, payId]);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!me) return <Navigate to="/ingresar" replace />;
  if (cart && cart.items.length === 0) return <div className="panel"><h1>Tu carrito está vacío</h1><Link to="/productos">Ver productos</Link></div>;

  const saveAddr = async (e: FormEvent) => { e.preventDefault(); setErr(null);
    try { const a = await api<Address>("/api/me/addresses", { method: "POST", body: { ...newAddr, reference: newAddr.reference || null } });
      setAddrs([...addrs, a]); setAddrId(a.id); setShowNew(false); setNewAddr(EMPTY); } catch (x) { setErr((x as Error).message); } };

  const confirm = async () => { setBusy(true); setErr(null);
    try {
      const o = await api<OrderT>("/api/orders", { method: "POST", headers: { "Idempotency-Key": idemKey.current },
        body: { address_id: addrId, shipping_method_id: shipId, payment_method_id: payId, delivery_notes: notes || null } });
      await refresh(); nav(`/pedidos/${o.number}`);
    } catch (x) { setErr((x as Error).message); await refresh(); } finally { setBusy(false); } };

  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement>) => setNewAddr({ ...newAddr, [k]: e.target.value });
  return (<div className="two cartgrid">
    <section>
      <h1>Finalizar compra</h1>
      <div className="panel"><h2>1. Dirección de entrega</h2>
        {addrs.map(a => <label key={a.id} className="chk opt"><input type="radio" name="addr" checked={addrId === a.id} onChange={() => setAddrId(a.id)} />
          <span><b>{a.recipient_name}</b> · {a.phone}<br /><small className="muted">{a.full_address}, {a.municipality}, {a.state}</small></span></label>)}
        {!showNew && <button className="link plainlink" onClick={() => setShowNew(true)}>+ Usar otra dirección</button>}
        {showNew && <form className="form inner" onSubmit={saveAddr}>
          <label>Destinatario<input value={newAddr.recipient_name} onChange={set("recipient_name")} required minLength={2} /></label>
          <label>Teléfono<input value={newAddr.phone} onChange={set("phone")} required pattern="\+?\d{10,15}" placeholder="+584121234567" /></label>
          <label>Estado<input value={newAddr.state} onChange={set("state")} required /></label>
          <label>Municipio<input value={newAddr.municipality} onChange={set("municipality")} required /></label>
          <label>Dirección completa<input value={newAddr.full_address} onChange={set("full_address")} required minLength={5} /></label>
          <label>Referencias de ubicación<input value={newAddr.reference} onChange={set("reference")} /></label>
          <button className="btn">Guardar dirección</button></form>}
      </div>
      <div className="panel"><h2>2. Transportista</h2>
        {ships.map(s => <label key={s.id} className="chk opt"><input type="radio" name="ship" checked={shipId === s.id} onChange={() => setShipId(s.id)} /> {s.name}</label>)}
        {ships.length === 0 && <p className="muted">No hay transportistas habilitados.</p>}
        <label>Observaciones para la entrega<input value={notes} onChange={e => setNotes(e.target.value)} maxLength={500} /></label></div>
      <div className="panel"><h2>3. Método de pago</h2>
        {pays.map(p => <label key={p.id} className="chk opt"><input type="radio" name="pay" checked={payId === p.id} onChange={() => setPayId(p.id)} /> {p.name}</label>)}
        {payInfo?.instructions && <p className="muted">{payInfo.instructions}</p>}
        <p className="muted">Después de confirmar verás los datos para pagar. Tu pedido queda pendiente hasta que un administrador valide el pago.</p></div>
    </section>
    <aside className="panel sticky"><h2>Resumen</h2>
      {!sum && <p className="muted">Elige dirección, transportista y método de pago para ver el resumen.</p>}
      {sum && <>
        {sum.items.map(l => <p key={l.id} className="sumrow"><span>{l.quantity} × {l.name}{l.variant_label ? ` (${l.variant_label})` : ""}</span><b>{usd(l.line_total_usd)}</b></p>)}
        <hr /><p className="sumrow"><span>Subtotal</span><b>{usd(sum.subtotal_usd)}</b></p>
        <p className="sumrow"><span>Envío ({sum.shipping_method})</span><b>{Number(sum.shipping_usd) === 0 ? "A coordinar" : usd(sum.shipping_usd)}</b></p>
        <p className="sumrow total"><span>Total</span><b>{usd(sum.total_usd)}</b></p>
        <p className="muted">Entrega a {sum.address.recipient_name}: {sum.address.full_address}, {sum.address.municipality}, {sum.address.state}. Pago: {sum.payment_method}.</p>
        {sum.has_issues && <p className="err" role="alert">Hay productos con problemas. <Link to="/carrito">Revisa tu carrito</Link>.</p>}</>}
      {err && <p className="err" role="alert">{err}</p>}
      <button className="btn" disabled={!sum || sum.has_issues || busy} onClick={confirm}>{busy ? "Procesando…" : "Confirmar pedido"}</button>
    </aside>
  </div>);
}
