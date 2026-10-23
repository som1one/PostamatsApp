// Прогрессирующая скидка от срока аренды.
//
// 1 день — без скидки (это «прайс-лист за сутки», от которого считаются
// остальные тарифы), 2 дня — 5%, 3 дня — 10%, далее +1% за каждый
// дополнительный день. Скидка ограничена сверху 25% за весь срок аренды.
//
// Эта же формула продублирована на бэке в
// ``backend/utils/rental_pricing.py`` (по ней бэк считает срок, под который
// нет готового тарифа); правьте в обоих местах.
export function progressiveDiscountPercent(days: number): number {
  if (!Number.isFinite(days) || days <= 0) {
    return 0;
  }
  const d = Math.floor(days);
  let percent: number;
  if (d === 1) {
    percent = 0;
  } else if (d === 2) {
    percent = 5;
  } else if (d === 3) {
    percent = 10;
  } else {
    percent = 10 + (d - 3);
  }
  return Math.max(0, Math.min(percent, 25));
}

export function progressiveDiscountFraction(days: number): number {
  return progressiveDiscountPercent(days) / 100;
}

// Итоговая стоимость аренды на ``days`` суток в копейках/минорных единицах.
// Принимает базовую цену "1 день без скидки" в минорных единицах (то же,
// что ``PricePlan.baseAmount`` для дневного тарифа на 1 сутки).
//
// Используется в date-range UI, чтобы показать цену для произвольного
// диапазона, пока не пришёл ответ ``/products/{id}/pricing``.
export function calculateRentalTotalMinor(
  baseAmountPerDayMinor: number,
  days: number,
): number {
  if (!Number.isFinite(baseAmountPerDayMinor) || baseAmountPerDayMinor < 0) {
    return 0;
  }
  if (!Number.isFinite(days) || days <= 0) {
    return 0;
  }
  const safeDays = Math.floor(days);
  // Округление до 10 рублей (1000 минорных единиц), как на бэке. Проценты
  // держим целыми: с дробным множителем сумма на границе округления
  // расходится с бэком на те самые 10 рублей.
  const scaled =
    baseAmountPerDayMinor * safeDays * (100 - progressiveDiscountPercent(safeDays));
  const QUANTUM = 1000;
  return Math.round(scaled / (QUANTUM * 100)) * QUANTUM;
}

// Цена по дням недели: у товара с галочкой в админке каждые сутки аренды
// дорожают на наценку своего дня. ``markups`` — проценты с понедельника по
// воскресенье (``ProductDetail.weekdayMarkups``), отрицательные — скидка.
// Сутки считаются от даты выдачи: с пятницы на 2 суток — пятница и суббота.
//
// Сумма за срок умножается на среднюю по суткам наценку, так что скидка за
// срок сохраняется. Та же формула — ``weekday_markup_total_minor`` в
// ``backend/utils/rental_pricing.py``; правьте в обоих местах.
export function weekdayMarkupTotalMinor(
  amountMinor: number,
  startISO: string,
  days: number,
  markups: readonly number[] | null | undefined,
): number {
  const start = parseDateOnly(startISO);
  if (!markups || markups.length !== 7 || !start) {
    return amountMinor;
  }
  if (!Number.isFinite(amountMinor) || amountMinor <= 0 || !Number.isFinite(days) || days <= 0) {
    return amountMinor;
  }
  const safeDays = Math.floor(days);
  const firstWeekday = mondayBasedWeekday(start);
  let markupSum = 0;
  for (let offset = 0; offset < safeDays; offset += 1) {
    markupSum += Number(markups[(firstWeekday + offset) % 7]) || 0;
  }
  if (markupSum === 0) {
    // Как на бэке: цену без наценки не переокругляем.
    return amountMinor;
  }
  const QUANTUM = 1000;
  const scaled = amountMinor * (100 * safeDays + markupSum);
  return Math.round(scaled / (QUANTUM * 100 * safeDays)) * QUANTUM;
}

const WEEKDAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"] as const;

// «пт–вс +20%» или «пн −10%, сб–вс +25%»: подряд идущие дни с одной
// наценкой склеиваются. Пустая строка, если наценок нет.
export function describeWeekdayMarkups(markups: readonly number[] | null | undefined): string {
  if (!markups || markups.length !== 7) {
    return "";
  }
  const parts: string[] = [];
  let day = 0;
  while (day < 7) {
    const percent = Number(markups[day]) || 0;
    let last = day;
    while (last + 1 < 7 && (Number(markups[last + 1]) || 0) === percent) {
      last += 1;
    }
    if (percent !== 0) {
      const days =
        last === day
          ? WEEKDAY_SHORT[day]
          : `${WEEKDAY_SHORT[day]}${last === day + 1 ? ", " : "–"}${WEEKDAY_SHORT[last]}`;
      parts.push(`${days} ${percent > 0 ? "+" : "−"}${Math.abs(percent)}%`);
    }
    day = last + 1;
  }
  return parts.join(", ");
}

function mondayBasedWeekday(date: Date): number {
  return (date.getDay() + 6) % 7;
}

// Количество суток аренды между двумя ISO-датами (YYYY-MM-DD).
//
// Сутки считаются как разница start..end:
//   25 мая → 25 мая = 1 сутки (минимум, забрал и сдал в тот же день);
//   25 мая → 26 мая = 1 сутки (с одной даты на следующую = 24 часа);
//   25 мая → 27 мая = 2 суток;
//   1 мая → 15 мая = 14 суток.
//
// Если start позже end — возвращаем 0 как невалидный диапазон.
export function daysBetweenInclusive(startISO: string, endISO: string): number {
  const start = parseDateOnly(startISO);
  const end = parseDateOnly(endISO);
  if (!start || !end) {
    return 0;
  }
  const diffMs = end.getTime() - start.getTime();
  if (diffMs < 0) {
    return 0;
  }
  // 86_400_000 ms в сутках. Полные сутки между датами + минимум 1
  // (если start == end — арендуем на одни сутки, не на ноль).
  const nights = Math.round(diffMs / 86_400_000);
  return Math.max(1, nights);
}

function parseDateOnly(iso: string): Date | null {
  if (!iso) {
    return null;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) {
    return null;
  }
  const [, year, month, day] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  return Number.isNaN(date.getTime()) ? null : date;
}
