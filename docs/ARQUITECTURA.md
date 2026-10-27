# Quantum Store — Arquitectura, modelo de datos y plan

## 1. Arquitectura
Monolito modular (sin microservicios ni Redis hasta que haya una necesidad medida).

```
Navegador (React+TS, Vite)  ──HTTPS──►  Reverse proxy (Caddy/Nginx, TLS, gzip)
                                           ├─► /        archivos estáticos del frontend
                                           └─► /api     FastAPI (uvicorn) ──► PostgreSQL 16 (pool SQLAlchemy)
                                                                         └─► S3 compatible (imágenes, comprobantes)
```
- **Sesiones**: cookie `HttpOnly`, `SameSite=Lax`, `Secure` en producción; token opaco guardado como SHA-256 en tabla `sessions` (revocable). **CSRF**: token sincronizado en cabecera `X-CSRF-Token` para métodos no seguros.
- **Autorización**: roles → permisos (`payments.review`, `staff.manage`, …) verificados en el servidor con `require_permission`.
- **Dinero**: `NUMERIC(12,2)` en USD; el backend recalcula siempre precios y totales. CHECK de consistencia en `orders` y `order_items`.
- **Inventario**: CHECK `quantity_on_hand >= 0` y `reserved <= on_hand` + `SELECT … FOR UPDATE` en checkout (Fase 4) → sin sobreventa por concurrencia.
- **Tiempo**: `timestamptz` en UTC; presentación en `America/Caracas`.
- **Archivos**: solo URL/`storage_key` y metadatos en BD; binarios en S3.
- **Tareas asíncronas** (correo, miniaturas): tabla-cola en PostgreSQL con worker propio; se evalúa Redis solo si el volumen lo justifica.

## 2. Estructura de carpetas
```
quantumstore/
├─ docker-compose.yml        .env.example      README.md
├─ docs/                     ARQUITECTURA.md   RESPALDOS.md
├─ backend/
│  ├─ Dockerfile  requirements.txt  alembic.ini
│  ├─ alembic/ (env.py, versions/0001_baseline.py)
│  ├─ seeds/banks_ve.csv
│  ├─ app/
│  │  ├─ main.py   cli.py
│  │  ├─ core/ (config.py, security.py)
│  │  ├─ db/ (base.py, session.py)
│  │  ├─ models/ (identity, catalog, sales, system)
│  │  ├─ schemas/  api/ (deps.py, auth.py, …)  services/ (auth.py, audit.py, …)
│  └─ tests/
└─ frontend/ (Fase 3 en adelante: React + TypeScript + Vite)
```

## 3. Modelo relacional (resumen de relaciones)
- `users` 1—N `user_addresses`; `users` N—M `roles` (`user_roles`); `roles` N—M `permissions` (`role_permissions`); `users` 1—N `sessions`, `password_reset_tokens`.
- `categories` (auto-referencia `parent_id`) 1—N `products` 1—N `product_images`, `product_variants`; `inventory` por producto/variante 1—N `inventory_movements` (libro de movimientos).
- `carts` 1—1 `users`, 1—N `cart_items`.
- `orders` N—1 `users`; 1—N `order_items` (con **snapshot** de nombre, SKU, precio, descripción y variante); 1—N `payments` (N—1 `payment_methods`, N—1 `banks` ×2); 1—1 `shipments` (N—1 `shipping_methods`); 1—N `shipment_events` (append-only); 1—1 `delivery_confirmations`.
- `product_reviews` → `order_items` (UNIQUE por ítem comprado = compra verificada, sin duplicados); `product_questions` 1—N `product_answers`.
- Transversales: `notifications`, `site_settings` (clave/valor JSONB, p. ej. `theme.colors`), `audit_logs`.

Reglas en la BD: precio oferta < precio; estados válidos por CHECK; pago aprobado/rechazado exige revisor y fecha (`review_audited`); `orders.total = subtotal + envío`.

## 4. Plan por fases
| Fase | Contenido | Estado |
|---|---|---|
| 1 | Arquitectura, modelo, migración base, config, Docker, seguridad núcleo, registro/login/cambio de contraseña, CLI de inicialización, pruebas base | **Entregada (ver README: qué está verificado y qué no)** |
| 2 | Verificación de correo, recuperación de contraseña, direcciones, perfil, gestión de staff | **Entregada** (pendiente: worker SMTP, límites por IP) |
| 3 | Catálogo, categorías, imágenes S3, búsqueda, detalle, frontend base | **Entregada** (pendiente: miniaturas, "más vendidos") |
| 4 | Carrito, checkout transaccional, reservas de inventario, mis pedidos | **Entregada** (pendiente: cron de `expire-orders`) |
| 5 | Pagos, centro de validación, bancos, notificaciones en pantalla | **Entregada** (pendiente: correo/SMS/WhatsApp) |
| 6 | Envíos manuales, seguimiento, confirmación OTP, liberación administrativa | Pendiente |
| 7 | Dashboard, reportes CSV/Excel, personalización de colores | Pendiente |
| 8 | Pruebas E2E, rendimiento, respaldos probados, despliegue | Pendiente |

## 5. Decisiones y supuestos documentados
1. **Contraseñas temporales `123456`**: no se escriben en el código. Se pasan por `INIT_TEMP_PASSWORD` y solo el comando `init-admins` las acepta; ese comando se **niega** con `APP_ENV=production`, las cuentas nacen con `must_change_password=true` y la API bloquea todo salvo cambiar la contraseña hasta que se haga. La validación normal exige ≥12 caracteres con mezcla, así que `123456` jamás sirve como contraseña definitiva. Master y Admin deberían usar contraseñas distintas; no compartas la misma fuera de un entorno local.
2. **Bancos**: la lista inicial (`seeds/banks_ve.csv`) se cargó de memoria con códigos de 4 dígitos y queda con `verified_at = NULL`. Debes contrastarla con el listado vigente de SUDEBAN antes de producción; se administra desde el panel (Fase 7).
3. **Unicidad de cuenta**: correo (case-insensitive con CITEXT) y cédula son únicos. El error de registro es genérico para no revelar cuál existe.
4. **Envíos**: `api_integrated=false`; guías manuales. No se afirma integración con MRW/Zoom/Liberty/Tealca.
5. **USDT/pagos**: ningún pago pasa a `approved` sin `reviewed_by` y `reviewed_at` (restricción en BD).
6. **Migración 0001** usa `create_all` como línea base; los cambios siguientes se generan con `alembic revision --autogenerate`.

## 6. Inventario y estados (Fase 4)
- `available = quantity_on_hand - quantity_reserved`. Crear pedido suma a `reserved`; cancelar/vencer lo resta; aprobar pago (Fase 5) resta de ambos.
- Movimientos: `reserve` (−qty), `release` (+qty). Estados permitidos en `services/orders.ALLOWED`; cualquier otro salto responde 409.
- Concurrencia: `SELECT … FOR UPDATE` sobre `carts` (un checkout por cliente a la vez) e `inventory` (ordenado por id).

## 7. Pagos (Fase 5)
- Un pago «abierto» por pedido (índice parcial). `approved` exige `reviewed_by/at` (CHECK) y la aprobación se hace con bloqueo de fila sobre pago, pedido e inventario.
- Libro de inventario: `on_hand` cambia con `purchase|sale|adjustment|return`; `reserve|release` documentan cambios de `reserved` (no suman al stock físico).
- Las cuentas receptoras y la dirección USDT viven en `payment_methods.config` (editables por el Master) y solo se muestran al dueño del pedido.
