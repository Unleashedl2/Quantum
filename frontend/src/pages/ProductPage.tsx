import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../auth";
import { useCart } from "../cart";
import { usd } from "../api";
import ProductCard from "../components/ProductCard";
import { useFetch } from "../hooks";
import { ProductDetail } from "../types";

export default function ProductPage() {
  const { slug } = useParams();
  const { data: p, loading, error } = useFetch<ProductDetail>(`/api/products/${slug}`);
  const [img, setImg] = useState(0);
  const [vid, setVid] = useState<number | null>(null);
  const [qty, setQty] = useState(1);
  const { me } = useAuth(); const { add } = useCart(); const nav = useNavigate();
  const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (loading) return <p className="muted">Cargando…</p>;
  if (error || !p) return <div><p className="err" role="alert">{error ?? "Producto no encontrado"}</p><Link to="/productos">Volver al catálogo</Link></div>;
  const v = p.variants.find(x => x.id === vid) ?? null;
  const price = v ? (v.sale_price_usd ?? v.price_usd) : p.effective_price_usd;
  const old = v ? (v.sale_price_usd ? v.price_usd : null) : p.sale_price_usd ? p.price_usd : null;
  const avail = v ? v.available : p.available;
  const max = Math.max(1, avail);
  const addToCart = async (goCheckout: boolean) => {
    if (!me) return nav("/ingresar");
    if (p.variants.length > 0 && !v) return setMsg({ ok: false, t: "Selecciona una variante" });
    setBusy(true); setMsg(null);
    try { await add(p.id, v ? v.id : null, qty); if (goCheckout) nav("/checkout"); else setMsg({ ok: true, t: "Añadido al carrito" }); }
    catch (e) { setMsg({ ok: false, t: (e as Error).message }); } finally { setBusy(false); }
  };
  return (<>
    <p className="muted"><Link to="/">Inicio</Link> › <Link to={`/productos?category_id=${p.category.id}`}>{p.category.name}</Link></p>
    <div className="two">
      <div>
        <div className="gallery">{p.images[img] ? <img src={p.images[img].url} alt={p.images[img].alt ?? p.name} /> : <span className="noimg big" aria-hidden>🛍️</span>}</div>
        <div className="thumbs">{p.images.map((im, i) => <button key={im.id} className={i === img ? "on" : ""} onClick={() => setImg(i)} aria-label={`Imagen ${i + 1}`}><img src={im.url} alt="" loading="lazy" /></button>)}</div>
      </div>
      <div>
        <h1>{p.name}</h1>
        <p className="muted">{[p.brand, p.model].filter(Boolean).join(" · ")} · SKU {p.sku}</p>
        <div className="price big">{usd(price)}{old && <span className="old">{usd(old)}</span>}</div>
        <p>{avail > 0 ? <span className="tag in">Disponible · {avail} unidades</span> : <span className="tag out">Agotado</span>}</p>
        {p.short_description && <p>{p.short_description}</p>}
        {p.variants.length > 0 && <label>Variante<select value={vid ?? ""} onChange={e => { setVid(e.target.value ? Number(e.target.value) : null); setQty(1); }}>
          <option value="">Selecciona…</option>
          {p.variants.map(x => <option key={x.id} value={x.id} disabled={!x.in_stock}>{Object.values(x.attributes).join(" / ")}{x.in_stock ? "" : " (agotado)"}</option>)}</select></label>}
        <div className="qty"><button className="btn ghost" onClick={() => setQty(Math.max(1, qty - 1))} aria-label="Disminuir">−</button><b>{qty}</b><button className="btn ghost" onClick={() => setQty(Math.min(max, qty + 1))} aria-label="Aumentar">+</button></div>
        <div className="row"><button className="btn" disabled={avail <= 0 || busy} onClick={() => addToCart(false)}>Añadir al carrito</button><button className="btn accent" disabled={avail <= 0 || busy} onClick={() => addToCart(true)}>Comprar ahora</button></div>
        {msg && <p className={msg.ok ? "okmsg" : "err"} role="status">{msg.t} {msg.ok && <Link to="/carrito">Ver carrito</Link>}</p>}
        {p.warranty && <div className="panel"><b>Garantía</b><br />{p.warranty}</div>}
        <div className="panel"><b>Envío</b><br />MRW, Zoom, Liberty Express y Tealca. El costo y el total finales los calcula el servidor en el checkout.</div>
      </div>
    </div>
    {p.description && <div className="panel"><h2>Descripción</h2><p style={{ whiteSpace: "pre-line" }}>{p.description}</p></div>}
    {Object.keys(p.specs).length > 0 && <div className="panel"><h2>Especificaciones técnicas</h2><table className="specs"><tbody>{Object.entries(p.specs).map(([k, val]) => <tr key={k}><th>{k}</th><td>{val}</td></tr>)}</tbody></table></div>}
    <div className="panel"><h2>Valoraciones y preguntas</h2><p className="muted">Se activarán cuando existan compras entregadas: solo compradores verificados podrán valorar.</p></div>
    {p.related.length > 0 && <section><h2>Productos relacionados</h2><div className="grid">{p.related.map(r => <ProductCard key={r.id} p={r} />)}</div></section>}
  </>);
}
