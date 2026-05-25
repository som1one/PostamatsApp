"use client";

import { useEffect, useMemo, useState } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import {
  calculateRentalTotalMinor,
  daysBetweenInclusive,
  progressiveDiscountPercent,
} from "@/shared/rentalPricing";
import { formatMoney, pluralizeRu } from "@/shared/format";

export type DateRangeValue = {
  startDate: string;
  endDate: string;
};

const WEEKDAYS = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"] as const;
const MONTHS_NOMINATIVE = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
] as const;
const MONTHS_GENITIVE = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
] as const;

function toInputDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseInputDate(value: string): Date | null {
  if (!value) {
    return null;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return null;
  }
  const [, y, m, d] = match;
  return new Date(Number(y), Number(m) - 1, Number(d));
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addMonths(date: Date, count: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + count, 1);
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function formatDayMonth(date: Date): string {
  return `${date.getDate()} ${MONTHS_GENITIVE[date.getMonth()]}`;
}

type CalendarCell = {
  date: Date;
  inMonth: boolean;
  iso: string;
};

function buildMonthGrid(monthStart: Date): CalendarCell[] {
  const cells: CalendarCell[] = [];
  // ISO weekday: пн = 1, вс = 7. JS getDay: вс = 0.
  const jsDow = monthStart.getDay();
  const isoDow = jsDow === 0 ? 7 : jsDow;
  const offset = isoDow - 1;
  const cursor = new Date(
    monthStart.getFullYear(),
    monthStart.getMonth(),
    1 - offset,
  );

  // Всегда 6 строк по 7 ячеек, чтобы высота сетки не «прыгала».
  for (let i = 0; i < 42; i += 1) {
    const cellDate = new Date(cursor);
    cells.push({
      date: cellDate,
      inMonth: cellDate.getMonth() === monthStart.getMonth(),
      iso: toInputDate(cellDate),
    });
    cursor.setDate(cursor.getDate() + 1);
  }
  return cells;
}

export function RentalDateRangePicker({
  value,
  onChange,
  baseAmountPerDayMinor,
  currency,
  maxDays = 30,
  mode = "range",
}: {
  value: DateRangeValue;
  onChange: (next: DateRangeValue) => void;
  baseAmountPerDayMinor: number;
  currency: string;
  maxDays?: number;
  mode?: "range" | "single";
}) {
  const today = useMemo(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  }, []);
  const todayISO = useMemo(() => toInputDate(today), [today]);
  const startDateObj = useMemo(
    () => parseInputDate(value.startDate),
    [value.startDate],
  );
  const endDateObj = useMemo(
    () => parseInputDate(value.endDate),
    [value.endDate],
  );

  const [viewMonth, setViewMonth] = useState<Date>(() =>
    startOfMonth(startDateObj || today),
  );
  // Какой край редактируем: при первом клике двигаем `start`, при втором —
  // `end`. После выбора end следующий клик начинает новый диапазон.
  const [pendingEdge, setPendingEdge] = useState<"start" | "end">("end");

  useEffect(() => {
    // Если внешне сменили старт (например, пришли с reschedule), показываем
    // его месяц.
    if (startDateObj) {
      setViewMonth((prev) =>
        prev.getMonth() === startDateObj.getMonth() &&
        prev.getFullYear() === startDateObj.getFullYear()
          ? prev
          : startOfMonth(startDateObj),
      );
    }
  }, [startDateObj]);

  const days = useMemo(
    () => daysBetweenInclusive(value.startDate, value.endDate),
    [value.endDate, value.startDate],
  );
  const safeBase = Math.max(0, Math.floor(baseAmountPerDayMinor));
  const totalMinor = useMemo(
    () => calculateRentalTotalMinor(safeBase, days),
    [days, safeBase],
  );
  const discountPercent = progressiveDiscountPercent(days);

  const monthGrid = useMemo(() => buildMonthGrid(viewMonth), [viewMonth]);

  const minSelectableISO = todayISO;
  const maxSelectableDate = useMemo(() => {
    const limit = new Date(today);
    limit.setDate(limit.getDate() + Math.max(maxDays - 1, 0));
    return limit;
  }, [maxDays, today]);
  const maxSelectableISO = toInputDate(maxSelectableDate);

  function handleCellClick(cell: CalendarCell) {
    if (cell.iso < minSelectableISO || cell.iso > maxSelectableISO) {
      return;
    }
    if (mode === "single") {
      // Один клик — выбираем только дату начала. Конечную дату определяет
      // выбранный тариф снаружи; пока тариф не выбран — пусть end будет
      // равен start, чтобы пикер не показывал «диапазон».
      onChange({
        startDate: cell.iso,
        endDate: value.endDate && value.endDate >= cell.iso ? value.endDate : cell.iso,
      });
      return;
    }
    if (pendingEdge === "end" && startDateObj) {
      if (cell.iso < value.startDate) {
        // Кликнули раньше старта — начинаем заново с этой даты.
        onChange({ startDate: cell.iso, endDate: cell.iso });
        setPendingEdge("end");
        return;
      }
      onChange({ startDate: value.startDate, endDate: cell.iso });
      setPendingEdge("start");
      return;
    }
    onChange({ startDate: cell.iso, endDate: cell.iso });
    setPendingEdge("end");
  }

  function gotoPrevMonth() {
    setViewMonth((prev) => addMonths(prev, -1));
  }

  function gotoNextMonth() {
    setViewMonth((prev) => addMonths(prev, 1));
  }

  const canGoPrev = useMemo(() => {
    const prev = addMonths(viewMonth, -1);
    const lastDayPrev = new Date(prev.getFullYear(), prev.getMonth() + 1, 0);
    return toInputDate(lastDayPrev) >= minSelectableISO;
  }, [minSelectableISO, viewMonth]);
  const canGoNext = useMemo(() => {
    const next = addMonths(viewMonth, 1);
    return toInputDate(next) <= maxSelectableISO;
  }, [maxSelectableISO, viewMonth]);

  const summaryLabel = (() => {
    if (!startDateObj) {
      return mode === "single" ? "Выберите день начала" : "Выберите даты";
    }
    if (mode === "single") {
      return formatDayMonth(startDateObj);
    }
    if (!endDateObj) {
      return formatDayMonth(startDateObj);
    }
    if (isSameDay(startDateObj, endDateObj)) {
      return formatDayMonth(startDateObj);
    }
    return `${formatDayMonth(startDateObj)} — ${formatDayMonth(endDateObj)}`;
  })();

  return (
    <div className="rental-range-picker">
      <div className="rental-range-summary">
        <div className="rental-range-summary-main">
          <span className="rental-range-summary-icon" aria-hidden="true">
            <Calendar size={18} />
          </span>
          <div>
            <strong>{summaryLabel}</strong>
            {mode === "single" ? (
              <span className="muted">Выберите тариф ниже</span>
            ) : (
              <span className="muted">
                {days > 0
                  ? `${days} ${pluralizeRu(days, ["сутки", "суток", "суток"])}`
                  : "—"}
              </span>
            )}
          </div>
        </div>
        {mode === "single" ? null : (
          <div className="rental-range-summary-price">
            <strong>{formatMoney(totalMinor, currency)}</strong>
            {discountPercent > 0 ? (
              <span
                className="rental-range-summary-discount"
                aria-label={`Скидка ${discountPercent} процентов`}
              >
                −{discountPercent}%
              </span>
            ) : null}
          </div>
        )}
      </div>

      <div className="rental-range-calendar">
        <div className="rental-range-calendar-header">
          <button
            className="rental-range-nav"
            type="button"
            aria-label="Предыдущий месяц"
            onClick={gotoPrevMonth}
            disabled={!canGoPrev}
          >
            <ChevronLeft size={18} />
          </button>
          <span className="rental-range-month">
            {MONTHS_NOMINATIVE[viewMonth.getMonth()]}, {viewMonth.getFullYear()}
          </span>
          <button
            className="rental-range-nav"
            type="button"
            aria-label="Следующий месяц"
            onClick={gotoNextMonth}
            disabled={!canGoNext}
          >
            <ChevronRight size={18} />
          </button>
        </div>

        <div className="rental-range-weekdays" role="row">
          {WEEKDAYS.map((label) => (
            <span key={label} className="rental-range-weekday" role="columnheader">
              {label}
            </span>
          ))}
        </div>

        <div className="rental-range-grid" role="grid">
          {monthGrid.map((cell) => {
            const disabled =
              cell.iso < minSelectableISO || cell.iso > maxSelectableISO;
            const isStart = startDateObj
              ? isSameDay(cell.date, startDateObj)
              : false;
            const isEnd = endDateObj ? isSameDay(cell.date, endDateObj) : false;
            const inRange =
              startDateObj && endDateObj
                ? cell.iso >= value.startDate && cell.iso <= value.endDate
                : false;
            const isToday = isSameDay(cell.date, today);

            const classes = [
              "rental-range-day",
              cell.inMonth ? "" : "is-outside",
              disabled ? "is-disabled" : "",
              isStart ? "is-start" : "",
              isEnd ? "is-end" : "",
              inRange && !isStart && !isEnd ? "is-in-range" : "",
              isToday ? "is-today" : "",
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <button
                key={cell.iso}
                className={classes}
                type="button"
                role="gridcell"
                disabled={disabled}
                aria-current={isStart || isEnd ? "date" : undefined}
                aria-label={`${cell.date.getDate()} ${MONTHS_GENITIVE[cell.date.getMonth()]} ${cell.date.getFullYear()}`}
                onClick={() => handleCellClick(cell)}
              >
                {cell.date.getDate()}
              </button>
            );
          })}
        </div>
      </div>

      {mode === "single" ? null : (
        <p className="muted small rental-range-hint">
          Стоимость считается прогрессивно: 1 сутки — −5%, 2 — −10%, 3 — −15%,
          далее +3% за каждый дополнительный день.
        </p>
      )}
    </div>
  );
}
