// Прогрессирующая скидка от срока аренды.
//
// 1 день — 5%, 2 дня — 10%, 3 дня — 15%, далее +3% за каждый
// дополнительный день. Скидка ограничена сверху 90%, чтобы цена не стала
// отрицательной для экстремально длинных тарифов.
//
// Эта же формула продублирована на бэке в
// ``backend/scripts/add_extra_price_plans.py``; правьте в обоих местах.
export function progressiveDiscountPercent(days: number): number {
  if (!Number.isFinite(days) || days <= 0) {
    return 0;
  }
  const d = Math.floor(days);
  let percent: number;
  if (d === 1) {
    percent = 5;
  } else if (d === 2) {
    percent = 10;
  } else if (d === 3) {
    percent = 15;
  } else {
    percent = 15 + (d - 3) * 3;
  }
  return Math.max(0, Math.min(percent, 90));
}

export function progressiveDiscountFraction(days: number): number {
  return progressiveDiscountPercent(days) / 100;
}

// Итоговая стоимость аренды на ``days`` суток в копейках/минорных единицах.
// Принимает базовую цену "1 день без скидки" в минорных единицах (то же,
// что ``PricePlan.baseAmount`` для дневного тарифа на 1 сутки).
//
// Используется в date-range UI, чтобы показать цену для произвольного
// диапазона до того, как backend подберёт ближайший существующий тариф.
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
  const fraction = progressiveDiscountFraction(safeDays);
  // Округление до 10 рублей (1000 минорных единиц), как на бэке.
  const raw = baseAmountPerDayMinor * safeDays * (1 - fraction);
  const QUANTUM = 1000;
  return Math.round(raw / QUANTUM) * QUANTUM;
}

// Считает разницу в днях между двумя ISO-датами (YYYY-MM-DD).
// Возвращает количество "ночей" + 1 (включая стартовый день), так что
// одинаковые start/end дают 1 день. Это согласуется с тем, как 1-дневный
// тариф соответствует «забрал и вернул в тот же календарный день».
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
  // 86_400_000 ms в сутках (UTC, без DST-перескоков, потому что мы парсим
  // на полночь локально и складываем сутки целыми днями).
  return Math.round(diffMs / 86_400_000) + 1;
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
