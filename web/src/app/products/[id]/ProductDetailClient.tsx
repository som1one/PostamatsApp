"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Boxes, CalendarClock, CalendarRange, MapPinned, Tags } from "lucide-react";
import {
  CitySelector,
  readSavedCityId,
  resolveSelectedCityId,
  saveSelectedCityId,
  useCitySync,
} from "@/components/CitySelector";
import { DateTimeSelector } from "@/components/DateTimeSelector";
import { EmptyState } from "@/components/EmptyState";
import { OrderSummary } from "@/components/OrderSummary";
import { PageChrome } from "@/components/PageChrome";
import { ProductEquipment, ProductInstructions, ProductUsageGuide } from "@/components/ProductInfoBlocks";
import { ProductGallery } from "@/components/ProductGallery";
import { RentalDateRangePicker } from "@/components/RentalDateRangePicker";
import { RentalDurationSelector } from "@/components/RentalDurationSelector";
import { YandexMap } from "@/components/YandexMap";
import {
  fetchCities,
  fetchAllLockers,
  fetchProductPricing,
  resolveProductBySlugOrId,
} from "@/shared/api/endpoints";
import type { City, Locker, PricePlan, PricingQuote, ProductDetail } from "@/shared/api/types";
import { useAuth } from "@/shared/auth/auth-context";
import { resolvePublicAssetUrl } from "@/shared/media";
import { daysBetweenInclusive } from "@/shared/rentalPricing";
import { formatMoney } from "@/shared/format";

type LockerOption = {
  lockerId: string;
  name: string;
  address: string;
  status: string;
  availableUnits: number;
  isAvailable: boolean;
};

// Длинные описания на мобильном клампятся в 2 строки (см. globals-19.css).
// Чтобы пользователь мог их прочитать, добавляем кнопку «Показать полностью».
// На десктопе клампа нет, так что кнопка ничего лишнего не показывает —
// просто остаётся скрытой по медиа-запросу.
const PRODUCT_DESCRIPTION_TOGGLE_THRESHOLD = 140;

function ProductDescription({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > PRODUCT_DESCRIPTION_TOGGLE_THRESHOLD;

  return (
    <>
      <p className={`page-subtitle${expanded ? " is-expanded" : ""}`}>{text}</p>
      {isLong ? (
        <button
          type="button"
          className="page-subtitle-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Свернуть" : "Показать полностью"}
        </button>
      ) : null}
    </>
  );
}

function todayInputValue() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatRangeNote(plan: PricePlan): string {
  return `${formatMoney(plan.baseAmount, plan.currency)}`;
}

export function ProductDetailClient({ productRef }: { productRef: string }) {
  const { isAuthed } = useAuth();
  const searchParams = useSearchParams();
  const preselectedLockerId = searchParams.get("lockerId") || "";
  const preselectedDurationType = searchParams.get("durationType") || "";
  const preselectedDurationValue = Number(searchParams.get("durationValue") || 0);
  const rescheduleReservationId = searchParams.get("reservationId") || "";
  const [cities, setCities] = useState<City[]>([]);
  const [cityLockers, setCityLockers] = useState<Locker[]>([]);
  const [cityId, setCityId] = useState("");
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [lockerId, setLockerId] = useState("");
  const [planId, setPlanId] = useState("");
  const [date, setDate] = useState(todayInputValue);
  const [endDate, setEndDate] = useState(todayInputValue);
  const [rentMode, setRentMode] = useState<"tariff" | "range">("tariff");
  const [pricing, setPricing] = useState<PricingQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [pricingLoading, setPricingLoading] = useState(false);
  const [error, setError] = useState("");
  const [pricingError, setPricingError] = useState("");

  const tariffSelectedPlan = useMemo<PricePlan | null>(
    () =>
      product?.pricePlans.find((plan) => plan.id === planId) ??
      product?.pricePlans[0] ??
      null,
    [planId, product],
  );

  const dayPlans = useMemo<PricePlan[]>(() => {
    if (!product) {
      return [];
    }
    return [...product.pricePlans]
      .filter((plan) => plan.durationType === "day")
      .sort((a, b) => a.durationValue - b.durationValue);
  }, [product]);

  // Базовая цена «1 день без скидки» — точка отсчёта для клиентской оценки
  // в режиме «Календарь». На бэке множители уже зашиты в существующие
  // плановые тарифы, но базу мы знаем от 1-дневного.
  const baseDayPlan = useMemo<PricePlan | null>(
    () => dayPlans.find((plan) => plan.durationValue === 1) ?? dayPlans[0] ?? null,
    [dayPlans],
  );

  const rangeDays = useMemo(
    () => daysBetweenInclusive(date, endDate),
    [date, endDate],
  );

  // В режиме «Календарь» подбираем существующий тариф с durationValue,
  // ближайшим снизу к выбранному количеству суток. Это страхует от случая,
  // когда у товара нет точного N-дневного плана: бэк требует точного
  // совпадения durationType+durationValue, иначе вернёт PRICE_PLAN_NOT_FOUND.
  const rangeMatchedPlan = useMemo<PricePlan | null>(() => {
    if (!dayPlans.length || rangeDays <= 0) {
      return null;
    }
    let best: PricePlan | null = null;
    for (const plan of dayPlans) {
      if (plan.durationValue <= rangeDays) {
        if (!best || plan.durationValue > best.durationValue) {
          best = plan;
        }
      }
    }
    // Если все тарифы длиннее выбранного диапазона (например, минимальный
    // тариф 2 дня, а пользователь выбрал 1 день), берём самый короткий.
    return best ?? dayPlans[0] ?? null;
  }, [dayPlans, rangeDays]);

  const selectedPlan = rentMode === "range" ? rangeMatchedPlan : tariffSelectedPlan;
  const lockerOptions = useMemo<LockerOption[]>(() => {
    if (!product) {
      return [];
    }

    const availableById = new Map(
      product.availableLockers.map((locker) => [
        locker.lockerId,
        {
          name: locker.name,
          address: locker.address,
          status: locker.status,
          availableUnits: locker.availableUnits,
        },
      ]),
    );

    const all = cityLockers.map((locker) => {
      const available = availableById.get(locker.id);
      const isRescheduleLocker =
        Boolean(rescheduleReservationId) && preselectedLockerId === locker.id;
      return {
        lockerId: locker.id,
        name: available?.name ?? locker.name,
        address: available?.address ?? locker.address,
        status: available?.status ?? locker.status,
        availableUnits: available?.availableUnits ?? (isRescheduleLocker ? 1 : 0),
        isAvailable: (available?.availableUnits ?? 0) > 0 || isRescheduleLocker,
      };
    });

    const missingAvailable = product.availableLockers
      .filter((locker) => !cityLockers.some((item) => item.id === locker.lockerId))
      .map((locker) => ({
        lockerId: locker.lockerId,
        name: locker.name,
        address: locker.address,
        status: locker.status,
        availableUnits: locker.availableUnits,
        isAvailable: locker.availableUnits > 0,
      }));

    return [...all, ...missingAvailable].sort((a, b) => {
      if (a.isAvailable !== b.isAvailable) {
        return a.isAvailable ? -1 : 1;
      }
      return a.name.localeCompare(b.name, "ru");
    });
  }, [cityLockers, preselectedLockerId, product, rescheduleReservationId]);
  const selectedLocker = useMemo<LockerOption | undefined>(
    () => lockerOptions.find((locker) => locker.lockerId === lockerId),
    [lockerId, lockerOptions],
  );
  const mapLockers = useMemo<Locker[]>(() => {
    const allowed = new Set(
      lockerOptions
        .filter((option) => option.isAvailable)
        .map((option) => option.lockerId),
    );
    return cityLockers.filter(
      (locker) =>
        allowed.has(locker.id) &&
        typeof locker.lat === "number" &&
        typeof locker.lon === "number",
    );
  }, [cityLockers, lockerOptions]);
  const images = useMemo(() => {
    if (!product) {
      return [];
    }
    return Array.from(
      new Set(
        [product.coverUrl, ...product.images.map((image) => image.url)]
          .map((url) => resolvePublicAssetUrl(url) || url)
          .filter(Boolean) as string[],
      ),
    );
  }, [product]);
  const startDateTime = date || "";
  const checkoutHref =
    product && selectedPlan && lockerId && date
      ? `/checkout?productId=${product.id}&lockerId=${lockerId}&durationType=${selectedPlan.durationType}&durationValue=${selectedPlan.durationValue}&startAt=${encodeURIComponent(date)}${rescheduleReservationId ? `&reservationId=${encodeURIComponent(rescheduleReservationId)}` : ""}`
      : "/catalog";
  const canCheckout = Boolean(product && selectedPlan && lockerId && date);

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
    if (!cityId) {
      setCityLockers([]);
      return;
    }

    let active = true;
    fetchAllLockers(cityId)
      .then((items) => {
        if (active) {
          setCityLockers(items);
        }
      })
      .catch(() => {
        if (active) {
          setCityLockers([]);
        }
      });

    return () => {
      active = false;
    };
  }, [cityId]);

  useEffect(() => {
    // Не запрашиваем товар, пока не загружены города и не выбран cityId.
    // Иначе первый запрос идёт без cityId и попадают локеры из других
    // городов; UI потом «прилипает» к чужому локеру как к дефолту.
    if (cities.length === 0 || !cityId) {
      return;
    }

    let active = true;
    setLoading(true);
    setError("");
    resolveProductBySlugOrId(productRef, cityId || undefined, rescheduleReservationId || undefined)
      .then((item) => {
        if (!active) {
          return;
        }
        setProduct(item);
        setPlanId((current) =>
          item.pricePlans.some((plan) => plan.id === current)
            ? current
            : item.pricePlans.find(
                (plan) =>
                  plan.durationType === preselectedDurationType &&
                  plan.durationValue === preselectedDurationValue,
              )?.id ||
              item.pricePlans[0]?.id ||
              "",
        );
        setLockerId((current) =>
          item.availableLockers.some((locker) => locker.lockerId === current)
            ? current
            : item.availableLockers.find((locker) => locker.lockerId === preselectedLockerId)
                ?.lockerId ||
              item.availableLockers[0]?.lockerId ||
              "",
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
  }, [
    cities.length,
    cityId,
    preselectedDurationType,
    preselectedDurationValue,
    preselectedLockerId,
    productRef,
    rescheduleReservationId,
  ]);

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
      rescheduleReservationId || undefined,
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
  }, [lockerId, product, rescheduleReservationId, selectedPlan]);

  return (
    <PageChrome>
      <Link className="button button-ghost button-inline product-back-link" href="/catalog">
        <ArrowLeft size={18} />
        Назад в каталог
      </Link>

      {loading ? <div className="loader">Загружаем товар</div> : null}
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
              <ProductDescription
                text={
                  product.fullDescription ||
                  product.shortDescription ||
                  "Описание появится после заполнения карточки товара в админке."
                }
              />
              <div className="product-mobile-equipment">
                <ProductEquipment product={product} />
              </div>
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
                variant="compact"
                showProduct={false}
              />
            </div>
          </section>

          <div className="detail-layout" id="rental-flow">
            <section className="rental-panel-stack">
              <section className="surface detail-panel rental-step-panel rental-step-panel-tariff">
                <div className="card-row">
                  <div>
                    <p className="eyebrow">Срок и стоимость</p>
                    <h2 className="section-title">
                      {rentMode === "tariff" ? "Выберите дату и срок аренды" : "Выберите даты"}
                    </h2>
                  </div>
                  <div
                    className="rental-mode-switch"
                    role="tablist"
                    aria-label="Режим выбора срока аренды"
                  >
                    <button
                      type="button"
                      role="tab"
                      aria-selected={rentMode === "tariff"}
                      className={`rental-mode-switch-button ${rentMode === "tariff" ? "is-active" : ""}`}
                      onClick={() => setRentMode("tariff")}
                    >
                      <Tags size={14} />
                      Тарифы
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={rentMode === "range"}
                      className={`rental-mode-switch-button ${rentMode === "range" ? "is-active" : ""}`}
                      onClick={() => {
                        setRentMode("range");
                        // При первом переключении приводим конец к старту,
                        // чтобы пользователь сам выбрал диапазон.
                        if (!endDate || endDate < date) {
                          setEndDate(date);
                        }
                      }}
                    >
                      <CalendarRange size={14} />
                      Календарь
                    </button>
                  </div>
                </div>
                {rentMode === "tariff" ? (
                  <RentalDurationSelector
                    plans={product.pricePlans}
                    selectedPlanId={selectedPlan?.id || ""}
                    onSelect={setPlanId}
                  />
                ) : (
                  <RentalDateRangePicker
                    value={{ startDate: date, endDate }}
                    onChange={(next) => {
                      setDate(next.startDate);
                      setEndDate(next.endDate);
                    }}
                    baseAmountPerDayMinor={baseDayPlan?.baseAmount ?? 0}
                    currency={baseDayPlan?.currency || "RUB"}
                  />
                )}
                {rentMode === "range" && rangeMatchedPlan && rangeDays > 0 ? (
                  <p className="muted small rental-range-hint">
                    {rangeMatchedPlan.durationValue === rangeDays
                      ? `Подобран тариф «${rangeMatchedPlan.name}» — ${formatRangeNote(rangeMatchedPlan)}.`
                      : `Ближайший доступный тариф — «${rangeMatchedPlan.name}» (${rangeMatchedPlan.durationValue} дн., ${formatRangeNote(rangeMatchedPlan)}). При оформлении срок аренды будет ${rangeMatchedPlan.durationValue} дн.`}
                  </p>
                ) : null}
              </section>

              {rentMode === "tariff" ? (
                <section className="surface detail-panel rental-step-panel rental-step-panel-time">
                  <div className="card-row">
                    <div>
                      <p className="eyebrow">Дата</p>
                      <h2 className="section-title">Когда хотите забрать</h2>
                    </div>
                    <CalendarClock size={22} />
                  </div>
                  <DateTimeSelector date={date} onDateChange={setDate} />
                  <p className="muted small">
                    После оплаты у вас будет 3 часа, чтобы забрать товар из постамата.
                  </p>
                </section>
              ) : null}

              <section className="surface detail-panel rental-step-panel rental-step-panel-locker">
                <div className="card-row">
                  <div>
                    <p className="eyebrow">Постамат</p>
                    <h2 className="section-title">Где получить товар</h2>
                  </div>
                  <CitySelector cities={cities} value={cityId} onChange={setCityId} />
                </div>
                {mapLockers.length ? (
                  <div className="product-locker-map">
                    <YandexMap
                      lockers={mapLockers}
                      selectedLockerId={lockerId}
                      onSelectLocker={setLockerId}
                    />
                  </div>
                ) : null}
                {lockerOptions.length ? (
                  <div className="product-locker-grid">
                    {lockerOptions.map((locker) => {
                      const isSelected = lockerId === locker.lockerId;
                      return (
                        <button
                          className={`product-locker-card ${isSelected ? "is-selected" : ""}`}
                          key={locker.lockerId}
                          type="button"
                          disabled={!locker.isAvailable}
                          onClick={() => setLockerId(locker.lockerId)}
                        >
                          <div className="product-locker-card-row">
                            <strong>{locker.name}</strong>
                            <div className="product-locker-card-badges">
                              <small>{locker.isAvailable ? `${locker.availableUnits} шт.` : "временно недоступно"}</small>
                              {isSelected ? <em>Выбран</em> : null}
                            </div>
                          </div>
                          <span>{locker.address}</span>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <EmptyState
                    icon={<MapPinned size={34} />}
                    title="Нет постаматов с этим товаром"
                    text="Выберите другой город или вернитесь позже."
                  />
                )}
              </section>

              {pricingLoading ? <div className="loader loader-small">Пересчитываем стоимость</div> : null}
              {pricingError ? <div className="alert alert-warn">{pricingError}</div> : null}
            </section>

            <aside className="detail-side-stack">
              <div className="product-desktop-equipment">
                <ProductEquipment product={product} />
              </div>
              <ProductInstructions product={product} />
              <ProductUsageGuide />
            </aside>
          </div>
        </div>
      ) : null}
    </PageChrome>
  );
}
