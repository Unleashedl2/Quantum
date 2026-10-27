from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from app.models import Cart, CartItem, Category, Inventory, Product, ProductImage, ProductVariant, User
from app.services import catalog as cat


class ShopError(Exception):
    def __init__(self, message: str, status: int = 400, issues: list | None = None):
        self.message, self.status, self.issues = message, status, issues or []


def get_cart(db: DbSession, user: User) -> Cart:
    c = db.scalar(select(Cart).where(Cart.user_id == user.id))
    if not c:
        c = Cart(user_id=user.id)
        db.add(c)
        try:
            db.flush()
        except IntegrityError:        # dos pestañas creando el carrito a la vez
            db.rollback()
            c = db.scalar(select(Cart).where(Cart.user_id == user.id))
    return c


def load_context(db: DbSession, items: list[CartItem]) -> dict:
    pids = {i.product_id for i in items}
    vids = {i.variant_id for i in items if i.variant_id}
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(pids)))} if pids else {}
    variants = {v.id: v for v in db.scalars(select(ProductVariant).where(ProductVariant.id.in_(vids)))} if vids else {}
    active_cats = set(db.scalars(select(Category.id).where(Category.is_active.is_(True),
                                                           Category.id.in_({p.category_id for p in products.values()})))) if products else set()
    avail = {}
    if pids:
        for r in db.scalars(select(Inventory).where(Inventory.product_id.in_(pids))):
            avail[(r.product_id, r.variant_id)] = r.quantity_on_hand - r.quantity_reserved
    images: dict[int, str] = {}
    if pids:
        for im in db.scalars(select(ProductImage).where(ProductImage.product_id.in_(pids))
                             .order_by(ProductImage.sort_order, ProductImage.id)):
            images.setdefault(im.product_id, im.url)
    return {"products": products, "variants": variants, "active_cats": active_cats, "avail": avail, "images": images}


def line_issue(ctx: dict, item: CartItem, avail: int) -> str | None:
    p = ctx["products"].get(item.product_id)
    v = ctx["variants"].get(item.variant_id) if item.variant_id else None
    if (not p or p.status != "published" or p.category_id not in ctx["active_cats"]
            or (item.variant_id and (not v or v.product_id != p.id or not v.is_active))):
        return "unavailable"
    if avail <= 0:
        return "out_of_stock"
    if item.quantity > avail:
        return "insufficient_stock"
    return None


def build_view(db: DbSession, cart: Cart) -> dict:
    items = db.scalars(select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)).all()
    ctx = load_context(db, items)
    lines, subtotal = [], Decimal("0.00")
    for it in items:
        p, v = ctx["products"].get(it.product_id), ctx["variants"].get(it.variant_id) if it.variant_id else None
        avail = max(0, ctx["avail"].get((it.product_id, it.variant_id), 0))
        issue = line_issue(ctx, it, avail)
        unit = cat.unit_price(p, v) if p else Decimal("0.00")
        total = unit * it.quantity
        if issue is None:
            subtotal += total
        lines.append({"id": it.id, "product_id": it.product_id, "variant_id": it.variant_id,
                      "name": p.name if p else "Producto no disponible", "slug": p.slug if p else None,
                      "sku": (v.sku if v else p.sku) if p else None,
                      "variant_label": " / ".join(v.attributes.values()) if v else None,
                      "image_url": ctx["images"].get(it.product_id), "unit_price_usd": unit, "quantity": it.quantity,
                      "line_total_usd": total, "available": avail, "issue": issue})
    return {"items": lines, "subtotal_usd": subtotal, "item_count": sum(i.quantity for i in items),
            "has_issues": any(l["issue"] for l in lines)}


def add_item(db: DbSession, user: User, product_id: int, variant_id: int | None, qty: int) -> None:
    p = db.get(Product, product_id)
    if not p or p.status != "published":
        raise ShopError("Producto no disponible", 404)
    c = db.get(Category, p.category_id)
    if not c or not c.is_active:
        raise ShopError("Producto no disponible", 404)
    active_variants = db.scalars(select(ProductVariant).where(ProductVariant.product_id == p.id,
                                                              ProductVariant.is_active.is_(True))).all()
    if active_variants and variant_id is None:
        raise ShopError("Selecciona una variante antes de añadir al carrito")
    if variant_id is not None and variant_id not in {v.id for v in active_variants}:
        raise ShopError("La variante seleccionada no existe", 400)
    inv = db.scalar(select(Inventory).where(Inventory.product_id == p.id,
                                            Inventory.variant_id == variant_id if variant_id else Inventory.variant_id.is_(None)))
    avail = max(0, (inv.quantity_on_hand - inv.quantity_reserved) if inv else 0)
    cart = get_cart(db, user)
    cond = CartItem.variant_id == variant_id if variant_id else CartItem.variant_id.is_(None)
    row = db.scalar(select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == p.id, cond))
    new_qty = (row.quantity if row else 0) + qty
    if new_qty > avail:
        raise ShopError(f"Solo hay {avail} unidades disponibles", 409)
    if row:
        row.quantity = new_qty
    else:
        db.add(CartItem(cart_id=cart.id, product_id=p.id, variant_id=variant_id, quantity=qty))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ShopError("No se pudo actualizar el carrito; inténtalo de nuevo", 409)


def _own_item(db: DbSession, user: User, item_id: int) -> CartItem:
    it = db.scalar(select(CartItem).join(Cart, Cart.id == CartItem.cart_id)
                   .where(CartItem.id == item_id, Cart.user_id == user.id))
    if not it:
        raise ShopError("Artículo no encontrado en tu carrito", 404)
    return it


def set_quantity(db: DbSession, user: User, item_id: int, qty: int) -> None:
    it = _own_item(db, user, item_id)
    if qty == 0:
        db.delete(it)
    else:
        inv = db.scalar(select(Inventory).where(Inventory.product_id == it.product_id,
                                                Inventory.variant_id == it.variant_id if it.variant_id else Inventory.variant_id.is_(None)))
        avail = max(0, (inv.quantity_on_hand - inv.quantity_reserved) if inv else 0)
        if qty > avail:
            raise ShopError(f"Solo hay {avail} unidades disponibles", 409)
        it.quantity = qty
    db.commit()


def remove_item(db: DbSession, user: User, item_id: int) -> None:
    db.delete(_own_item(db, user, item_id))
    db.commit()
