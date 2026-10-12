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
