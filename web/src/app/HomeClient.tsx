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
  ShieldCheck,
} from "lucide-react";
import { CategoryTabs } from "@/components/CategoryTabs";
import {
  CitySelector,
  readSavedCityId,
  resolveSelectedCityId,
  saveSelectedCityId,
  useCitySync,
} from "@/components/CitySelector";
import { EmptyState } from "@/components/EmptyState";
import { LockerCard } from "@/components/LockerCard";
import { PageChrome } from "@/components/PageChrome";
import { ProductCard } from "@/components/ProductCard";
import { YandexMap } from "@/components/YandexMap";
import {
  fetchAllLockers,
  fetchCities,
  fetchFeaturedProduct,
  fetchLockers,
  fetchProducts,
} from "@/shared/api/endpoints";
import type { City, FeaturedProduct, Locker, ProductListItem } from "@/shared/api/types";
import { benefits, faqItems, workflowSteps } from "@/shared/content";
import { formatCountRu, formatMoney, pluralizeRu } from "@/shared/format";
import { resolvePublicAssetUrl } from "@/shared/media";

function categoryLabel(product: ProductListItem, index: number) {
  const byName = product.categoryName?.trim();
  if (byName) {
    return byName;
  }

  const compact = product.categoryId.replace(/[-_]/g, " ").trim();
  if (!compact || /^[a-f0-9 -]{16,}$/i.test(compact)) {
    return `Категория ${index + 1}`;
  }

  return compact.charAt(0).toUpperCase() + compact.slice(1);
}

export function HomeClient() {
  const [cities, setCities] = useState<City[]>([]);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [lockers, setLockers] = useState<Locker[]>([]);
  const [allLockers, setAllLockers] = useState<Locker[]>([]);
  const [productOfDay, setProductOfDay] = useState<ProductListItem | null>(null);
  const [productOfDayDate, setProductOfDayDate] = useState("");
  const [selectedCityId, setSelectedCityId] = useState("");
  const [selectedLockerId, setSelectedLockerId] = useState("");
  const [previewCategoryId, setPreviewCategoryId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selectedCity = useMemo(
    () => cities.find((city) => city.id === selectedCityId) ?? cities[0],
    [cities, selectedCityId],
  );
  const selectedLocker = useMemo(
    () => lockers.find((locker) => locker.id === selectedLockerId) ?? lockers[0],
    [lockers, selectedLockerId],
  );
  const lockerPreviewItems = useMemo(() => {
    if (!lockers.length) {
      return [];
    }
    const leadLocker = selectedLocker ?? lockers[0];
    return [leadLocker, ...lockers.filter((locker) => locker.id !== leadLocker.id)].slice(0, 3);
  }, [lockers, selectedLocker]);
  const featuredProductCoverUrl = resolvePublicAssetUrl(productOfDay?.coverUrl);
  const previewCategories = useMemo(
    () => [
      { id: "", label: "Все" },
      ...Array.from(
        new Map(
          products
            .filter((product) => product.categoryId)
            .map((product, index) => [product.categoryId, categoryLabel(product, index)]),
        ),
      ).map(([id, label], index) => ({ id, label: label || `Категория ${index + 1}` })),
    ],
    [products],
  );
  const previewProducts = useMemo(() => {
    const items = previewCategoryId ? products.filter((product) => product.categoryId === previewCategoryId) : products;
    return items.slice(0, 6);
  }, [previewCategoryId, products]);

  useCitySync(cities, selectedCityId, setSelectedCityId);

  useEffect(() => {
    let active = true;
    fetchCities()
      .then((items) => {
        if (!active) {
          return;
        }
        setCities(items);
        const next = resolveSelectedCityId(items, readSavedCityId());
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
    let active = true;
    fetchAllLockers()
      .then((items) => {
        if (!active) {
          return;
        }
        setAllLockers(items);
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setAllLockers([]);
      });
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
      fetchFeaturedProduct(selectedCityId).catch(() => null),
    ])
      .then(([productItems, lockerItems, featuredProduct]) => {
        if (!active) {
          return;
        }
        setProducts(productItems);
        setLockers(lockerItems);
        setSelectedLockerId((current) =>
          current && lockerItems.some((locker) => locker.id === current) ? current : lockerItems[0]?.id || "",
        );
        const featured = featuredProduct as FeaturedProduct | null;
        setProductOfDay(featured?.product ?? null);
        setProductOfDayDate(featured?.activeDate ?? "");
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

  const totalLockerCount = allLockers.length || lockers.length;
  const heroHighlights = [
    {
      icon: MapPinned,
      label: cities.length ? formatCountRu(cities.length, ["город", "города", "городов"]) : "города загружаются",
    },
    {
      icon: PackageSearch,
      label: totalLockerCount
        ? formatCountRu(totalLockerCount, ["постамат", "постамата", "постаматов"])
        : "ищем постаматы",
    },
    {
      icon: ShieldCheck,
      label: "Код после оплаты",
    },
  ];

  const stats = [
    {
      label: pluralizeRu(cities.length, ["город", "города", "городов"]),
      value: cities.length || "—",
    },
    {
      label: pluralizeRu(totalLockerCount, ["постамат", "постамата", "постаматов"]),
      value: totalLockerCount,
    },
    { label: "пользователей", value: "5k+" },
    { label: "часов аренды", value: "45k+" },
  ];

  return (
    <PageChrome compact>
      <section className="hero-service">
        <div className="hero-service-copy">
          <p className="eyebrow">Аренда через постаматы</p>
          <h1>Бери нужное на время. Не покупай лишнее.</h1>
          <div className="hero-service-summary">
            <p className="hero-service-description">
              Техника, инструменты и вещи для дома доступны в постаматах рядом с
              вами: выберите товар, точку, срок аренды и получите код после оплаты.
            </p>
            <div className="hero-service-highlights" aria-label="Ключевые преимущества сервиса">
              {heroHighlights.map((item) => {
                const Icon = item.icon;
                return (
                  <span key={item.label}>
                    <Icon size={14} />
                    {item.label}
                  </span>
                );
              })}
            </div>
          </div>
          <div className="hero-service-cta">
            <Link className="button button-primary" href="/catalog">
              Начать аренду
              <ArrowRight size={18} />
            </Link>
          </div>
        </div>

        <div className="hero-dashboard" aria-label="Сценарий аренды">
          <p className="hero-dashboard-label">Товар дня рядом с вами</p>
          <article className="product-of-day-card">
            <div className="product-of-day-media">
              {featuredProductCoverUrl ? (
                <img src={featuredProductCoverUrl} alt={productOfDay?.name || "Товар дня"} />
              ) : (
                <ImageIcon size={54} />
              )}
                <span title={productOfDayDate ? `Обновлено: ${productOfDayDate}` : undefined}>
                Товар дня
              </span>
            </div>
            <div className="product-of-day-copy">
              <p className="eyebrow">{productOfDay?.brand || "Подборка из каталога"}</p>
              <h2>{productOfDay?.name || "Товар дня появится после загрузки каталога"}</h2>
              <p>
                {productOfDay?.shortDescription ||
                  "Собрали заметную позицию из каталога, чтобы вы могли сразу выбрать ближайшую точку получения."}
              </p>
            </div>
            <div className="product-of-day-meta">
              <span>
                <PackageSearch size={16} />
                {productOfDay
                  ? formatCountRu(productOfDay.availableLockerCount, [
                      "постамат",
                      "постамата",
                      "постаматов",
                    ])
                  : "ищем наличие"}
              </span>
              <span>
                <MapPinned size={16} />
                {selectedLocker?.address || selectedCity?.name || "выберите город"}
              </span>
            </div>
            <div className="product-of-day-bottom">
              <strong>
                {productOfDay
                  ? `от ${formatMoney(productOfDay.priceFrom, productOfDay.currency)}`
                  : "цена после загрузки"}
              </strong>
              <Link
                className="button button-primary product-of-day-action"
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
        <div className="catalog-preview-heading">
          <div>
            <p className="eyebrow">Каталог</p>
            <h2 className="section-heading">Популярное в аренду</h2>
          </div>
        </div>

        <div className="catalog-filter-panel catalog-filter-panel-home">
          <div className="catalog-filter-city">
            <MapPinned size={16} />
            <CitySelector cities={cities} value={selectedCityId} onChange={setSelectedCityId} compact />
          </div>
          <CategoryTabs categories={previewCategories} activeId={previewCategoryId} onChange={setPreviewCategoryId} />
        </div>

        {error ? <div className="alert alert-danger">{error}</div> : null}

        {loading ? (
          <div className="skeleton-grid">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="skeleton-card" key={index} />
            ))}
          </div>
        ) : previewProducts.length ? (
          <>
            <div className="product-grid">
              {previewProducts.map((product) => (
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
            title={previewCategoryId ? "В этой категории пока нет товаров" : "Каталог пока пуст"}
            text={
              previewCategoryId
                ? "Сбросьте категорию или откройте весь каталог, чтобы посмотреть другие позиции."
                : "Когда товары появятся в выбранном городе, они отобразятся здесь."
            }
            action={
              previewCategoryId ? (
                <button className="button button-secondary" type="button" onClick={() => setPreviewCategoryId("")}>
                  Показать всё
                </button>
              ) : undefined
            }
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
            <YandexMap
              lockers={lockers}
              selectedLockerId={selectedLockerId}
              onSelectLocker={setSelectedLockerId}
            />
            <div className="locker-list">
              {lockerPreviewItems.map((locker) => (
                <LockerCard
                  key={locker.id}
                  locker={locker}
                  selected={selectedLockerId === locker.id}
                  onSelect={setSelectedLockerId}
                  showAction
                />
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
            Все шаги аренды собраны в одном понятном сценарии: от выбора товара до
            получения кода и возврата через постамат.
          </p>
        </div>
      </section>
    </PageChrome>
  );
}
