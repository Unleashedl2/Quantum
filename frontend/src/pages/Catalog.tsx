import { useSearchParams } from "react-router-dom";
import ProductCard from "../components/ProductCard";
import { useFetch } from "../hooks";
import { Category, Page } from "../types";

export default function Catalog() {
  const [sp, setSp] = useSearchParams();
  const { data, loading, error } = useFetch<Page>(`/api/products?${sp.toString()}`);
  const { data: cats } = useFetch<Category[]>("/api/categories");
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); n.delete("page"); setSp(n); };
  const page = Number(sp.get("page") ?? 1);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const goto = (p: number) => { const n = new URLSearchParams(sp); n.set("page", String(p)); setSp(n); window.scrollTo(0, 0); };
  return (
    <div className="catalog">
      <aside className="filters" aria-label="Filtros">
        <h3>Filtros</h3>
        <label>Categoría
          <select value={sp.get("category_id") ?? ""} onChange={e => set("category_id", e.target.value)}>
            <option value="">Todas</option>
            {(cats ?? []).map(c => <option key={c.id} value={c.id}>{c.parent_id ? "— " : ""}{c.name}</option>)}
          </select></label>
        <label>Precio mínimo (USD)<input type="number" min="0" defaultValue={sp.get("min_price") ?? ""} onBlur={e => set("min_price", e.target.value)} /></label>
        <label>Precio máximo (USD)<input type="number" min="0" defaultValue={sp.get("max_price") ?? ""} onBlur={e => set("max_price", e.target.value)} /></label>
        <label className="chk"><input type="checkbox" checked={sp.get("in_stock") === "true"} onChange={e => set("in_stock", e.target.checked ? "true" : "")} /> Solo disponibles</label>
        <label className="chk"><input type="checkbox" checked={sp.get("on_sale") === "true"} onChange={e => set("on_sale", e.target.checked ? "true" : "")} /> Solo ofertas</label>
      </aside>
      <section>
        <div className="sech">
          <h2>{sp.get("q") ? `Resultados para «${sp.get("q")}»` : "Productos"}{data ? ` (${data.total})` : ""}</h2>
          <label>Ordenar <select value={sp.get("sort") ?? "relevance"} onChange={e => set("sort", e.target.value)}>
            <option value="relevance">Relevancia</option><option value="newest">Más recientes</option>
            <option value="price_asc">Precio: menor a mayor</option><option value="price_desc">Precio: mayor a menor</option></select></label>
        </div>
        {loading && <p className="muted">Cargando…</p>}
        {error && <p className="err" role="alert">{error}</p>}
        {data && !loading && data.items.length === 0 && <p>No encontramos productos con esos filtros.</p>}
        <div className="grid">{data?.items.map(p => <ProductCard key={p.id} p={p} />)}</div>
        {data && pages > 1 && <nav className="pager" aria-label="Paginación">
          <button className="btn ghost" disabled={page <= 1} onClick={() => goto(page - 1)}>Anterior</button>
          <span>Página {page} de {pages}</span>
          <button className="btn ghost" disabled={page >= pages} onClick={() => goto(page + 1)}>Siguiente</button></nav>}
      </section>
    </div>);
}
