"use client";

import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Boxes, MapPinned, PackageSearch, ShieldCheck } from "lucide-react";
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
  fetchLockers,
  fetchProducts,
  fetchPublicStats,
} from "@/shared/api/endpoints";
import type { City, Locker, ProductListItem } from "@/shared/api/types";
import { formatCountRu, pluralizeRu } from "@/shared/format";

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
  const [selectedCityId, setSelectedCityId] = useState("");
  const [selectedLockerId, setSelectedLockerId] = useState("");
  const [previewCategoryId, setPreviewCategoryId] = useState("");
  const [userCount, setUserCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
    const items = previewCategoryId
      ? products.filter((product) => product.categoryId === previewCategoryId)
      : products;
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
      .catch(() =>
        setError("Не удалось загрузить города. Попробуйте обновить страницу."),
      );
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
    let active = true;
    fetchPublicStats()
      .then((stats) => {
        if (active) {
          setUserCount(stats.users);
        }
      })
      .catch(() => {
        if (active) {
          setUserCount(null);
        }
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
      fetchProducts({ cityId: selectedCityId, availableOnly: true, limit: 100 }),
      fetchLockers(selectedCityId),
    ])
      .then(([productItems, lockerItems]) => {
        if (!active) {
          return;
        }
        setProducts(productItems);
        setLockers(lockerItems);
        setSelectedLockerId((current) =>
          current && lockerItems.some((locker) => locker.id === current)
            ? current
            : lockerItems[0]?.id || "",
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

  const totalLockerCount = allLockers.length || lockers.length;
  const totalProductCount = products.length;
  const heroHighlights = [
    {
      icon: MapPinned,
      label: cities.length
        ? formatCountRu(cities.length, ["город", "города", "городов"])
        : "города загружаются",
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
    {
      label: pluralizeRu(userCount ?? 0, ["пользователь", "пользователя", "пользователей"]),
      value: userCount ?? "—",
    },
    {
      label: pluralizeRu(totalProductCount, ["товар", "товара", "товаров"]),
      value: totalProductCount || "—",
    },
  ];

  const workflowCards = [
    {
      icon: Boxes,
      title: "Выберите вещь",
    },
    {
      icon: MapPinned,
      title: "Выберите постамат",
    },
    {
      icon: ShieldCheck,
      title: "Оплатите аренду",
    },
    {
      icon: PackageSearch,
      title: "Заберите и верните",
    },
  ];

  return (
    <PageChrome compact>
      <section className="hero-service">
        <div className="hero-service-copy">
          <div className="hero-service-lead">
            <div className="hero-service-stack">
              <div className="hero-service-content">
                <p className="eyebrow">аренда через постаматы</p>
                <h1>Аренда нужных вещей рядом с вами</h1>
              </div>
              <div className="hero-service-summary">
                <p className="hero-service-description">
                  Выберите технику в каталоге, найдите ближайший постамат и получите код
                  для аренды за пару минут.
                </p>
                <div
                  className="hero-service-highlights"
                  aria-label="Ключевые преимущества сервиса"
                >
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
              <div className="hero-service-actions">
                <Link
                  className="button button-primary hero-cta-button hero-cta-start"
                  href="/catalog"
                >
                  Начать аренду
                </Link>
                <Link className="button button-secondary hero-cta-button" href="/lockers">
                  <MapPinned size={18} />
                  Карта постаматов
                </Link>
              </div>
            </div>
            <div className="hero-service-media">
              <div className="hero-service-media-frame">
                <Image
                  src="/hero-rental-promo.png"
                  alt="Витрина Naprokatberu с арендной техникой"
                  width={1054}
                  height={1492}
                  className="hero-service-media-image"
                  priority
                  sizes="(max-width: 720px) 34vw, (max-width: 1100px) 38vw, 420px"
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="section-band workflow-band">
        <div className="section-kicker workflow-kicker">
          <h2 className="section-heading">Как это работает</h2>
        </div>
        <div className="workflow-grid">
          {workflowCards.map((item, index) => {
            const Icon = item.icon;
            return (
              <article className="workflow-card" key={item.title}>
                <span className="workflow-index">{index + 1}</span>
                <span className="workflow-icon">
                  <Icon size={24} />
                </span>
                <strong>{item.title}</strong>
              </article>
            );
          })}
        </div>
      </section>

      <section className="section-band" id="catalog-preview">
        <div className="catalog-preview-heading">
          <div>
            <p className="eyebrow">Каталог</p>
            <h2 className="section-heading">Выберите технику и вещи для аренды</h2>
          </div>
        </div>

        <div className="catalog-filter-panel catalog-filter-panel-home">
          <div className="catalog-filter-city">
            <MapPinned size={16} />
            <CitySelector
              cities={cities}
              value={selectedCityId}
              onChange={setSelectedCityId}
              compact
            />
          </div>
          <CategoryTabs
            categories={previewCategories}
            activeId={previewCategoryId}
            onChange={setPreviewCategoryId}
          />
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
            title={
              previewCategoryId
                ? "В этой категории пока нет товаров"
                : "Каталог пока пуст"
            }
            text={
              previewCategoryId
                ? "Сбросьте категорию или откройте весь каталог, чтобы посмотреть другие позиции."
                : "Когда товары появятся в выбранном городе, они отобразятся здесь."
            }
            action={
              previewCategoryId ? (
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => setPreviewCategoryId("")}
                >
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
          <h2 className="section-heading">Найдите удобный постамат рядом с вами</h2>
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
                  cityName={cities.find((city) => city.id === locker.cityId)?.name ?? null}
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

      <section className="stats-grid" aria-label="Статистика сервиса">
        {stats.map((item) => (
          <article className="stat-card" key={item.label}>
            <strong>{item.value}</strong>
            <span>{item.label}</span>
          </article>
        ))}
      </section>
    </PageChrome>
  );
}
