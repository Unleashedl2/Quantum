import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { api, usd } from "../api";
import { useAuth } from "../auth";
import { useFetch } from "../hooks";
import PaymentSection from "../components/PaymentSection";
import { fmtDate, OrderT, STATUS_LABEL } from "../types";

export function OrdersList() {
  const { me, loading } = useAuth();
  const [page, setPage] = useState(1);
  const { data, loading: l2, error } = useFetch<{ items: OrderT[]; total: number; page_size: number }>(me ? `/api/orders?page=${page}` : null);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!me) return <Navigate to="/ingresar" replace />;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (<div><h1>Mis pedidos</h1>
    {l2 && <p className="muted">Cargando…</p>}{error && <p className="err" role="alert">{error}</p>}
    {data && data.items.length === 0 && <p>Aún no tienes pedidos. <Link to="/productos">Explora el catálogo</Link>.</p>}
    <div className="scroll">{data && data.items.length > 0 && <table className="tbl"><thead><tr><th>Pedido</th><th>Fecha</th><th>Artículos</th><th>Total</th><th>Estado</th></tr></thead>
      <tbody>{data.items.map(o => <tr key={o.id}><td><Link to={`/pedidos/${o.number}`}>{o.number}</Link></td><td>{fmtDate(o.created_at)}</td><td>{o.item_count}</td><td>{usd(o.total_usd)}</td><td>{STATUS_LABEL[o.status] ?? o.status}</td></tr>)}</tbody></table>}</div>
    {pages > 1 && <nav className="pager"><button className="btn ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button><span>Página {page} de {pages}</span><button className="btn ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>Siguiente</button></nav>}
  </div>);
}

export function OrderDetail() {
  const { number } = useParams();
  const { me, loading } = useAuth();
  const [tick, setTick] = useState(0);
  const { data, loading: l2, error } = useFetch<OrderT>(me ? `/api/orders/${number}?t=${tick}` : null);
  const [o, setO] = useState<OrderT | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!me) return <Navigate to="/ingresar" replace />;
  if (l2 && !data) return <p className="muted">Cargando…</p>;
  const order = o ?? data;
  if (error || !order) return <div><p className="err" role="alert">{error ?? "Pedido no encontrado"}</p><Link to="/pedidos">Volver a mis pedidos</Link></div>;
  const cancel = async () => { if (!window.confirm("¿Cancelar este pedido? Se liberará el inventario reservado.")) return; setErr(null);
    try { setO(await api<OrderT>(`/api/orders/${order.number}/cancel`, { method: "POST" })); } catch (e) { setErr((e as Error).message); } };
  return (<div>
    <p className="muted"><Link to="/pedidos">← Mis pedidos</Link></p>
    <h1>Pedido {order.number}</h1>
    <p><span className="tag in">{STATUS_LABEL[order.status] ?? order.status}</span> · {fmtDate(order.created_at)}</p>
    {["pending_payment", "payment_validation", "preparing", "shipped", "out_for_delivery", "delivered"].includes(order.status) &&
      <PaymentSection number={order.number} orderStatus={order.status} onChange={() => { setO(null); setTick(t => t + 1); }} />}
    {order.status === "pending_payment" && <div className="panel">
      <p className="muted">Tu inventario queda reservado{order.reservation_expires_at ? ` hasta el ${fmtDate(order.reservation_expires_at)}` : ""}; si no declaras un pago antes, el pedido se cancela automáticamente.</p>
      <button className="btn ghost" onClick={cancel}>Cancelar pedido</button></div>}
    {err && <p className="err" role="alert">{err}</p>}
    <div className="two">
      <div className="panel"><h2>Productos</h2>
        {order.items?.map((i, k) => <p key={k} className="sumrow"><span>{i.quantity} × {i.product_name}{i.variant ? ` (${Object.values(i.variant).join(" / ")})` : ""}<br /><small className="muted">SKU {i.sku} · {usd(i.unit_price_usd)} c/u</small></span><b>{usd(i.line_total_usd)}</b></p>)}
        <hr /><p className="sumrow"><span>Subtotal</span><b>{usd(order.subtotal_usd)}</b></p>
        <p className="sumrow"><span>Envío</span><b>{Number(order.shipping_usd) === 0 ? "A coordinar" : usd(order.shipping_usd)}</b></p>
        <p className="sumrow total"><span>Total</span><b>{usd(order.total_usd)}</b></p></div>
      <div className="panel"><h2>Entrega</h2>
        <p>{order.shipping?.recipient} · {order.shipping?.phone}<br />{order.shipping?.address}, {order.shipping?.municipality}, {order.shipping?.state}
          {order.shipping?.reference && <><br /><small className="muted">{order.shipping.reference}</small></>}</p>
        <p className="muted">Transportista: {order.shipping?.carrier ?? "—"} · Pago: {order.payment_method ?? "—"}</p>
        <h2>Seguimiento</h2>
        <ul className="tl">{order.events?.map((e, k) => <li key={k} className={k === (order.events?.length ?? 1) - 1 ? "now" : "done"}><i /><div><b>{STATUS_LABEL[e.status] ?? e.status}</b><br /><small className="muted">{fmtDate(e.at)}{e.note ? ` — ${e.note}` : ""}</small></div></li>)}</ul></div>
    </div></div>);
}
