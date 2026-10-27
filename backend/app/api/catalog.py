"""Endpoints públicos del catálogo (solo lectura; solo productos publicados)."""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession, selectinload
from app.db.session import get_db
from app.models import Category, Inventory, Product
from app.schemas.catalog import CategoryOut, Page
from app.services import catalog as svc

router = APIRouter(prefix="/api", tags=["catalog"])
CACHE = "public, max-age=30, stale-while-revalidate=60"


@router.get("/categories", response_model=list[CategoryOut])
def categories(response: Response, db: DbSession = Depends(get_db)):
    response.headers["Cache-Control"] = CACHE
    return db.scalars(select(Category).where(Category.is_active.is_(True))
                      .order_by(Category.sort_order, Category.name)).all()


@router.get("/products", response_model=Page)
def products(response: Response, q: str | None = Query(default=None, max_length=100), category_id: int | None = None,
             min_price: Decimal | None = Query(default=None, ge=0), max_price: Decimal | None = Query(default=None, ge=0),
             in_stock: bool = False, on_sale: bool = False, featured: bool = False,
             sort: str = Query(default="relevance", pattern="^(relevance|price_asc|price_desc|newest)$"),
             page: int = Query(default=1, ge=1, le=10_000), page_size: int = Query(default=24, ge=1, le=48),
             db: DbSession = Depends(get_db)):
    response.headers["Cache-Control"] = CACHE
    rows, total = svc.search_products(db, q=q, category_id=category_id, min_price=min_price, max_price=max_price,
                                      in_stock=in_stock, on_sale=on_sale, featured=featured, sort=sort,
                                      page=page, page_size=page_size)
    return {"items": [svc.card(p, a, i) for p, a, i in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/products/{slug}")
def product_detail(slug: str, response: Response, db: DbSession = Depends(get_db)):
    response.headers["Cache-Control"] = CACHE
    p = db.scalar(select(Product).where(Product.slug == slug, Product.status == "published")
                  .options(selectinload(Product.images), selectinload(Product.variants)))
    cat = db.get(Category, p.category_id) if p else None
    if not p or not cat or not cat.is_active:
        raise HTTPException(404, "Producto no encontrado")
    inv = {(r.variant_id): r.quantity_on_hand - r.quantity_reserved
           for r in db.scalars(select(Inventory).where(Inventory.product_id == p.id)).all()}
    total_avail = sum(inv.values())
    related_rows, _ = svc.search_products(db, category_id=p.category_id, page_size=9)
    related = [svc.card(rp, a, i) for rp, a, i in related_rows if rp.id != p.id][:8]
    return {
        **svc.card(p, total_avail, p.images[0].url if p.images else None),
        "short_description": p.short_description, "description": p.description, "model": p.model,
        "specs": p.specs or {}, "warranty": p.warranty,
        "dimensions": {"weight_kg": p.weight_kg, "length_cm": p.length_cm, "width_cm": p.width_cm,
                       "height_cm": p.height_cm},
        "category": {"id": cat.id, "name": cat.name, "slug": cat.slug},
        "images": [{"id": im.id, "url": im.url, "alt": im.alt_text} for im in p.images],
        "variants": [{"id": v.id, "sku": v.sku, "attributes": v.attributes,
                      "price_usd": svc.variant_prices(p, v)[0],
                      "sale_price_usd": svc.variant_prices(p, v)[1], "available": max(0, inv.get(v.id, 0)),
                      "in_stock": inv.get(v.id, 0) > 0} for v in p.variants if v.is_active],
        "related": related,
    }
