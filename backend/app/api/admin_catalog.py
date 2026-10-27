"""Gestión del catálogo (staff con permisos)."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession, selectinload
from app.api.deps import client_ip, require_permission
from app.core.config import settings
from app.db.session import get_db
from app.models import Category, Inventory, InventoryMovement, Product, ProductImage, ProductVariant, User
from app.schemas.catalog import (CategoryIn, CategoryOut, ImageOrder, Page, ProductIn, ProductUpdate, StockAdjust,
                                 VariantIn)
from app.services import catalog as svc
from app.services import storage
from app.services.audit import audit
from app.services.auth import now

router = APIRouter(prefix="/api/admin", tags=["admin-catalog"])
CAT = require_permission("categories.manage")
PROD = require_permission("products.manage")


# ---------- categorías ----------
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(_: User = Depends(CAT), db: DbSession = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.sort_order, Category.name)).all()


def _check_parent(db: DbSession, parent_id: int | None, self_id: int | None = None) -> None:
    if parent_id is None:
        return
    if not db.get(Category, parent_id):
        raise HTTPException(400, "La categoría superior no existe")
    if self_id and parent_id in svc.category_and_descendants(db, self_id):
        raise HTTPException(400, "Una categoría no puede ser hija de sí misma ni de sus descendientes")


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryIn, request: Request, actor: User = Depends(CAT), db: DbSession = Depends(get_db)):
    _check_parent(db, data.parent_id)
    c = Category(**data.model_dump(), slug=svc.unique_slug(db, Category, data.name))
    db.add(c); db.flush()
    audit(db, "category.created", actor.id, "category", c.id, {"name": c.name}, client_ip(request))
    db.commit()
    return c


@router.put("/categories/{cid}", response_model=CategoryOut)
def update_category(cid: int, data: CategoryIn, request: Request, actor: User = Depends(CAT),
                    db: DbSession = Depends(get_db)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Categoría no encontrada")
    _check_parent(db, data.parent_id, cid)
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    audit(db, "category.updated", actor.id, "category", cid, ip=client_ip(request))
    db.commit()
    return c


@router.delete("/categories/{cid}", status_code=204)
def delete_category(cid: int, request: Request, actor: User = Depends(CAT), db: DbSession = Depends(get_db)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Categoría no encontrada")
    has_children = db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == cid))
    has_products = db.scalar(select(func.count()).select_from(Product).where(Product.category_id == cid))
    if has_children or has_products:
        raise HTTPException(409, "Tiene subcategorías o productos asociados; desactívala en su lugar")
    db.delete(c)
    audit(db, "category.deleted", actor.id, "category", cid, ip=client_ip(request))
    db.commit()


@router.post("/categories/{cid}/image", response_model=CategoryOut)
async def category_image(cid: int, file: UploadFile = File(...), actor: User = Depends(CAT),
                         db: DbSession = Depends(get_db)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Categoría no encontrada")
    meta = await _store(f"categories/{cid}", file)
    c.image_url = meta["url"]
    audit(db, "category.image_changed", actor.id, "category", cid)
    db.commit()
    return c


async def _store(prefix: str, file: UploadFile) -> dict:
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    try:
        return storage.put_image(prefix, data)
    except storage.StorageNotConfigured as e:
        raise HTTPException(503, str(e))
    except storage.InvalidUpload as e:
        raise HTTPException(400, str(e))


# ---------- productos ----------
def _get_product(db: DbSession, pid: int) -> Product:
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    return p


@router.get("/products", response_model=Page)
def list_products(q: str | None = Query(default=None, max_length=100), status: str | None = None,
                  category_id: int | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
                  _: User = Depends(PROD), db: DbSession = Depends(get_db)):
    rows, total = svc.search_products(db, q=q, category_id=category_id, page=page, page_size=page_size,
                                      public=False, status=status, sort="newest")
    return {"items": [svc.card(p, a, i) for p, a, i in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/products", status_code=201)
def create_product(data: ProductIn, request: Request, actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    if not db.get(Category, data.category_id):
        raise HTTPException(400, "La categoría no existe")
    if db.scalar(select(Product.id).where(Product.sku == data.sku)):
        raise HTTPException(409, "Ya existe un producto con ese SKU")
    fields = data.model_dump(exclude={"initial_stock"})
    p = Product(**fields, slug=svc.unique_slug(db, Product, data.name))
    db.add(p); db.flush()
    inv = Inventory(product_id=p.id, quantity_on_hand=data.initial_stock)
    db.add(inv); db.flush()
    if data.initial_stock:
        db.add(InventoryMovement(inventory_id=inv.id, delta=data.initial_stock, reason="purchase",
                                 user_id=actor.id, note="Stock inicial"))
    audit(db, "product.created", actor.id, "product", p.id, {"sku": p.sku}, client_ip(request))
    db.commit()
    return {"id": p.id, "slug": p.slug}


@router.patch("/products/{pid}")
def update_product(pid: int, data: ProductUpdate, request: Request, actor: User = Depends(PROD),
                   db: DbSession = Depends(get_db)):
    p = _get_product(db, pid)
    changes = data.model_dump(exclude_unset=True, exclude={"clear_sale_price"})
    if "category_id" in changes and not db.get(Category, changes["category_id"]):
        raise HTTPException(400, "La categoría no existe")
    if "sku" in changes and db.scalar(select(Product.id).where(Product.sku == changes["sku"], Product.id != pid)):
        raise HTTPException(409, "Ya existe un producto con ese SKU")
    for k, v in changes.items():
        if v is not None:
            setattr(p, k, v)
    if data.clear_sale_price:
        p.sale_price_usd = None
    if p.sale_price_usd is not None and p.sale_price_usd >= p.price_usd:
        db.rollback()
        raise HTTPException(422, "El precio de oferta debe ser menor al precio normal")
    audit(db, "product.updated", actor.id, "product", pid, {"fields": sorted(changes)}, client_ip(request))
    db.commit()
    return {"id": p.id, "slug": p.slug}


@router.post("/products/{pid}/publish", status_code=204)
def publish(pid: int, actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    p = _get_product(db, pid)
    p.status, p.archived_at = "published", None
    audit(db, "product.published", actor.id, "product", pid)
    db.commit()


@router.post("/products/{pid}/unpublish", status_code=204)
def unpublish(pid: int, actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    p = _get_product(db, pid)
    p.status = "draft"
    audit(db, "product.unpublished", actor.id, "product", pid)
    db.commit()


@router.post("/products/{pid}/archive", status_code=204)
def archive(pid: int, actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    """Eliminación lógica: conserva el historial de pedidos."""
    p = _get_product(db, pid)
    p.status, p.archived_at = "archived", now()
    audit(db, "product.archived", actor.id, "product", pid)
    db.commit()


# ---------- variantes ----------
@router.post("/products/{pid}/variants", status_code=201)
def add_variant(pid: int, data: VariantIn, actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    p = _get_product(db, pid)
    if db.scalar(select(ProductVariant.id).where(ProductVariant.sku == data.sku)):
        raise HTTPException(409, "Ya existe una variante con ese SKU")
    v = ProductVariant(product_id=p.id, sku=data.sku, attributes=data.attributes, price_usd=data.price_usd,
                       sale_price_usd=data.sale_price_usd)
    db.add(v); db.flush()
    inv = Inventory(product_id=p.id, variant_id=v.id, quantity_on_hand=data.initial_stock)
    db.add(inv); db.flush()
    if data.initial_stock:
        db.add(InventoryMovement(inventory_id=inv.id, delta=data.initial_stock, reason="purchase",
                                 user_id=actor.id, note="Stock inicial de variante"))
    audit(db, "variant.created", actor.id, "product", pid, {"variant_sku": v.sku})
    db.commit()
    return {"id": v.id}


# ---------- inventario ----------
@router.post("/products/{pid}/inventory")
def adjust_stock(pid: int, data: StockAdjust, request: Request, actor: User = Depends(PROD),
                 db: DbSession = Depends(get_db)):
    _get_product(db, pid)
    # Bloqueo de fila: ajustes concurrentes se serializan
    cond = Inventory.variant_id == data.variant_id if data.variant_id else Inventory.variant_id.is_(None)
    inv = db.scalar(select(Inventory).where(Inventory.product_id == pid, cond).with_for_update())
    if not inv:
        raise HTTPException(404, "No hay inventario para ese producto/variante")
    new_qty = inv.quantity_on_hand + data.delta
    if new_qty < 0 or new_qty < inv.quantity_reserved:
        raise HTTPException(409, "El ajuste dejaría el inventario por debajo de lo reservado o negativo")
    inv.quantity_on_hand = new_qty
    db.add(InventoryMovement(inventory_id=inv.id, delta=data.delta, reason=data.reason, user_id=actor.id,
                             note=data.note))
    audit(db, "inventory.adjusted", actor.id, "product", pid, {"delta": data.delta, "reason": data.reason},
          client_ip(request))
    db.commit()
    return {"quantity_on_hand": inv.quantity_on_hand, "quantity_reserved": inv.quantity_reserved}


# ---------- imágenes ----------
@router.post("/products/{pid}/images", status_code=201)
async def upload_image(pid: int, file: UploadFile = File(...), alt: str | None = None,
                       actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    p = _get_product(db, pid)
    count = db.scalar(select(func.count()).select_from(ProductImage).where(ProductImage.product_id == pid))
    if count >= 10:
        raise HTTPException(400, "Máximo 10 imágenes por producto")
    meta = await _store(f"products/{pid}", file)
    im = ProductImage(product_id=p.id, url=meta["url"], storage_key=meta["key"], mime_type=meta["mime"],
                      size_bytes=meta["size"], alt_text=(alt or p.name)[:250], sort_order=count)
    db.add(im)
    audit(db, "product.image_added", actor.id, "product", pid)
    db.commit()
    return {"id": im.id, "url": im.url}


@router.put("/products/{pid}/images/order", status_code=204)
def reorder_images(pid: int, data: ImageOrder, actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    imgs = {i.id: i for i in db.scalars(select(ProductImage).where(ProductImage.product_id == pid)).all()}
    if set(data.ids) != set(imgs):
        raise HTTPException(400, "La lista debe contener exactamente las imágenes del producto")
    for pos, iid in enumerate(data.ids):
        imgs[iid].sort_order = pos
    audit(db, "product.images_reordered", actor.id, "product", pid)
    db.commit()


@router.delete("/products/{pid}/images/{iid}", status_code=204)
def delete_image(pid: int, iid: int, actor: User = Depends(PROD), db: DbSession = Depends(get_db)):
    im = db.scalar(select(ProductImage).where(ProductImage.id == iid, ProductImage.product_id == pid))
    if not im:
        raise HTTPException(404, "Imagen no encontrada")
    key = im.storage_key
    db.delete(im)
    audit(db, "product.image_deleted", actor.id, "product", pid)
    db.commit()
    storage.delete_object(key)   # tras confirmar la BD
