"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  CircleUserRound,
  HelpCircle,
  Home,
  Info,
  LogOut,
  MapPinned,
  Menu,
  PackageCheck,
  ShieldCheck,
  ShoppingBag,
  X,
} from "lucide-react";
import { CitySelector, readSavedCityId, saveSelectedCityId } from "@/components/CitySelector";
import { fetchCities, logoutSession } from "@/shared/api/endpoints";
import type { City } from "@/shared/api/types";
import { useAuth } from "@/shared/auth/auth-context";

const nav = [
  { href: "/", label: "Главная", icon: Home },
  { href: "/catalog", label: "Каталог", icon: ShoppingBag },
  { href: "/lockers", label: "Карта постаматов", icon: MapPinned },
  { href: "/faq", label: "FAQ", icon: HelpCircle },
  { href: "/about", label: "О нас", icon: Info },
];

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthed, clearSession, session } = useAuth();
  const [cities, setCities] = useState<City[]>([]);
  const [cityId, setCityId] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    let active = true;
    fetchCities()
      .then((items) => {
        if (!active) {
          return;
        }
        setCities(items);
        const saved = readSavedCityId();
        const next = saved && items.some((city) => city.id === saved) ? saved : items[0]?.id || "";
        setCityId(next);
        if (next) {
          saveSelectedCityId(next);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  async function handleLogout() {
    try {
      await logoutSession();
    } catch {
      // Local logout is enough when access token is already expired.
    }
    clearSession();
    router.push("/");
  }

  return (
    <>
      <header className="app-header">
        <div className="container app-header-inner">
          <Link className="brand" href="/" aria-label="Postamats">
            <span className="brand-mark">
              <ShieldCheck size={21} strokeWidth={2.6} />
            </span>
            <span>Postamats</span>
          </Link>

          <nav className="desktop-nav" aria-label="Основная навигация">
            {nav.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  className={isActive(pathname, item.href) ? "is-active" : ""}
                  href={item.href}
                >
                  <Icon size={17} />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="header-actions">
            <CitySelector cities={cities} value={cityId} onChange={setCityId} compact />
            {isAuthed ? (
              <>
                <Link className="button button-secondary header-profile" href="/profile">
                  <CircleUserRound size={18} />
                  {session?.user?.phone || "Профиль"}
                </Link>
                <button
                  className="button button-ghost icon-button"
                  type="button"
                  onClick={handleLogout}
                  aria-label="Выйти"
                >
                  <LogOut size={18} />
                </button>
              </>
            ) : (
              <Link className="button button-primary header-login" href="/login">
                Войти
              </Link>
            )}
            <button
              className="button button-secondary menu-button"
              type="button"
              onClick={() => setMenuOpen((value) => !value)}
              aria-label={menuOpen ? "Закрыть меню" : "Открыть меню"}
            >
              {menuOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </div>

        <div className={`mobile-nav-panel ${menuOpen ? "is-open" : ""}`}>
          <nav className="container mobile-nav-grid" aria-label="Мобильная навигация">
            {nav.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  className={isActive(pathname, item.href) ? "is-active" : ""}
                  href={item.href}
                >
                  <Icon size={18} />
                  {item.label}
                </Link>
              );
            })}
            <Link href="/profile/orders">
              <PackageCheck size={18} />
              Мои заказы
            </Link>
          </nav>
        </div>
      </header>
    </>
  );
}
