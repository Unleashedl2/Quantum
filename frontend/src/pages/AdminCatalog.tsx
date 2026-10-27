import { FormEvent, useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, usd } from "../api";
import { useAuth } from "../auth";
import { Category, Page, ProductCardT } from "../types";

export default function AdminCatalog() {
  const { can, loading } = useAuth();
  const [cats, setCats] = useState<Category[]>([]);
  const [prods, setProds] = useState<ProductCardT[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [q, setQ] = useState("");
  const note = (ok: boolean, text: string) => setMsg({ ok, text });
  const load = useCallback(async () => {
    try {
      setCats(await api<Category[]>("/api/admin/categories"));
      setProds((await api<Page>(`/api/admin/products?page_size=50&q=${encodeURIComponent(q)}`)).items);
    } catch (e) { note(false, (e as Error).message); }
  }, [q]);
  useEffect(() => { if (can("products.manage")) load(); }, [load, can]);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!can("products.manage")) return <Navigate to="/" replace />;
  const run = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); note(true, ok); await load(); } catch (e) { note(false, (e as Error).message); } };

  const addCat = (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); const form = e.currentTarget;
    run(async () => { await api("/api/admin/categories", { method: "POST", body: { name: f.get("name"), parent_id: f.get("parent_id") ? Number(f.get("parent_id")) : null } }); form.reset(); }, "Categoría creada"); };
  const addProd = (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); const form = e.currentTarget;
    const sale = String(f.get("sale") ?? "");
    run(async () => { await api("/api/admin/products", { method: "POST", body: {
      category_id: Number(f.get("category_id")), name: f.get("name"), brand: f.get("brand") || null, sku: f.get("sku"),
      price_usd: String(f.get("price")), sale_price_usd: sale || null, short_description: f.get("short") || null,
      initial_stock: Number(f.get("stock") || 0), status: f.get("publish") ? "published" : "draft" } }); form.reset(); }, "Producto creado"); };
  const adjust = (p: ProductCardT) => { const v = window.prompt(`Ajuste de inventario para «${p.name}» (ej. 5 o -2):`); if (!v) return; const delta = Number(v);
    if (!Number.isInteger(delta) || delta === 0) return note(false, "Ingresa un entero distinto de 0");
    run(() => api(`/api/admin/products/${p.id}/inventory`, { method: "POST", body: { delta, reason: "adjustment", note: "Ajuste manual" } }), "Inventario ajustado"); };
  const upload = (p: ProductCardT, file: File | undefined) => { if (!file) return; const fd = new FormData(); fd.append("file", file);
    run(() => api(`/api/admin/products/${p.id}/images`, { method: "POST", form: fd }), "Imagen subida"); };

  return (<div>
    <h1>Gestión de catálogo</h1>
    {msg && <p className={msg.ok ? "okmsg" : "err"} role="status">{msg.text}</p>}
    <div className="two">
      <form className="form" onSubmit={addCat}><h2>Nueva categoría</h2>
        <label>Nombre<input name="name" required minLength={2} /></label>
        <label>Categoría superior<select name="parent_id"><option value="">(ninguna)</option>{cats.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <button className="btn">Crear categoría</button>
        <ul className="plain">{cats.map(c => <li key={c.id}>{c.parent_id ? "— " : ""}{c.name}
          <button type="button" className="link" onClick={() => run(() => api(`/api/admin/categories/${c.id}`, { method: "DELETE" }), "Categoría eliminada")}>eliminar</button></li>)}</ul></form>
      <form className="form" onSubmit={addProd}><h2>Nuevo producto</h2>
        <label>Categoría<select name="category_id" required><option value="">Selecciona…</option>{cats.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <label>Nombre<input name="name" required minLength={2} /></label>
        <label>Marca<input name="brand" /></label>
        <label>SKU<input name="sku" required pattern="[A-Za-z0-9._\-]+" /></label>
        <label>Precio USD<input name="price" type="number" step="0.01" min="0" required /></label>
        <label>Precio de oferta USD (opcional)<input name="sale" type="number" step="0.01" min="0" /></label>
        <label>Descripción corta<input name="short" maxLength={500} /></label>
        <label>Existencia inicial<input name="stock" type="number" min="0" defaultValue={0} /></label>
        <label className="chk"><input type="checkbox" name="publish" /> Publicar de inmediato</label>
        <button className="btn">Crear producto</button></form>
    </div>
    <div className="sech"><h2>Productos</h2><input placeholder="Buscar…" value={q} onChange={e => setQ(e.target.value)} aria-label="Buscar productos" /></div>
    <div className="scroll"><table className="tbl"><thead><tr><th>Producto</th><th>SKU</th><th>Precio</th><th>Stock</th><th>Estado</th><th>Acciones</th></tr></thead>
      <tbody>{prods.map(p => <tr key={p.id}><td>{p.name}</td><td>{p.sku}</td><td>{usd(p.effective_price_usd)}</td><td>{p.available}</td><td>{p.status}</td>
        <td className="acts">
          {p.status !== "published" ? <button className="btn ghost" onClick={() => run(() => api(`/api/admin/products/${p.id}/publish`, { method: "POST" }), "Publicado")}>Publicar</button>
            : <button className="btn ghost" onClick={() => run(() => api(`/api/admin/products/${p.id}/unpublish`, { method: "POST" }), "Pasado a borrador")}>Despublicar</button>}
          <button className="btn ghost" onClick={() => adjust(p)}>Stock</button>
          <label className="btn ghost filebtn">Foto<input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={e => { upload(p, e.target.files?.[0]); e.target.value = ""; }} /></label>
          <button className="btn ghost" onClick={() => window.confirm("¿Archivar? Se conserva el historial de pedidos.") && run(() => api(`/api/admin/products/${p.id}/archive`, { method: "POST" }), "Archivado")}>Archivar</button>
        </td></tr>)}</tbody></table></div>
  </div>);
}
