"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
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
  ShoppingBag,
  X,
} from "lucide-react";
import {
  CitySelector,
  readSavedCityId,
  resolveSelectedCityId,
  saveSelectedCityId,
  useCitySync,
} from "@/components/CitySelector";
import { fetchCities, logoutSession } from "@/shared/api/endpoints";
import type { City } from "@/shared/api/types";
import { useAuth } from "@/shared/auth/auth-context";

const nav = [
  {
    href: "/",
    label: "Главная",
    icon: Home,
    group: "main",
  },
  {
    href: "/catalog",
    label: "Каталог",
    icon: ShoppingBag,
    group: "main",
  },
  {
    href: "/lockers",
    label: "Постаматы",
    icon: MapPinned,
    group: "main",
  },
  {
    href: "/faq",
    label: "FAQ",
    icon: HelpCircle,
    group: "service",
  },
  {
    href: "/about",
    label: "О сервисе",
    icon: Info,
    group: "service",
  },
] as const;

const ordersNavItem = {
  href: "/profile/orders",
  label: "Мои заказы",
  icon: PackageCheck,
} as const;

const mainNav = nav.filter((item) => item.group === "main");
const serviceNav = nav.filter((item) => item.group === "service");

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
  const selectedCity = cities.find((item) => item.id === cityId);
  const desktopLinks = isAuthed ? [...nav, ordersNavItem] : nav;

  useCitySync(cities, cityId, setCityId);

  useEffect(() => {
    let active = true;
    fetchCities()
      .then((items) => {
        if (!active) {
          return;
        }
        setCities(items);
        const next = resolveSelectedCityId(items, readSavedCityId());
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

  useEffect(() => {
    if (!menuOpen) {
      return;
    }

    const scrollY = window.scrollY;
    const previousBodyOverflow = document.body.style.overflow;
    const previousBodyPosition = document.body.style.position;
    const previousBodyTop = document.body.style.top;
    const previousBodyLeft = document.body.style.left;
    const previousBodyRight = document.body.style.right;
    const previousBodyWidth = document.body.style.width;
    const previousHtmlOverflow = document.documentElement.style.overflow;

    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    document.body.style.position = "fixed";
    document.body.style.top = `-${scrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.documentElement.style.overflow = previousHtmlOverflow;
      document.body.style.overflow = previousBodyOverflow;
      document.body.style.position = previousBodyPosition;
      document.body.style.top = previousBodyTop;
      document.body.style.left = previousBodyLeft;
      document.body.style.right = previousBodyRight;
      document.body.style.width = previousBodyWidth;
      window.scrollTo(0, scrollY);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  async function handleLogout() {
    setMenuOpen(false);
    try {
      await logoutSession();
    } catch {
      // Local logout is enough when access token is already expired.
    }
    clearSession();
    router.push("/");
  }

  const mobileLinks = [...mainNav, ...serviceNav, ordersNavItem] as const;

  return (
    <>
      <header className="app-header">
        <div className="container app-header-inner">
          <Link className="brand" href="/" aria-label="naprokatberu">
            <span className="brand-mark">
              <Image src="/naprokatberu-logo.png" alt="" width={44} height={44} />
            </span>
            <span>naprokatberu</span>
          </Link>

          <nav className="desktop-nav" aria-label="Основная навигация">
            {desktopLinks.map((item) => {
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
            <div className="header-city-control">
              <CitySelector cities={cities} value={cityId} onChange={setCityId} compact />
            </div>
            {isAuthed ? (
              <>
                <Link className="button button-secondary header-profile" href="/profile">
                  <CircleUserRound size={18} />
                  {session?.user?.phone || "Профиль"}
                </Link>
                <button
                  className="button button-ghost icon-button header-logout"
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
              aria-expanded={menuOpen}
              aria-controls="mobile-nav-panel"
            >
              {menuOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </div>

        {menuOpen ? (
          <div
            className="mobile-nav-overlay"
            role="presentation"
            onClick={() => setMenuOpen(false)}
          >
            <div className="mobile-nav-shell">
              <div
                id="mobile-nav-panel"
                className="mobile-nav-panel is-open"
                role="dialog"
                aria-modal="true"
                aria-label="Мобильная навигация"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="mobile-nav-head">
                  <Link className="mobile-nav-brand" href="/" aria-label="naprokatberu">
                    <span className="brand-mark">
                      <Image src="/naprokatberu-logo.png" alt="" width={38} height={38} />
                    </span>
                    <span>
                      <strong>naprokatberu</strong>
                      <small>Аренда рядом с вами</small>
                    </span>
                  </Link>
                  <button
                    className="button button-ghost icon-button mobile-nav-close"
                    type="button"
                    onClick={() => setMenuOpen(false)}
                    aria-label="Закрыть меню"
                  >
                    <X size={18} />
                  </button>
                </div>

                <nav className="mobile-nav-simple" aria-label="Мобильная навигация">
                  {mobileLinks.map((item) => {
                    const Icon = item.icon;
                    return (
                      <Link
                        key={item.href}
                        className={isActive(pathname, item.href) ? "is-active" : ""}
                        href={item.href}
                      >
                        <Icon size={18} />
                        <span>{item.label}</span>
                      </Link>
                    );
                  })}
                </nav>

                <div className="mobile-nav-foot">
                  <div className="mobile-nav-city-card mobile-nav-city-card-simple">
                    <div className="mobile-nav-city-copy">
                      <span className="mobile-nav-section-label">Город</span>
                      <strong>{selectedCity?.name || "Выберите город"}</strong>
                    </div>
                    <CitySelector cities={cities} value={cityId} onChange={setCityId} compact />
                  </div>

                  {isAuthed ? (
                    <>
                      <Link className="mobile-nav-account-link" href="/profile">
                        <CircleUserRound size={18} />
                        <span>{session?.user?.phone || "Профиль"}</span>
                      </Link>
                      <div className="mobile-nav-foot-actions">
                        <button
                          className="button button-ghost"
                          type="button"
                          onClick={handleLogout}
                        >
                          <LogOut size={18} />
                          Выйти
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="mobile-nav-foot-actions mobile-nav-foot-actions-single">
                      <Link className="button button-primary" href="/login">
                        Войти
                      </Link>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </header>
    </>
  );
}
