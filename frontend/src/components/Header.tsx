import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useCart } from "../cart";
import { Category } from "../types";

export default function Header() {
  const { me, logout, can } = useAuth();
  const { count } = useCart();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [cats, setCats] = useState<Category[]>([]);
  const [unread, setUnread] = useState(0);
  useEffect(() => { api<Category[]>("/api/categories").then(setCats).catch(() => setCats([])); }, []);
  useEffect(() => {
    if (!me || me.must_change_password) { setUnread(0); return; }
    const poll = () => api<{ unread: number }>("/api/notifications?unread_only=true").then(d => setUnread(d.unread)).catch(() => {});
    poll(); const t = setInterval(poll, 60000); return () => clearInterval(t);
  }, [me]);
  const submit = (e: FormEvent) => { e.preventDefault(); nav(`/productos?q=${encodeURIComponent(q)}`); };
  return (
    <header className="hdr">
      <div className="bar">
        <Link to="/" className="logo"><i />Quantum Store</Link>
        <form className="search" onSubmit={submit} role="search">
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Buscar productos, marcas…" aria-label="Buscar productos" maxLength={100} />
          <button type="submit">Buscar</button>
        </form>
        {me ? (<>
          {can("products.manage") && <Link className="btn ghost" to="/admin/catalogo">Catálogo</Link>}
          {can("payments.review") && <Link className="btn ghost" to="/admin/pagos">Pagos</Link>}
          {can("banks.manage") && <Link className="btn ghost" to="/admin/bancos">Bancos</Link>}
          <Link className="btn ghost" to="/notificaciones" aria-label={`Notificaciones, ${unread} sin leer`}>🔔{unread > 0 ? ` ${unread}` : ""}</Link>
          <Link className="btn ghost" to="/pedidos">Mis pedidos</Link>
          <span className="hi">Hola, {me.first_name}</span>
          <button className="btn ghost" onClick={() => logout().then(() => nav("/"))}>Salir</button>
        </>) : (<><Link className="btn ghost" to="/ingresar">Ingresar</Link><Link className="btn" to="/registro">Crear cuenta</Link></>)}
        <Link className="btn ghost" to="/carrito">🛒 Carrito{count > 0 ? ` (${count})` : ""}</Link>
      </div>
      <nav className="catnav" aria-label="Categorías">
        {cats.filter(c => c.parent_id === null).map(c => <Link key={c.id} to={`/productos?category_id=${c.id}`}>{c.name}</Link>)}
      </nav>
    </header>
  );
}
