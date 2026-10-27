import { Link } from "react-router-dom";
import ProductCard from "../components/ProductCard";
import { useFetch } from "../hooks";
import { Category, Page } from "../types";

function Section({ title, query, more }: { title: string; query: string; more: string }) {
  const { data, loading, error } = useFetch<Page>(`/api/products?${query}`);
  if (loading) return <p className="muted">Cargando {title.toLowerCase()}…</p>;
  if (error) return <p className="err" role="alert">{error}</p>;
  if (!data?.items.length) return null;
  return (<section><div className="sech"><h2>{title}</h2><Link to={more}>Ver todo</Link></div><div className="grid">{data.items.map(p => <ProductCard key={p.id} p={p} />)}</div></section>);
}

export default function Home() {
  const { data: cats } = useFetch<Category[]>("/api/categories");
  const top = (cats ?? []).filter(c => c.parent_id === null);
  return (<>
    <div className="hero"><h1>Ofertas de la semana</h1><p>Compra con transferencia, pago móvil, efectivo o USDT.</p><Link className="btn light" to="/productos?on_sale=true">Ver ofertas</Link></div>
    {top.length > 0 && <div className="cats">{top.map(c => (
      <Link key={c.id} to={`/productos?category_id=${c.id}`} className="cat">
        {c.image_url ? <img src={c.image_url} alt="" loading="lazy" /> : <span aria-hidden>🛍️</span>}<small>{c.name}</small></Link>))}</div>}
    <Section title="Ofertas" query="on_sale=true&page_size=8" more="/productos?on_sale=true" />
    <Section title="Productos destacados" query="featured=true&page_size=8" more="/productos?featured=true" />
    <Section title="Productos recientes" query="sort=newest&page_size=8" more="/productos?sort=newest" />
    <p className="muted">«Más vendidos» se activa en la Fase 7, cuando existan ventas reales que ordenar.</p>
  </>);
}
