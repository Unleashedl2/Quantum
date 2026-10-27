import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import { CartView } from "./types";

interface Ctx { cart: CartView | null; count: number; refresh(): Promise<void>; add(productId: number, variantId: number | null, qty: number): Promise<void>; setQty(itemId: number, qty: number): Promise<void> }
const CartCtx = createContext<Ctx>(null!);
export const useCart = () => useContext(CartCtx);

export function CartProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const [cart, setCart] = useState<CartView | null>(null);
  const refresh = useCallback(async () => {
    if (!me || me.must_change_password) { setCart(null); return; }
    try { setCart(await api<CartView>("/api/cart")); } catch { setCart(null); }
  }, [me]);
  useEffect(() => { refresh(); }, [refresh]);
  const add = async (productId: number, variantId: number | null, qty: number) => {
    setCart(await api<CartView>("/api/cart/items", { method: "POST", body: { product_id: productId, variant_id: variantId, quantity: qty } }));
  };
  const setQty = async (itemId: number, qty: number) => {
    setCart(qty === 0 ? await api<CartView>(`/api/cart/items/${itemId}`, { method: "DELETE" })
                      : await api<CartView>(`/api/cart/items/${itemId}`, { method: "PATCH", body: { quantity: qty } }));
  };
  return <CartCtx.Provider value={{ cart, count: cart?.item_count ?? 0, refresh, add, setQty }}>{children}</CartCtx.Provider>;
}
