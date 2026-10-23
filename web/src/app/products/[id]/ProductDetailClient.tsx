"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Boxes, MapPinned, PackageCheck } from "lucide-react";
import {
  CitySelector,
  readSavedCityId,
  resolveSelectedCityId,
  saveSelectedCityId,
  useCitySync,
} from "@/components/CitySelector";
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
  fetchProductBusyDates,
  resolveProductBySlugOrId,
} from "@/shared/api/endpoints";
import type { City, Locker, PricePlan, PricingQuote, ProductDetail } from "@/shared/api/types";
import { useAuth } from "@/shared/auth/auth-context";
import { resolvePublicAssetUrl } from "@/shared/media";
import {
  calculateRentalTotalMinor,
  daysBetweenInclusive,
  describeWeekdayMarkups,
  weekdayMarkupTotalMinor,
} from "@/shared/rentalPricing";
import { formatMoney, pluralizeRu } from "@/shared/format";

type LockerOption = {
  lockerId: string;
  name: string;
  address: string;
  status: string;
  availableUnits: number;
  /** Свободных сейчас нет (вещь на руках или под чужой бронью), но её
   * можно забронировать на даты, когда она освободится. */
  isBusyNow: boolean;
  isAvailable: boolean;
};

// Длинные описания на мобильном клампятся в 2 строки (см. globals-19.css).
// Чтобы пользователь мог их прочитать, добавляем кнопку «Показать полностью».
// На десктопе клампа нет, так что кнопка ничего лишнего не показывает —
// просто остаётся скрытой по медиа-запросу.
const PRODUCT_DESCRIPTION_TOGGLE_THRESHOLD = 140;

// Заголовок страницы товара отдельно от названия: само название уходит
// в брони, чеки и уведомления, поэтому в каталоге его не трогаем.
const PRODUCT_PAGE_TITLES: Record<string, string> = {
  "playstation-5": "PlayStation 5 (PS5) — аренда и прокат",
};

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

function tomorrowInputValue() {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const year = tomorrow.getFullYear();
  const month = String(tomorrow.getMonth() + 1).padStart(2, "0");
  const day = String(tomorrow.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function shiftInputDate(iso: string, days: number) {
  const next = new Date(`${iso}T00:00:00`);
  next.setDate(next.getDate() + days);
  const year = next.getFullYear();
  const month = String(next.getMonth() + 1).padStart(2, "0");
  const day = String(next.getDate()).padStart(2, "0");
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
  const [date, setDate] = useState(todayInputValue);
  const [endDate, setEndDate] = useState(tomorrowInputValue);
  const [pricing, setPricing] = useState<PricingQuote | null>(null);
  const [busyDates, setBusyDates] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [pricingLoading, setPricingLoading] = useState(false);
  const [error, setError] = useState("");
  const [pricingError, setPricingError] = useState("");

  const dayPlans = useMemo<PricePlan[]>(() => {
    if (!product) {
      return [];
    }
    return [...product.pricePlans]
      .filter((plan) => plan.durationType === "day")
      .sort((a, b) => a.durationValue - b.durationValue);
  }, [product]);

  // Базовая цена «1 день без скидки» — заголовок «N ₽ в сутки» и точка
  // отсчёта шкалы: срок, под который нет готового тарифа, бэк считает от
  // суточного (backend/utils/rental_pricing.py).
  const baseDayPlan = useMemo<PricePlan | null>(
    () => dayPlans.find((plan) => plan.durationValue === 1) ?? dayPlans[0] ?? null,
    [dayPlans],
  );
  const hasDailyRate = baseDayPlan?.durationValue === 1;

  const rangeDays = useMemo(
    () => daysBetweenInclusive(date, endDate),
    [date, endDate],
  );

  // На сколько суток оформится аренда — ровно выбранный в календаре срок.
  // Раньше сюда подставлялся ближайший тариф снизу, и человек, выбравший
  // 9 суток, видел цену и получал аренду на одни. Ближайший тариф остался
  // только для товара без суточного тарифа: шкалу там считать не от чего,
  // и бэк на срок без тарифа вернёт PRICE_PLAN_NOT_FOUND.
  const rentalDays = useMemo<number>(() => {
    if (rangeDays <= 0) {
      return 0;
    }
    if (hasDailyRate || dayPlans.some((plan) => plan.durationValue === rangeDays)) {
      return rangeDays;
    }
    const fitting = dayPlans.filter((plan) => plan.durationValue <= rangeDays);
    return (fitting[fitting.length - 1] ?? dayPlans[0])?.durationValue ?? 0;
  }, [dayPlans, hasDailyRate, rangeDays]);

  // Готовый тариф ровно на этот срок, если он заведён: его цена главнее шкалы.
  const rentalPlan = useMemo<PricePlan | null>(
    () => dayPlans.find((plan) => plan.durationValue === rentalDays) ?? null,
    [dayPlans, rentalDays],
  );

  const rentalDurationLabel =
    rentalPlan?.name ||
    (rentalDays > 0
      ? `${rentalDays} ${pluralizeRu(rentalDays, ["день", "дня", "дней"])}`
      : "");

  // Наценки по дням недели (пн…вс), если цена товара от них зависит.
  const weekdayMarkups = product?.weekdayMarkups ?? null;
  const weekdayMarkupsLabel = useMemo(
    () => describeWeekdayMarkups(weekdayMarkups),
    [weekdayMarkups],
  );

  // Оценка суммы, пока не пришёл ответ `/products/{id}/pricing`: тем же
  // правилом, каким считает бэк, чтобы цифра не прыгала после загрузки.
  const estimatedTotalMinor = useMemo<number | null>(() => {
    if (rentalDays <= 0) {
      return null;
    }
    let termTotal: number | null = null;
    if (rentalPlan) {
      termTotal = Math.max(0, Math.floor(rentalPlan.baseAmount));
    } else if (baseDayPlan && hasDailyRate) {
      termTotal = calculateRentalTotalMinor(baseDayPlan.baseAmount, rentalDays);
    }
    if (termTotal == null) {
      return null;
    }
    return weekdayMarkupTotalMinor(termTotal, date, rentalDays, weekdayMarkups);
  }, [baseDayPlan, date, hasDailyRate, rentalDays, rentalPlan, weekdayMarkups]);

  // Пока летит запрос за новый срок или дату, в `pricing` лежит сумма за
  // прошлый выбор — показываем ответ бэка, только если он про текущий.
  const currentPricing =
    pricing &&
    pricing.durationType === "day" &&
    pricing.durationValue === rentalDays &&
    (!pricing.startDate || pricing.startDate === date)
      ? pricing
      : null;
  const rentalTotalMinor = currentPricing?.totalAmount ?? estimatedTotalMinor;

  // Скидка = насколько итог дешевле, чем базовый день × дни (с наценкой
  // дней недели, иначе она «съест» скидку за срок). Считаем по факту, без
  // таблиц процентов.
  const rangeDiscountPercent = useMemo<number>(() => {
    if (!baseDayPlan || !hasDailyRate || rentalDays <= 1 || rentalTotalMinor == null) {
      return 0;
    }
    const reference = weekdayMarkupTotalMinor(
      baseDayPlan.baseAmount * rentalDays,
      date,
      rentalDays,
      weekdayMarkups,
    );
    if (reference <= 0) {
      return 0;
    }
    const ratio = 1 - rentalTotalMinor / reference;
    if (ratio <= 0) {
      return 0;
    }
    return Math.round(ratio * 100);
  }, [baseDayPlan, date, hasDailyRate, rentalDays, rentalTotalMinor, weekdayMarkups]);
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
          bookableUnits: locker.bookableUnits ?? 0,
        },
      ]),
    );

    const all = cityLockers.map((locker) => {
      const available = availableById.get(locker.id);
      const isRescheduleLocker =
        Boolean(rescheduleReservationId) && preselectedLockerId === locker.id;
      const isFreeNow = (available?.availableUnits ?? 0) > 0 || isRescheduleLocker;
      // Вещь занята сейчас, но закреплена за этим постаматом — бронь
      // принимаем на свободные даты из календаря.
      const isBusyNow = !isFreeNow && (available?.bookableUnits ?? 0) > 0;
      return {
        lockerId: locker.id,
        name: available?.name ?? locker.name,
        address: available?.address ?? locker.address,
        status: available?.status ?? locker.status,
        availableUnits: available?.availableUnits ?? (isRescheduleLocker ? 1 : 0),
        isBusyNow,
        isAvailable: isFreeNow || isBusyNow,
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
        isBusyNow: locker.availableUnits <= 0 && (locker.bookableUnits ?? 0) > 0,
        isAvailable: locker.availableUnits > 0 || (locker.bookableUnits ?? 0) > 0,
      }));

    return [...all, ...missingAvailable].sort((a, b) => {
      if (a.isAvailable !== b.isAvailable) {
        return a.isAvailable ? -1 : 1;
      }
      if (a.isBusyNow !== b.isBusyNow) {
        return a.isBusyNow ? 1 : -1;
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
  const canCheckout = Boolean(product && rentalDays > 0 && lockerId && date);
  const checkoutHref =
    product && canCheckout
      ? `/checkout?productId=${product.id}&lockerId=${lockerId}&durationType=day&durationValue=${rentalDays}&startAt=${encodeURIComponent(date)}${rescheduleReservationId ? `&reservationId=${encodeURIComponent(rescheduleReservationId)}` : ""}`
      : "/catalog";

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
        // Если пришли с reschedule с заданным durationValue (в днях) —
        // выставляем endDate так, чтобы диапазон совпадал с прошлым тарифом.
        // daysBetweenInclusive по ночам, поэтому endDate = start + durationValue.
        if (
          preselectedDurationType === "day" &&
          Number.isFinite(preselectedDurationValue) &&
          preselectedDurationValue > 0
        ) {
          const startISO = todayInputValue();
          const start = new Date(`${startISO}T00:00:00`);
          if (!Number.isNaN(start.getTime())) {
            const next = new Date(start);
            next.setDate(next.getDate() + Math.max(preselectedDurationValue, 1));
            const yyyy = next.getFullYear();
            const mm = String(next.getMonth() + 1).padStart(2, "0");
            const dd = String(next.getDate()).padStart(2, "0");
            setEndDate(`${yyyy}-${mm}-${dd}`);
          }
        }
        setLockerId((current) =>
          item.availableLockers.some((locker) => locker.lockerId === current)
            ? current
            : item.availableLockers.find((locker) => locker.lockerId === preselectedLockerId)
                ?.lockerId ||
              // Сначала постамат, где вещь можно забрать уже сегодня.
              item.availableLockers.find((locker) => locker.availableUnits > 0)?.lockerId ||
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
    if (!product || !lockerId || rentalDays <= 0) {
      setPricing(null);
      return;
    }

    let active = true;
    setPricingLoading(true);
    setPricingError("");
    fetchProductPricing(
      product.id,
      lockerId,
      "day",
      rentalDays,
      rescheduleReservationId || undefined,
      date || undefined,
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
  }, [date, lockerId, product, rentalDays, rescheduleReservationId]);

  // Занятые даты для календаря: зависят от товара и выбранного постамата.
  useEffect(() => {
    if (!product) {
      setBusyDates([]);
      return;
    }
    let active = true;
    fetchProductBusyDates(product.id, lockerId || undefined, rescheduleReservationId || undefined)
      .then((dates) => {
        if (active) setBusyDates(dates);
      })
      .catch(() => {
        // Занятость — вспомогательная подсказка. При ошибке просто не
        // блокируем даты, чекаут всё равно проверит доступность.
        if (active) setBusyDates([]);
      });
    return () => {
      active = false;
    };
  }, [product, lockerId, rescheduleReservationId]);

  // Старт по умолчанию — сегодня, а у занятой вещи сегодня как раз занято.
  // Переносим выбор на ближайший свободный день, иначе оформление упрётся
  // в отказ на дате, которую человек даже не выбирал.
  useEffect(() => {
    if (!date || !busyDates.includes(date)) {
      return;
    }
    const busy = new Set(busyDates);
    for (let offset = 1; offset <= 60; offset += 1) {
      const candidate = shiftInputDate(date, offset);
      if (!busy.has(candidate)) {
        const dayAfter = shiftInputDate(candidate, 1);
        setDate(candidate);
        setEndDate(busy.has(dayAfter) ? candidate : dayAfter);
        return;
      }
    }
  }, [busyDates, date]);

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
              <h1 className="page-title">{PRODUCT_PAGE_TITLES[product.slug] ?? product.name}</h1>
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
              <div className="product-hero-summary">
                <OrderSummary
                  product={product}
                  lockerName={selectedLocker?.name}
                  lockerAddress={selectedLocker?.address}
                  lockerStatus={selectedLocker?.status}
                  durationLabel={rentalDurationLabel}
                  pricing={currentPricing}
                  estimatedTotal={estimatedTotalMinor}
                  currency={baseDayPlan?.currency}
                  startDateTime={startDateTime}
                  canCheckout={canCheckout}
                  checkoutHref={checkoutHref}
                  isAuthed={isAuthed}
                  variant="compact"
                  showProduct={false}
                />
              </div>
            </div>
          </section>

          <div className="detail-layout" id="rental-flow">
            <section className="rental-panel-stack">
              <section className="surface detail-panel rental-step-panel rental-step-panel-tariff">
                <div className="card-row">
                  <div>
                    <p className="eyebrow">Срок и стоимость</p>
                    <h2 className="section-title">Календарь аренды</h2>
                    {baseDayPlan ? (
                      <p className="muted small rental-range-rate">
                        {formatMoney(baseDayPlan.baseAmount, baseDayPlan.currency)} в сутки
                      </p>
                    ) : null}
                    {weekdayMarkupsLabel ? (
                      <p className="muted small rental-range-rate">
                        Цена зависит от дня недели: {weekdayMarkupsLabel} к цене суток
                      </p>
                    ) : null}
                  </div>
                </div>
                <RentalDateRangePicker
                  value={{ startDate: date, endDate }}
                  onChange={(next) => {
                    setDate(next.startDate);
                    setEndDate(next.endDate);
                  }}
                  totalMinor={rentalTotalMinor}
                  discountPercent={rangeDiscountPercent}
                  currency={baseDayPlan?.currency || "RUB"}
                  disabledDates={busyDates}
                />
                {dayPlans.length ? (
                  <>
                    <p className="muted small rental-range-hint">
                      Или выберите готовый тариф со скидкой:
                    </p>
                    <RentalDurationSelector
                      plans={dayPlans}
                      displayAmount={(plan) =>
                        weekdayMarkupTotalMinor(
                          plan.baseAmount,
                          date,
                          plan.durationValue,
                          weekdayMarkups,
                        )
                      }
                      selectedPlanId={
                        rentalPlan && rangeDays === rentalPlan.durationValue
                          ? rentalPlan.id
                          : ""
                      }
                      onSelect={(planId) => {
                        const plan = dayPlans.find((item) => item.id === planId);
                        if (!plan) {
                          return;
                        }
                        // daysBetweenInclusive считает по ночам:
                        // (start, start) = 1, (start, start+1) = 1, (start, start+2) = 2.
                        // Чтобы тариф 3 дня дал ровно 3 — endDate = start + durationValue.
                        const startISO = date || todayInputValue();
                        const start = new Date(`${startISO}T00:00:00`);
                        if (Number.isNaN(start.getTime())) {
                          return;
                        }
                        const next = new Date(start);
                        next.setDate(next.getDate() + Math.max(plan.durationValue, 1));
                        const yyyy = next.getFullYear();
                        const mm = String(next.getMonth() + 1).padStart(2, "0");
                        const dd = String(next.getDate()).padStart(2, "0");
                        setEndDate(`${yyyy}-${mm}-${dd}`);
                      }}
                    />
                  </>
                ) : null}
              </section>

              <div className="product-mobile-summary">
                <OrderSummary
                  product={product}
                  lockerName={selectedLocker?.name}
                  lockerAddress={selectedLocker?.address}
                  lockerStatus={selectedLocker?.status}
                  durationLabel={rentalDurationLabel}
                  pricing={currentPricing}
                  estimatedTotal={estimatedTotalMinor}
                  currency={baseDayPlan?.currency}
                  startDateTime={startDateTime}
                  canCheckout={canCheckout}
                  checkoutHref={checkoutHref}
                  isAuthed={isAuthed}
                  variant="compact"
                  showProduct={false}
                />
              </div>

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
                              <small>
                                {locker.isBusyNow
                                  ? "сейчас занят"
                                  : locker.isAvailable
                                    ? `${locker.availableUnits} шт.`
                                    : "временно недоступно"}
                              </small>
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
                {selectedLocker?.isBusyNow ? (
                  <div className="alert">
                    Сейчас эта вещь занята. Выберите свободные даты в календаре — после
                    оплаты бронь будет ждать, а PIN-код появится в заказе, как только вещь
                    вернётся в постамат.
                  </div>
                ) : null}
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
