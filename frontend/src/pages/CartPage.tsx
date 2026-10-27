import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { usd } from "../api";
import { useAuth } from "../auth";
import { useCart } from "../cart";

const ISSUE: Record<string, string> = { unavailable: "Este producto ya no está disponible", out_of_stock: "Agotado", insufficient_stock: "No hay stock suficiente para esta cantidad" };

export default function CartPage() {
  const { me, loading } = useAuth();
  const { cart, setQty, refresh } = useCart();
  const [err, setErr] = useState<string | null>(null);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!me) return <Navigate to="/ingresar" replace />;
  const change = async (id: number, q: number) => { setErr(null); try { await setQty(id, q); } catch (e) { setErr((e as Error).message); refresh(); } };
  if (!cart) return <p className="muted">Cargando carrito…</p>;
  if (cart.items.length === 0) return <div className="panel"><h1>Tu carrito está vacío</h1><Link className="btn" to="/productos">Ver productos</Link></div>;
  return (<div className="two cartgrid">
    <section>
      <h1>Carrito</h1>
      {err && <p className="err" role="alert">{err}</p>}
      {cart.items.map(l => (
        <article key={l.id} className={`line ${l.issue ? "bad" : ""}`}>
          <div className="thumb">{l.image_url ? <img src={l.image_url} alt="" loading="lazy" /> : <span aria-hidden>🛍️</span>}</div>
          <div className="info">
            {l.slug ? <Link to={`/producto/${l.slug}`}>{l.name}</Link> : <b>{l.name}</b>}
            {l.variant_label && <small className="muted">{l.variant_label}</small>}
            <small className="muted">{usd(l.unit_price_usd)} c/u</small>
            {l.issue && <small className="err" role="alert">{ISSUE[l.issue]}{l.available > 0 ? ` (máx. ${l.available})` : ""}</small>}
          </div>
          <div className="qty">
            <button className="btn ghost" onClick={() => change(l.id, l.quantity - 1)} aria-label="Disminuir">−</button>
            <b>{l.quantity}</b>
            <button className="btn ghost" disabled={l.quantity >= l.available} onClick={() => change(l.id, l.quantity + 1)} aria-label="Aumentar">+</button>
          </div>
          <b className="lt">{usd(l.line_total_usd)}</b>
          <button className="link" onClick={() => change(l.id, 0)}>Quitar</button>
        </article>))}
    </section>
    <aside className="panel sticky">
      <h2>Resumen</h2>
      <p className="sumrow"><span>Subtotal ({cart.item_count} {cart.item_count === 1 ? "artículo" : "artículos"})</span><b>{usd(cart.subtotal_usd)}</b></p>
      <p className="muted">El envío y el total final se calculan en el checkout.</p>
      {cart.has_issues && <p className="err" role="alert">Resuelve los avisos en rojo para continuar.</p>}
      <Link className={`btn ${cart.has_issues ? "disabled" : ""}`} to="/checkout" aria-disabled={cart.has_issues} onClick={e => cart.has_issues && e.preventDefault()}>Continuar con la compra</Link>
    </aside>
  </div>);
}
