"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Boxes, Filter, Search, ShoppingBag, X } from "lucide-react";
import { CategoryTabs } from "@/components/CategoryTabs";
import {
  CitySelector,
  readSavedCityId,
  resolveSelectedCityId,
  saveSelectedCityId,
  useCitySync,
} from "@/components/CitySelector";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { ProductCard } from "@/components/ProductCard";
import { fetchCities, fetchProducts } from "@/shared/api/endpoints";
import type { City, ProductListItem } from "@/shared/api/types";

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

export function CatalogClient() {
  const params = useSearchParams();
  const lockerId = params.get("lockerId") || "";
  const [cities, setCities] = useState<City[]>([]);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [cityId, setCityId] = useState("");
  const [search, setSearch] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [availableOnly, setAvailableOnly] = useState(true);
  const [filterSheetOpen, setFilterSheetOpen] = useState(false);
  const [draftSearch, setDraftSearch] = useState("");
  const [draftCategoryId, setDraftCategoryId] = useState("");
  const [draftAvailableOnly, setDraftAvailableOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selectedCity = useMemo(
    () => cities.find((city) => city.id === cityId),
    [cities, cityId],
  );
  const categories = useMemo(
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
  const visibleProducts = useMemo(
    () =>
      categoryId
        ? products.filter((product) => product.categoryId === categoryId)
        : products,
    [categoryId, products],
  );
  const activeCategory = useMemo(
    () => categories.find((category) => category.id === categoryId) ?? null,
    [categories, categoryId],
  );
  const mobileFilterSummary = useMemo(() => {
    const parts: string[] = [];
    if (lockerId) {
      parts.push("выбран постамат");
    }
    if (activeCategory?.id) {
      parts.push(activeCategory.label);
    }
    if (search.trim()) {
      parts.push(`поиск: ${search.trim()}`);
    }
    parts.push(availableOnly ? "только доступные" : "все товары");
    return parts.join(" · ");
  }, [activeCategory, availableOnly, lockerId, search]);
  const hasFilterChanges =
    draftSearch.trim() !== search ||
    draftCategoryId !== categoryId ||
    draftAvailableOnly !== availableOnly;
  const hasActiveFilters = Boolean(search || categoryId || !availableOnly);

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

  useEffect(() => {
    if (!filterSheetOpen) {
      return;
    }
    setDraftSearch(search);
    setDraftCategoryId(categoryId);
    setDraftAvailableOnly(availableOnly);
  }, [availableOnly, categoryId, filterSheetOpen, search]);

  useEffect(() => {
    if (!filterSheetOpen) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setFilterSheetOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [filterSheetOpen]);

  function applyDraftFilters() {
    setSearch(draftSearch.trim());
    setCategoryId(draftCategoryId);
    setAvailableOnly(draftAvailableOnly);
    setFilterSheetOpen(false);
  }

  function resetDraftFilters() {
    setDraftSearch("");
    setDraftCategoryId("");
    setDraftAvailableOnly(true);
  }

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

      <section className="surface catalog-mobile-filter-bar">
        <div className="catalog-mobile-filter-row">
          <div className="catalog-mobile-city">
            <CitySelector
              cities={cities}
              value={cityId}
              onChange={setCityId}
              compact
              allLabel="Все города"
            />
          </div>
          <button
            className="button button-secondary catalog-mobile-filter-button"
            type="button"
            onClick={() => setFilterSheetOpen(true)}
          >
            <Filter size={16} />
            Фильтры
            {hasActiveFilters ? <span className="filter-dot" /> : null}
          </button>
        </div>
        <p className="catalog-mobile-filter-summary">{mobileFilterSummary}</p>
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
              aria-label="Поиск по товарам"
              placeholder="Название, бренд или описание"
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

      <div className="catalog-desktop-categories">
        <CategoryTabs categories={categories} activeId={categoryId} onChange={setCategoryId} />
      </div>

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

      {filterSheetOpen ? (
        <div
          className="catalog-filter-sheet-overlay"
          role="presentation"
          onClick={() => setFilterSheetOpen(false)}
        >
          <div className="container catalog-filter-sheet-shell">
            <section
              className="surface catalog-filter-sheet"
              role="dialog"
              aria-modal="true"
              aria-label="Фильтры каталога"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="catalog-filter-sheet-head">
                <div>
                  <strong>Фильтры</strong>
                  <span>{selectedCity?.name || "Все города"}</span>
                </div>
                <button
                  className="button button-ghost icon-button"
                  type="button"
                  onClick={() => setFilterSheetOpen(false)}
                  aria-label="Закрыть фильтры"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="catalog-filter-sheet-body">
                <label className="field catalog-filter-sheet-field">
                  <span>Поиск</span>
                  <span className="search-field">
                    <Search size={18} />
                    <input
                      className="input"
                      value={draftSearch}
                      aria-label="Поиск по товарам"
                      placeholder="Название, бренд или описание"
                      onChange={(event) => setDraftSearch(event.target.value)}
                    />
                  </span>
                </label>

                <label className="toggle-field catalog-filter-sheet-toggle">
                  <input
                    type="checkbox"
                    checked={draftAvailableOnly}
                    onChange={(event) => setDraftAvailableOnly(event.target.checked)}
                  />
                  <span>Только доступные</span>
                </label>

                <div className="catalog-filter-sheet-section">
                  <span className="field-label">Категория</span>
                  <CategoryTabs
                    categories={categories}
                    activeId={draftCategoryId}
                    onChange={setDraftCategoryId}
                  />
                </div>
              </div>

              <div className="catalog-filter-sheet-actions">
                <button className="button button-ghost" type="button" onClick={resetDraftFilters}>
                  Сбросить
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  onClick={applyDraftFilters}
                  disabled={!hasFilterChanges}
                >
                  Применить
                </button>
              </div>
            </section>
          </div>
        </div>
      ) : null}
    </PageChrome>
  );
}
