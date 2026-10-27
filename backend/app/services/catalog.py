import re
import unicodedata
from decimal import Decimal
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session as DbSession
from app.models import Category, Inventory, Product, ProductImage


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:120] or "item"


def unique_slug(db: DbSession, model, base: str, exclude_id: int | None = None) -> str:
    slug, n = slugify(base), 1
    while True:
        q = select(model.id).where(model.slug == slug)
        if exclude_id:
            q = q.where(model.id != exclude_id)
        if not db.scalar(q):
            return slug
        n += 1
        slug = f"{slugify(base)}-{n}"


def category_and_descendants(db: DbSession, root_id: int) -> list[int]:
    rows = db.execute(select(Category.id, Category.parent_id)).all()
    children: dict[int, list[int]] = {}
    for cid, pid in rows:
        children.setdefault(pid, []).append(cid)
    out, stack = [], [root_id]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children.get(cur, []))
    return out


def available_expr():
    return func.coalesce(
        select(func.sum(Inventory.quantity_on_hand - Inventory.quantity_reserved))
        .where(Inventory.product_id == Product.id).correlate(Product).scalar_subquery(), 0)


def image_expr():
    return (select(ProductImage.url).where(ProductImage.product_id == Product.id)
            .order_by(ProductImage.sort_order, ProductImage.id).limit(1).correlate(Product).scalar_subquery())


def effective_price():
    return func.coalesce(Product.sale_price_usd, Product.price_usd)


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search_products(db: DbSession, *, q: str | None = None, category_id: int | None = None,
                    min_price: Decimal | None = None, max_price: Decimal | None = None, in_stock: bool = False,
                    on_sale: bool = False, featured: bool = False, sort: str = "relevance", page: int = 1,
                    page_size: int = 24, public: bool = True, status: str | None = None):
    avail, img = available_expr().label("available"), image_expr().label("image_url")
    conds = []
    if public:
        conds += [Product.status == "published",
                  Product.category_id.in_(select(Category.id).where(Category.is_active.is_(True)))]
    elif status:
        conds.append(Product.status == status)
    if category_id:
        conds.append(Product.category_id.in_(category_and_descendants(db, category_id)))
    if min_price is not None:
        conds.append(effective_price() >= min_price)
    if max_price is not None:
        conds.append(effective_price() <= max_price)
    if on_sale:
        conds.append(Product.sale_price_usd.is_not(None))
    if featured:
        conds.append(Product.is_featured.is_(True))
    score = None
    if q and q.strip():
        pat = _like(q.strip())
        conds.append(or_(Product.name.ilike(pat, escape="\\"), Product.brand.ilike(pat, escape="\\"),
                         Product.short_description.ilike(pat, escape="\\"), Product.description.ilike(pat, escape="\\"),
                         Product.sku.ilike(pat, escape="\\")))
        score = (case((Product.name.ilike(pat, escape="\\"), 3), else_=0)
                 + case((Product.brand.ilike(pat, escape="\\"), 2), else_=0)
                 + case((or_(Product.short_description.ilike(pat, escape="\\"),
                             Product.description.ilike(pat, escape="\\")), 1), else_=0))
    base = select(Product.id).where(and_(*conds)) if conds else select(Product.id)
    if in_stock:
        stmt_ids = select(Product.id).where(and_(*conds), available_expr() > 0)
    else:
        stmt_ids = base
    total = db.scalar(select(func.count()).select_from(stmt_ids.subquery())) or 0
    stmt = select(Product, avail, img).where(Product.id.in_(stmt_ids))
    if sort == "price_asc":
        stmt = stmt.order_by(effective_price().asc(), Product.id)
    elif sort == "price_desc":
        stmt = stmt.order_by(effective_price().desc(), Product.id)
    elif sort == "newest" or score is None:
        stmt = stmt.order_by(Product.created_at.desc(), Product.id.desc())
    else:
        stmt = stmt.order_by(score.desc(), Product.created_at.desc())
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return rows, total


def card(p: Product, available: int, image_url: str | None) -> dict:
    return {"id": p.id, "slug": p.slug, "name": p.name, "brand": p.brand, "category_id": p.category_id,
            "price_usd": p.price_usd, "sale_price_usd": p.sale_price_usd,
            "effective_price_usd": p.sale_price_usd if p.sale_price_usd is not None else p.price_usd,
            "available": int(available), "in_stock": int(available) > 0, "image_url": image_url,
            "status": p.status, "sku": p.sku}


def variant_prices(p: Product, v) -> tuple[Decimal, Decimal | None]:
    """(precio de lista, precio de oferta|None). Fuente única para vitrina y carrito."""
    if v is not None and (v.price_usd is not None or v.sale_price_usd is not None):
        return (v.price_usd if v.price_usd is not None else p.price_usd), v.sale_price_usd
    return p.price_usd, p.sale_price_usd


def unit_price(p: Product, v=None) -> Decimal:
    lst, sale = variant_prices(p, v)
    return sale if sale is not None else lst
