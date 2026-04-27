"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Boxes,
  ImageIcon,
  HelpCircle,
  MapPinned,
  PackageSearch,
  Search,
  ShieldCheck,
} from "lucide-react";
import { CategoryTabs } from "@/components/CategoryTabs";
import { CitySelector, readSavedCityId, saveSelectedCityId } from "@/components/CitySelector";
import { EmptyState } from "@/components/EmptyState";
import { LockerCard } from "@/components/LockerCard";
import { PageChrome } from "@/components/PageChrome";
import { ProductCard } from "@/components/ProductCard";
import { fetchCities, fetchLockers, fetchProducts } from "@/shared/api/endpoints";
import type { City, Locker, ProductListItem } from "@/shared/api/types";
import { benefits, faqItems, productCategories, workflowSteps } from "@/shared/content";
import { formatMoney } from "@/shared/format";

export function HomeClient() {
  const [cities, setCities] = useState<City[]>([]);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [lockers, setLockers] = useState<Locker[]>([]);
  const [productOfDay, setProductOfDay] = useState<ProductListItem | null>(null);
  const [selectedCityId, setSelectedCityId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selectedCity = useMemo(
    () => cities.find((city) => city.id === selectedCityId) ?? cities[0],
    [cities, selectedCityId],
  );
  const featuredLocker = lockers[0];

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
        setSelectedCityId(next);
        if (next) {
          saveSelectedCityId(next);
        }
      })
      .catch(() => setError("Не удалось загрузить города. Попробуйте обновить страницу."));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedCityId) {
      setProducts([]);
      setLockers([]);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    setError("");
    Promise.all([
      fetchProducts({ cityId: selectedCityId, availableOnly: true, limit: 9 }),
      fetchLockers(selectedCityId),
    ])
      .then(([productItems, lockerItems]) => {
        if (!active) {
          return;
        }
        setProducts(productItems);
        setLockers(lockerItems);
        setProductOfDay(
          productItems.length
            ? productItems[Math.floor(Math.random() * productItems.length)]
            : null,
        );
      })
      .catch(() => {
        if (active) {
          setError("Не удалось загрузить каталог. Попробуйте обновить страницу.");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [selectedCityId]);

  const stats = [
    { label: "городов", value: cities.length || "—" },
    { label: "постаматов", value: lockers.length },
    // TODO: заменить на публичный endpoint статистики, когда он появится в backend.
    { label: "пользователей", value: "5k+" },
    { label: "часов аренды", value: "45k+" },
  ];

  return (
    <PageChrome compact>
      <section className="hero-service">
        <div className="hero-service-copy">
          <p className="eyebrow">Аренда через постаматы</p>
          <h1>Бери нужное на время. Не покупай лишнее.</h1>
          <p>
            Техника, инструменты и вещи для дома доступны в постаматах рядом с
            вами: выберите товар, точку, срок аренды и получите код после оплаты.
          </p>
          <div className="hero-service-actions">
            <Link className="button button-primary" href="/catalog">
              Начать аренду
              <ArrowRight size={18} />
            </Link>
            <Link className="button button-secondary" href="/lockers">
              Смотреть постаматы
            </Link>
          </div>
          <div className="hero-search-panel">
            <Search size={18} />
            <span>{selectedCity?.name || "Выберите город"} · каталог, наличие и цена</span>
          </div>
        </div>

        <div className="hero-dashboard" aria-label="Сценарий аренды">
          <article className="product-of-day-card">
            <div className="product-of-day-media">
              {productOfDay?.coverUrl ? (
                <img src={productOfDay.coverUrl} alt={productOfDay.name} />
              ) : (
                <ImageIcon size={54} />
              )}
              <span>Товар дня</span>
            </div>
            <div>
              <p className="eyebrow">{productOfDay?.brand || "Подборка из каталога"}</p>
              <h2>{productOfDay?.name || "Товар дня появится после загрузки каталога"}</h2>
              <p>
                {productOfDay?.shortDescription ||
                  "Берем случайную доступную позицию из базы и показываем быстрый путь к ближайшим постаматам."}
              </p>
            </div>
            <div className="product-of-day-meta">
              <span>
                <PackageSearch size={16} />
                {productOfDay ? `${productOfDay.availableLockerCount} постаматов` : "ищем наличие"}
              </span>
              <span>
                <MapPinned size={16} />
                {featuredLocker?.address || selectedCity?.name || "выберите город"}
              </span>
            </div>
            <div className="product-of-day-bottom">
              <strong>
                {productOfDay
                  ? `от ${formatMoney(productOfDay.priceFrom, productOfDay.currency)}`
                  : "цена после загрузки"}
              </strong>
              <Link
                className="button button-primary"
                href={productOfDay ? `/catalog/${productOfDay.slug || productOfDay.id}` : "/catalog"}
              >
                Найти поблизости
              </Link>
            </div>
          </article>
        </div>
      </section>

      <section className="stats-grid" aria-label="Статистика сервиса">
        {stats.map((item) => (
          <article className="stat-card" key={item.label}>
            <strong>{item.value}</strong>
            <span>{item.label}</span>
          </article>
        ))}
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Почему удобно</p>
          <h2 className="section-heading">Вещь появляется тогда, когда она действительно нужна</h2>
        </div>
        <div className="benefit-grid">
          {benefits.map((item) => {
            const Icon = item.icon;
            return (
              <article className="benefit-card" key={item.title}>
                <span className="icon-badge">
                  <Icon size={20} />
                </span>
                <strong>{item.title}</strong>
                <p>{item.text}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Как это работает</p>
          <h2 className="section-heading">От выбора до возврата без лишних шагов</h2>
        </div>
        <div className="workflow-grid">
          {workflowSteps.map((item, index) => {
            const Icon = item.icon;
            return (
              <article className="workflow-card" key={item.title}>
                <span className="workflow-index">{index + 1}</span>
                <Icon size={24} />
                <strong>{item.title}</strong>
                <p>{item.text}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="section-band" id="catalog-preview">
        <div className="toolbar">
          <div>
            <p className="eyebrow">Каталог</p>
            <h2 className="section-heading">Популярное в аренду</h2>
            <p className="muted">Город: {selectedCity?.name || "не выбран"}</p>
          </div>
          <CitySelector cities={cities} value={selectedCityId} onChange={setSelectedCityId} />
        </div>

        <CategoryTabs categories={productCategories} activeId="" onChange={() => undefined} />

        {error ? <div className="alert alert-danger">{error}</div> : null}

        {loading ? (
          <div className="skeleton-grid">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="skeleton-card" key={index} />
            ))}
          </div>
        ) : products.length ? (
          <>
            <div className="product-grid">
              {products.slice(0, 6).map((product) => (
                <ProductCard key={product.id} product={product} />
              ))}
            </div>
            <div className="section-cta">
              <Link className="button button-dark" href="/catalog">
                Открыть весь каталог
              </Link>
            </div>
          </>
        ) : (
          <EmptyState
            icon={<Boxes size={34} />}
            title="Каталог пока пуст"
            text="Когда товары появятся в выбранном городе, они отобразятся здесь."
          />
        )}
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Постаматы</p>
          <h2 className="section-heading">Выберите точку по адресу и наличию</h2>
        </div>
        {lockers.length ? (
          <div className="locker-preview-grid">
            <div className="map-preview">
              <div className="map-grid-lines" />
              <span className="map-pin map-pin-a" />
              <span className="map-pin map-pin-b" />
              <span className="map-pin map-pin-c" />
              <div className="map-preview-card">
                <MapPinned size={18} />
                <strong>{lockers.length} точек в городе</strong>
              </div>
            </div>
            <div className="locker-list">
              {lockers.slice(0, 3).map((locker) => (
                <LockerCard key={locker.id} locker={locker} showAction />
              ))}
            </div>
          </div>
        ) : (
          <EmptyState
            icon={<MapPinned size={34} />}
            title="Постаматы не найдены"
            text="Попробуйте другой город или вернитесь позже."
          />
        )}
      </section>

      <section className="section-band faq-preview">
        <div className="surface faq-preview-card">
          <div>
            <p className="eyebrow">FAQ</p>
            <h2 className="section-heading">Перед первой арендой</h2>
          </div>
          <div className="faq-preview-list">
            {faqItems.slice(0, 5).map((item) => (
              <Link href="/faq" key={item.question}>
                <HelpCircle size={17} />
                {item.question}
              </Link>
            ))}
          </div>
          <Link className="button button-secondary" href="/faq">
            Все вопросы
          </Link>
        </div>
        <div className="surface support-card">
          <ShieldCheck size={30} />
          <h2 className="section-title">Оформление под контролем</h2>
          <p>
            Авторизация, верификация, резерв, оплата и код получения уже разделены
            в интерфейсе, чтобы backend можно было подключать без переделки сценария.
          </p>
        </div>
      </section>
    </PageChrome>
  );
}
