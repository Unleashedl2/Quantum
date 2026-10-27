import { Navigate, Route, Routes } from "react-router-dom";
import Header from "./components/Header";
import Footer from "./components/Footer";
import { useAuth } from "./auth";
import Home from "./pages/Home";
import Catalog from "./pages/Catalog";
import ProductPage from "./pages/ProductPage";
import { Login, Register, ChangePassword } from "./pages/AuthPages";
import AdminCatalog from "./pages/AdminCatalog";
import CartPage from "./pages/CartPage";
import Notifications from "./pages/Notifications";
import AdminPayments from "./pages/AdminPayments";
import AdminBanks from "./pages/AdminBanks";
import Checkout from "./pages/Checkout";
import { OrdersList, OrderDetail } from "./pages/Orders";

export default function App() {
  const { me } = useAuth();
  if (me?.must_change_password) {   // contraseña temporal: solo se permite cambiarla
    return <><Header /><main className="wrap"><ChangePassword forced /></main></>;
  }
  return (
    <>
      <Header />
      <main className="wrap">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/productos" element={<Catalog />} />
          <Route path="/producto/:slug" element={<ProductPage />} />
          <Route path="/ingresar" element={<Login />} />
          <Route path="/registro" element={<Register />} />
          <Route path="/cambiar-clave" element={<ChangePassword />} />
          <Route path="/carrito" element={<CartPage />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/pedidos" element={<OrdersList />} />
          <Route path="/pedidos/:number" element={<OrderDetail />} />
          <Route path="/notificaciones" element={<Notifications />} />
          <Route path="/admin/pagos" element={<AdminPayments />} />
          <Route path="/admin/bancos" element={<AdminBanks />} />
          <Route path="/admin/catalogo" element={<AdminCatalog />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Footer />
    </>
  );
}
