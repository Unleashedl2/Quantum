import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useCart } from "../cart";
import { usd } from "../api";
import { ProductCardT } from "../types";

export default function ProductCard({ p }: { p: ProductCardT }) {
  const { me } = useAuth(); const { add } = useCart(); const nav = useNavigate();
  const [msg, setMsg] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const quickAdd = async () => {
    if (!me) return nav("/ingresar");
    setBusy(true); setMsg(null);
    try { await add(p.id, null, 1); setMsg("Añadido al carrito"); }
    catch (e) { const m = (e as Error).message; if (m.toLowerCase().includes("variante")) nav(`/producto/${p.slug}`); else setMsg(m); }
    finally { setBusy(false); }
  };
  const sale = p.sale_price_usd !== null;
  const tag = !p.in_stock ? <span className="tag out">Agotado</span> : p.available < 5 ? <span className="tag low">Quedan {p.available}</span> : <span className="tag in">Disponible</span>;
  return (
    <article className="card">
      <Link to={`/producto/${p.slug}`} className="imgbox">
        {p.image_url ? <img src={p.image_url} alt={p.name} loading="lazy" decoding="async" /> : <span className="noimg" aria-hidden>🛍️</span>}
      </Link>
      <div className="cbody">
        <Link to={`/producto/${p.slug}`} className="name">{p.name}</Link>
        {p.brand && <small className="muted">{p.brand}</small>}
        <div className="price">{usd(p.effective_price_usd)}{sale && <span className="old">{usd(p.price_usd)}</span>}</div>
        {tag}
        <div className="row">
          <Link className="btn ghost" to={`/producto/${p.slug}`}>Ver producto</Link>
          <button className="btn" disabled={!p.in_stock || busy} onClick={quickAdd}>＋ Carrito</button>
        </div>
        {msg && <small className="muted" role="status">{msg}</small>}
      </div>
    </article>
  );
}
