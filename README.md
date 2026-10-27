# Quantum Store — Fases 1 a 5

> Nombre del proyecto: **Quantum Store** (antes «NovaMarket»). Identificadores técnicos: base `quantumstore`, cookie `qs_session`, pedidos `QS-000001`. Si ya tienes una base creada con los nombres anteriores, conserva tus valores en `.env`; los pedidos antiguos conservarán el prefijo `NM-`.

## Puesta en marcha
```bash
cp .env.example .env            # edite SECRET_KEY, POSTGRES_PASSWORD y DATABASE_URL
docker compose up -d db
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                      # crea el esquema
python -m app.cli init-system             # permisos, roles, métodos de pago/envío, bancos
INIT_TEMP_PASSWORD='<temporal>' python -m app.cli init-admins   # solo desarrollo
uvicorn app.main:app --reload             # http://localhost:8000/docs
```
O todo con Docker: `docker compose up --build` (luego ejecute los dos comandos CLI con `docker compose exec api …`).

## Pruebas
```bash
pytest tests/test_security.py                                   # unitarias
TEST_DATABASE_URL=postgresql+psycopg://... pytest               # integración (BD de pruebas, se recrea)
```

## Variables a configurar
Ver `.env.example`. SMTP y S3 quedan vacíos: **no hay envío de correos ni subida de imágenes todavía** y nada se simula.

## Qué incluye la Fase 1 y su estado real
- Esquema PostgreSQL completo (todas las entidades del prompt) + migración base.
- Registro, login, logout, `me`, cambio de contraseña; Argon2id, sesiones revocables, CSRF, bloqueo por intentos, auditoría.
- Cambio obligatorio de contraseña temporal, CLI idempotente de inicialización.
- **Fase 2**: verificación de correo, recuperación/restablecimiento de contraseña (token de un solo uso, hash en BD, revoca sesiones), perfil editable, direcciones (aisladas por usuario), solicitud de cierre de cuenta, gestión de staff (crear/listar/bloquear; un Admin no toca a un Master). Migración `0002`.
- **Correo**: los mensajes se guardan en `email_outbox` con estado `pending`. Aún no hay worker SMTP, así que **no se envía ningún correo real**; en desarrollo el enlace aparece en el log.
- **Fase 3 (catálogo)**:
  - API pública: `/api/categories`, `/api/products` (búsqueda por nombre/marca/descripción/SKU, categoría con subcategorías, precio efectivo, ofertas, destacados, disponibilidad, orden por relevancia/precio/recientes, paginación) y `/api/products/{slug}` (galería, variantes, especificaciones, relacionados).
  - API admin (permisos `categories.manage` / `products.manage`): CRUD de categorías, productos, variantes, publicar/despublicar/**archivar** (borrado lógico), ajustes de inventario con bloqueo de fila y registro de movimientos, subida/ordenado/borrado de imágenes (tipo verificado por contenido, máx. 5 MB, 10 por producto).
  - Frontend React+TS: inicio, catálogo con filtros, detalle, registro/login, cambio obligatorio de contraseña temporal, pantalla admin de catálogo.
  - Migración `0003` (índice único de inventario sin variante, índices de búsqueda).
- **Imágenes**: requieren un bucket S3 compatible y las variables `S3_*` + `S3_PUBLIC_BASE_URL`. Sin ellas la subida responde 503 con un mensaje claro; no se simula. No se generan miniaturas todavía (se sirven las originales con carga diferida).
- **Fase 4 (compra)**:
  - Carrito persistente por cliente (requiere sesión): precios y stock siempre del servidor; se avisa si un producto cambió, se agotó o se archivó.
  - Checkout con resumen previo (`POST /api/checkout/summary`) y creación del pedido (`POST /api/orders`) en **una sola transacción**: bloqueo de filas de inventario ordenado por id, verificación de stock ya bloqueado, reserva (`quantity_reserved`), copia histórica de producto/precio/variante/dirección, historial de estados (`order_events`, solo se agrega), notificaciones internas y vaciado del carrito.
  - `Idempotency-Key`: un doble clic no duplica el pedido.
  - Mis pedidos (listado y detalle, aislados por cliente: un pedido ajeno responde 404) y cancelación mientras esté pendiente de pago (libera el stock).
  - Reserva vencida: `python -m app.cli expire-orders` cancela pedidos sin pago declarado pasadas `RESERVATION_HOURS` (24 h) y libera el stock. **Debes programarlo** (cron o timer cada 10–15 min).
  - Migración `0004`. Las pruebas ahora recrean la BD aplicando las migraciones.
- **Decisiones**: envío en $0 «a coordinar» (`SHIPPING_FLAT_USD`), todo en USD, carrito solo con sesión. El stock físico se descuenta cuando se **apruebe el pago** (Fase 5); hasta entonces solo está reservado.
- **Fase 5 (pagos)**:
  - El cliente declara el pago de su pedido con campos dinámicos por método (transferencia, pago móvil, efectivo, USDT) y puede adjuntar un comprobante (JPG/PNG/WEBP, privado en S3, visible al admin por URL temporal de 5 min).
  - Estados: declarado → en revisión → aprobado / rechazado / información adicional. **Nada se aprueba solo**: aprobar exige un administrador con permiso `payments.review` y que indique con qué medio verificó el dinero; en USDT, además, las confirmaciones observadas deben alcanzar el mínimo de la red configurada. Se guarda quién, cuándo y por qué (restricción en BD) y todo el historial (`payment_events`, solo se agrega).
  - Alertas automáticas para el revisor: referencia repetida en otro pedido, importe distinto al total, efectivo contra entrega sin cobrar. La misma referencia no puede aprobarse dos veces (índice único).
  - Aprobar convierte la reserva en salida física de inventario (`on_hand` y `reserved` bajan, movimiento `sale`) en una sola transacción. El pedido no avanza solo: el admin lo pasa a «Preparando envío» (`/api/admin/orders/{n}/prepare`).
  - Rechazar devuelve el pedido a «Pendiente de pago» con una nueva reserva de 24 h; máximo 5 rechazos por pedido.
  - Bancos administrables (`/admin/bancos`: buscar, crear, activar, renombrar, marcar verificado) y configuración de cuentas receptoras, instrucciones, dirección/redes USDT por el Master.
  - Centro de notificaciones en pantalla (cliente y bandeja del equipo) con contador en el encabezado. **No hay correo/SMS/WhatsApp**: requieren un proveedor y quedan para una fase posterior. La bandeja del equipo comparte el estado «leído» entre administradores.
  - Migración `0005`.
- **Pendiente conocido**: el efectivo «contra entrega» se aprueba como «autorizado», pero queda marcado `settlement = pending_on_delivery`; el cobro real se registrará en la Fase 6 (entrega) y los ingresos del dashboard (Fase 7) solo contarán pagos efectivamente cobrados.
- **No incluido aún**: gestión de envíos (guías, despacho, transportistas), seguimiento completo y confirmación de entrega, valoraciones/preguntas, dashboard, reportes, personalización de colores.
- **Verificación**: el código compila, pero en el entorno donde lo generé no había acceso a red para instalar dependencias, por lo que **no he ejecutado** la migración ni las pruebas. Ejecútalas tú y envíame cualquier error para corregirlo antes de la Fase 2.

## Frontend
```bash
cd frontend && npm install && npm run dev
```
