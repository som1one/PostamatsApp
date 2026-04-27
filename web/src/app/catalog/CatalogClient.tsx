"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Boxes, Filter, Search, ShoppingBag } from "lucide-react";
import { CategoryTabs } from "@/components/CategoryTabs";
import { CitySelector, readSavedCityId, saveSelectedCityId } from "@/components/CitySelector";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { ProductCard } from "@/components/ProductCard";
import { fetchCities, fetchProducts } from "@/shared/api/endpoints";
import type { City, ProductListItem } from "@/shared/api/types";

function categoryLabel(categoryId: string, index: number) {
  const compact = categoryId.replace(/[-_]/g, " ");
  if (/^[a-f0-9 ]{16,}$/i.test(compact)) {
    return `Категория ${index + 1}`;
  }
  return compact.charAt(0).toUpperCase() + compact.slice(1);
}

export function CatalogClient() {
  const params = useSearchParams();
  const lockerId = params.get("lockerId") || "";
  const [cities, setCities] = useState<City[]>([]);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [cityId, setCityId] = useState("");
  const [search, setSearch] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [availableOnly, setAvailableOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selectedCity = useMemo(
    () => cities.find((city) => city.id === cityId),
    [cities, cityId],
  );
  const categories = useMemo(
    () =>
      [
        { id: "", label: "Все" },
        ...Array.from(new Set(products.map((product) => product.categoryId)))
          .filter(Boolean)
          .map((id, index) => ({ id, label: categoryLabel(id, index) })),
      ],
    [products],
  );
  const visibleProducts = useMemo(
    () =>
      categoryId
        ? products.filter((product) => product.categoryId === categoryId)
        : products,
    [categoryId, products],
  );

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
      .catch(() => setError("Не удалось загрузить города. Попробуйте обновить страницу."));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    fetchProducts({
      cityId,
      lockerId,
      search,
      availableOnly,
      limit: 100,
    })
      .then((items) => {
        if (!active) {
          return;
        }
        setProducts(items);
        setCategoryId((current) =>
          current && items.some((product) => product.categoryId === current) ? current : "",
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
  }, [availableOnly, cityId, lockerId, search]);

  return (
    <PageChrome>
      <section className="catalog-topline">
        <div>
          <p className="eyebrow">Каталог</p>
          <h1 className="page-title">Выберите вещь для аренды</h1>
          <p className="page-subtitle">
            Фильтруйте товары по городу, категории и наличию. Карточки показывают
            минимальную цену, число постаматов и остатки.
          </p>
        </div>
        <div className="catalog-topline-card">
          <Filter size={20} />
          <strong>{selectedCity?.name || "Все города"}</strong>
          <span>{lockerId ? "товары выбранного постамата" : "наличие по точкам выдачи"}</span>
        </div>
      </section>

      <section className="surface catalog-controls">
        <CitySelector cities={cities} value={cityId} onChange={setCityId} allLabel="Все города" />
        <label className="field">
          <span>Поиск</span>
          <span className="search-field">
            <Search size={18} />
            <input
              className="input"
              value={search}
              placeholder="Название, бренд или сценарий"
              onChange={(event) => setSearch(event.target.value)}
            />
          </span>
        </label>
        <label className="toggle-field">
          <input
            type="checkbox"
            checked={availableOnly}
            onChange={(event) => setAvailableOnly(event.target.checked)}
          />
          <span>Только доступные</span>
        </label>
      </section>

      <CategoryTabs categories={categories} activeId={categoryId} onChange={setCategoryId} />

      <div className="toolbar">
        <div>
          <h2 className="section-heading">Товары</h2>
          <p className="muted">
            Найдено {visibleProducts.length}
            {selectedCity ? ` · ${selectedCity.name}` : ""}
          </p>
        </div>
      </div>

      {error ? <div className="alert alert-danger">{error}</div> : null}

      {loading ? (
        <div className="skeleton-grid">
          {Array.from({ length: 9 }, (_, index) => (
            <div className="skeleton-card" key={index} />
          ))}
        </div>
      ) : visibleProducts.length ? (
        <div className="product-grid">
          {visibleProducts.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={categoryId ? <Boxes size={34} /> : <ShoppingBag size={34} />}
          title="Товаров не найдено"
          text="Попробуйте другой город, категорию или очистите строку поиска."
        />
      )}
    </PageChrome>
  );
}
