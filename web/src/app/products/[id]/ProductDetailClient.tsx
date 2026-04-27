"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Boxes, CalendarClock, MapPinned, PackageCheck, ShieldCheck } from "lucide-react";
import { CitySelector, readSavedCityId, saveSelectedCityId } from "@/components/CitySelector";
import { DateTimeSelector } from "@/components/DateTimeSelector";
import { EmptyState } from "@/components/EmptyState";
import { OrderSummary } from "@/components/OrderSummary";
import { PageChrome } from "@/components/PageChrome";
import { ProductEquipment, ProductInstructions } from "@/components/ProductInfoBlocks";
import { ProductGallery } from "@/components/ProductGallery";
import { RentalDurationSelector } from "@/components/RentalDurationSelector";
import {
  fetchCities,
  fetchProductPricing,
  resolveProductBySlugOrId,
} from "@/shared/api/endpoints";
import type { City, PricePlan, PricingQuote, ProductDetail } from "@/shared/api/types";
import { useAuth } from "@/shared/auth/auth-context";
import { formatMoney } from "@/shared/format";

type ProductLocker = ProductDetail["availableLockers"][number];

function todayInputValue() {
  return new Date().toISOString().slice(0, 10);
}

function durationText(plan?: PricePlan | null) {
  if (!plan) {
    return "Выберите тариф";
  }
  if (plan.name) {
    return plan.name;
  }
  return `${plan.durationValue} ${plan.durationType}`;
}

export function ProductDetailClient({ productRef }: { productRef: string }) {
  const { isAuthed } = useAuth();
  const [cities, setCities] = useState<City[]>([]);
  const [cityId, setCityId] = useState("");
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [lockerId, setLockerId] = useState("");
  const [planId, setPlanId] = useState("");
  const [date, setDate] = useState(todayInputValue);
  const [time, setTime] = useState("");
  const [pricing, setPricing] = useState<PricingQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [pricingLoading, setPricingLoading] = useState(false);
  const [error, setError] = useState("");
  const [pricingError, setPricingError] = useState("");

  const selectedPlan = useMemo<PricePlan | null>(
    () =>
      product?.pricePlans.find((plan) => plan.id === planId) ??
      product?.pricePlans[0] ??
      null,
    [planId, product],
  );
  const selectedLocker = useMemo<ProductLocker | undefined>(
    () => product?.availableLockers.find((locker) => locker.lockerId === lockerId),
    [lockerId, product],
  );
  const images = useMemo(() => {
    if (!product) {
      return [];
    }
    return Array.from(
      new Set(
        [product.coverUrl, ...product.images.map((image) => image.url)].filter(Boolean) as string[],
      ),
    );
  }, [product]);
  const startDateTime = date && time ? `${date} ${time}` : "";
  const checkoutHref =
    product && selectedPlan && lockerId && date && time
      ? `/checkout?productId=${product.id}&lockerId=${lockerId}&durationType=${selectedPlan.durationType}&durationValue=${selectedPlan.durationValue}&startAt=${encodeURIComponent(`${date}T${time}:00`)}`
      : "/catalog";
  const canCheckout = Boolean(product && selectedPlan && lockerId && date && time);

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
    let active = true;
    setLoading(true);
    setError("");
    resolveProductBySlugOrId(productRef, cityId || undefined)
      .then((item) => {
        if (!active) {
          return;
        }
        setProduct(item);
        setPlanId((current) =>
          item.pricePlans.some((plan) => plan.id === current) ? current : item.pricePlans[0]?.id || "",
        );
        setLockerId((current) =>
          item.availableLockers.some((locker) => locker.lockerId === current)
            ? current
            : item.availableLockers[0]?.lockerId || "",
        );
      })
      .catch(() => {
        if (active) {
          setError("Не удалось загрузить товар. Попробуйте открыть каталог заново.");
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
  }, [cityId, productRef]);

  useEffect(() => {
    if (!product || !lockerId || !selectedPlan) {
      setPricing(null);
      return;
    }

    let active = true;
    setPricingLoading(true);
    setPricingError("");
    fetchProductPricing(
      product.id,
      lockerId,
      selectedPlan.durationType,
      selectedPlan.durationValue,
    )
      .then((result) => {
        if (active) {
          setPricing(result);
        }
      })
      .catch(() => {
        if (active) {
          setPricing(null);
          setPricingError("Цена уточнится при оформлении. Проверьте доступность постамата.");
        }
      })
      .finally(() => {
        if (active) {
          setPricingLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [lockerId, product, selectedPlan]);

  return (
    <PageChrome>
      <Link className="button button-ghost button-inline" href="/catalog">
        <ArrowLeft size={18} />
        Назад в каталог
      </Link>

      {loading ? <div className="loader">Загружаем карточку товара</div> : null}
      {error ? <div className="alert alert-danger">{error}</div> : null}

      {!loading && !product ? (
        <EmptyState
          icon={<Boxes size={34} />}
          title="Товар не найден"
          text="Вернитесь в каталог и выберите другую позицию."
          action={
            <Link className="button button-primary" href="/catalog">
              Открыть каталог
            </Link>
          }
        />
      ) : null}

      {product ? (
        <div className="product-page">
          <section className="product-hero">
            <ProductGallery images={images} title={product.name} />
            <div className="product-hero-copy">
              <p className="eyebrow">{product.brand || "Товар в аренду"}</p>
              <h1 className="page-title">{product.name}</h1>
              <p className="page-subtitle">
                {product.fullDescription ||
                  product.shortDescription ||
                  "Описание появится после заполнения карточки товара в админке."}
              </p>
              <div className="product-hero-facts">
                <span>
                  <PackageCheck size={18} />
                  от {formatMoney(product.pricePlans[0]?.baseAmount, product.pricePlans[0]?.currency)}
                </span>
                <span>
                  <MapPinned size={18} />
                  {product.availableLockers.length} постаматов
                </span>
                <span>
                  <ShieldCheck size={18} />
                  проверка комплекта
                </span>
              </div>
              <a className="button button-primary" href="#rental-flow">
                Выбрать постамат
              </a>
            </div>
          </section>

          <div className="detail-layout" id="rental-flow">
            <section className="detail-panel">
              <section className="surface detail-panel">
                <div className="card-row">
                  <div>
                    <p className="eyebrow">Тарифы</p>
                    <h2 className="section-title">Выберите длительность</h2>
                  </div>
                  <span className="muted">{durationText(selectedPlan)}</span>
                </div>
                <RentalDurationSelector
                  plans={product.pricePlans}
                  selectedPlanId={selectedPlan?.id || ""}
                  onSelect={setPlanId}
                />
              </section>

              <ProductEquipment product={product} />
              <ProductInstructions product={product} />

              <section className="surface detail-panel">
                <div className="card-row">
                  <div>
                    <p className="eyebrow">Постамат</p>
                    <h2 className="section-title">Где получить товар</h2>
                  </div>
                  <CitySelector cities={cities} value={cityId} onChange={setCityId} />
                </div>
                {product.availableLockers.length ? (
                  <div className="product-locker-grid">
                    {product.availableLockers.map((locker) => (
                      <button
                        className={`product-locker-card ${lockerId === locker.lockerId ? "is-selected" : ""}`}
                        key={locker.lockerId}
                        type="button"
                        onClick={() => setLockerId(locker.lockerId)}
                      >
                        <strong>{locker.name}</strong>
                        <span>{locker.address}</span>
                        <small>{locker.availableUnits} шт. доступно</small>
                      </button>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    icon={<MapPinned size={34} />}
                    title="Нет постаматов с этим товаром"
                    text="Выберите другой город или вернитесь позже."
                  />
                )}
              </section>

              <section className="surface detail-panel">
                <div className="card-row">
                  <div>
                    <p className="eyebrow">Время</p>
                    <h2 className="section-title">Когда хотите забрать</h2>
                  </div>
                  <CalendarClock size={22} />
                </div>
                <DateTimeSelector
                  date={date}
                  time={time}
                  onDateChange={setDate}
                  onTimeChange={setTime}
                />
                <p className="muted small">
                  TODO: backend сейчас создает ближайший резерв; выбранное время передается
                  в checkout и готово для будущего endpoint слотов.
                </p>
              </section>

              {pricingLoading ? <div className="loader loader-small">Пересчитываем стоимость</div> : null}
              {pricingError ? <div className="alert alert-warn">{pricingError}</div> : null}
            </section>

            <OrderSummary
              product={product}
              lockerName={selectedLocker?.name}
              lockerAddress={selectedLocker?.address}
              plan={selectedPlan}
              pricing={pricing}
              startDateTime={startDateTime}
              canCheckout={canCheckout}
              checkoutHref={checkoutHref}
              isAuthed={isAuthed}
            />
          </div>
        </div>
      ) : null}
    </PageChrome>
  );
}
