"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ChevronDown,
  ChevronRight,
  CircleUserRound,
  HelpCircle,
  Home,
  Lightbulb,
  LogOut,
  MapPin,
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
  },
  {
    href: "/catalog",
    label: "Каталог",
    icon: ShoppingBag,
  },
  {
    href: "/lockers",
    label: "Постаматы",
    icon: MapPinned,
  },
  {
    href: "/faq",
    label: "Вопрос-ответ",
    icon: HelpCircle,
  },
  {
    href: "/ideas",
    label: "Идея для аренды",
    icon: Lightbulb,
  },
] as const;

const ordersNavItem = {
  href: "/profile/orders",
  label: "Мои заказы",
  icon: PackageCheck,
} as const;

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
  const desktopLinks = isAuthed ? [...nav, ordersNavItem] : nav;
  const selectedCity = cities.find((item) => item.id === cityId);
  const userInitial = session?.user?.phone
    ? session.user.phone.replace(/\D/g, "").slice(-1)
    : "?";

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

  return (
    <>
      <div className="city-top-bar">
        <div className="container city-top-bar-inner">
          <div className="city-top-bar-location">
            <MapPin size={14} className="city-top-bar-icon" />
            <span className="city-top-bar-label">Ваш город:</span>
            <CitySelector cities={cities} value={cityId} onChange={setCityId} compact />
          </div>
          {isAuthed ? (
            <Link className="city-top-auth" href="/profile">
              <CircleUserRound size={14} />
              <span className="city-top-auth-phone">{session?.user?.phone}</span>
            </Link>
          ) : null}
        </div>
      </div>

      <header className="app-header">
        <div className="container app-header-inner">
          <Link className="brand" href="/" aria-label="naprokatberu">
            <span className="brand-mark">
              <Image src="/naprokatberu-logo.png" alt="" width={44} height={44} />
            </span>
            <span className="brand-copy">
              <strong>naprokatberu</strong>
              <small>Сервис аренды вещей</small>
            </span>
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
            <div className="header-mobile-city">
              <MapPin size={15} />
              <span className="header-mobile-city-name">
                {selectedCity?.name || "Город"}
              </span>
              <ChevronDown size={16} />
              <select
                className="header-mobile-city-select"
                value={cityId}
                onChange={(event) => {
                  setCityId(event.target.value);
                  saveSelectedCityId(event.target.value);
                }}
                aria-label="Выбор города"
              >
                {!cities.length ? <option value="">Выберите город</option> : null}
                {cities.map((city) => (
                  <option key={city.id} value={city.id}>
                    {city.name}
                  </option>
                ))}
              </select>
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
                <Link className="button button-secondary header-mobile-auth" href="/profile">
                  <CircleUserRound size={16} />
                  <span className="header-mobile-auth-phone">
                    {session?.user?.phone || "Кабинет"}
                  </span>
                </Link>
              </>
            ) : (
              <>
                <Link className="button button-primary header-login" href="/login">
                  Войти
                </Link>
                <Link className="button button-primary header-mobile-auth" href="/login">
                  Войти
                </Link>
              </>
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

      </header>

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
                      <Image src="/naprokatberu-logo.png" alt="" width={36} height={36} />
                    </span>
                    <span>
                      <strong>naprokatberu</strong>
                      <small>Сервис аренды вещей</small>
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

                <div className="mobile-nav-body">
                  {isAuthed && (
                    <Link className="mobile-nav-user-card" href="/profile">
                      <span className="mobile-nav-user-avatar">{userInitial}</span>
                      <span className="mobile-nav-user-info">
                        <span className="mobile-nav-user-label">Профиль</span>
                        <span className="mobile-nav-user-phone">{session?.user?.phone}</span>
                      </span>
                      <ChevronRight size={16} className="mobile-nav-user-arrow" />
                    </Link>
                  )}

                  <nav aria-label="Мобильная навигация">
                    <p className="mobile-nav-group-label">Навигация</p>
                    <div className="mobile-nav-group">
                      {nav.map((item) => {
                        const Icon = item.icon;
                        return (
                          <Link
                            key={item.href}
                            className={`mobile-nav-item${isActive(pathname, item.href) ? " is-active" : ""}`}
                            href={item.href}
                          >
                            <span className="mobile-nav-item-icon">
                              <Icon size={18} />
                            </span>
                            <span>{item.label}</span>
                          </Link>
                        );
                      })}
                      {isAuthed ? (
                        <Link
                          className={`mobile-nav-item${isActive(pathname, ordersNavItem.href) ? " is-active" : ""}`}
                          href={ordersNavItem.href}
                        >
                          <span className="mobile-nav-item-icon">
                            <PackageCheck size={18} />
                          </span>
                          <span>{ordersNavItem.label}</span>
                        </Link>
                      ) : null}
                    </div>
                  </nav>
                </div>

                <div className="mobile-nav-foot">
                  <div className="mobile-nav-city-row">
                    <span className="mobile-nav-city-label">
                      <MapPinned size={13} />
                      Город
                    </span>
                    <CitySelector cities={cities} value={cityId} onChange={setCityId} compact />
                  </div>

                  {isAuthed ? (
                    <button
                      className="button button-ghost mobile-nav-logout-btn"
                      type="button"
                      onClick={handleLogout}
                    >
                      <LogOut size={16} />
                      Выйти из аккаунта
                    </button>
                  ) : (
                    <Link className="button button-primary mobile-nav-login-btn" href="/login">
                      Войти
                    </Link>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : null}
    </>
  );
}
