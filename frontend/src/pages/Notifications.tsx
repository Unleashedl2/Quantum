import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { fmtDate, NotificationT } from "../types";

export default function Notifications() {
  const { me, loading, can } = useAuth();
  const [data, setData] = useState<{ unread: number; items: NotificationT[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<{ unread: number; items: NotificationT[] }>("/api/notifications").then(setData).catch(e => setErr((e as Error).message)), []);
  useEffect(() => { if (me) load(); }, [me, load]);
  if (loading) return <p className="muted">Cargando…</p>;
  if (!me) return <Navigate to="/ingresar" replace />;
  const read = async (n: NotificationT) => { if (!n.read) { await api(`/api/notifications/${n.id}/read`, { method: "POST" }); load(); } };
  const link = (n: NotificationT) => !n.order_number ? null : n.audience === "staff" && can("payments.review") ? <Link to="/admin/pagos" onClick={() => read(n)}>Ir al centro de pagos</Link> : <Link to={`/pedidos/${n.order_number}`} onClick={() => read(n)}>Ver pedido</Link>;
  return (<div><div className="sech"><h1>Notificaciones</h1>{data && data.unread > 0 && <button className="btn ghost" onClick={async () => { await api("/api/notifications/read-all", { method: "POST" }); load(); }}>Marcar todas como leídas</button>}</div>
    {err && <p className="err" role="alert">{err}</p>}
    {data && data.items.length === 0 && <p className="muted">No tienes notificaciones.</p>}
    {data?.items.map(n => <article key={n.id} className={`panel notif ${n.read ? "" : "unread"}`}>
      <b>{n.title}</b>{n.audience === "staff" && <span className="tag low">Equipo</span>}<br />{n.body && <span>{n.body}<br /></span>}
      <small className="muted">{fmtDate(n.created_at)}</small> {link(n)}</article>)}
    <p className="muted">Las notificaciones se muestran aquí. El envío por correo, SMS o WhatsApp requiere configurar un proveedor y aún no está activo.</p></div>);
}
