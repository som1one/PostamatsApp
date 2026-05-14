"use client";

import { useEffect, useMemo } from "react";

function toInputDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseInputDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function clampDate(value: string, minDate: string, maxDate: string) {
  if (!value || value < minDate) {
    return minDate;
  }
  if (value > maxDate) {
    return maxDate;
  }
  return value;
}

function formatDateOption(value: string, index: number) {
  const date = parseInputDate(value);
  const title =
    index === 0
      ? "Сегодня"
      : index === 1
        ? "Завтра"
        : new Intl.DateTimeFormat("ru-RU", { weekday: "short" })
            .format(date)
            .replace(".", "")
            .replace(/^./, (char) => char.toUpperCase());
  const caption = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
  }).format(date);

  return { title, caption };
}

const slots = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00", "20:00"];

export function DateTimeSelector({
  date,
  time,
  onDateChange,
  onTimeChange,
}: {
  date: string;
  time: string;
  onDateChange: (date: string) => void;
  onTimeChange: (time: string) => void;
}) {
  const today = useMemo(() => toInputDate(new Date()), []);
  const maxDate = useMemo(() => {
    const next = new Date();
    next.setDate(next.getDate() + 14);
    return toInputDate(next);
  }, []);
  const safeDate = useMemo(() => clampDate(date, today, maxDate), [date, maxDate, today]);
  const dateOptions = useMemo(() => {
    const items: Array<{ value: string; title: string; caption: string }> = [];
    const cursor = parseInputDate(today);

    while (toInputDate(cursor) <= maxDate) {
      const value = toInputDate(cursor);
      const { title, caption } = formatDateOption(value, items.length);
      items.push({ value, title, caption });
      cursor.setDate(cursor.getDate() + 1);
    }

    return items;
  }, [maxDate, today]);
  const disabledSlots = useMemo(() => {
    if (safeDate !== today) {
      return new Set<string>();
    }
    const now = new Date();
    return new Set(
      slots.filter((slot) => {
        const [hours, minutes] = slot.split(":").map(Number);
        const slotDate = new Date();
        slotDate.setHours(hours, minutes, 0, 0);
        return slotDate.getTime() <= now.getTime() + 60 * 60 * 1000;
      }),
    );
  }, [safeDate, today]);

  useEffect(() => {
    if (date !== safeDate) {
      onDateChange(safeDate);
    }
  }, [date, onDateChange, safeDate]);

  useEffect(() => {
    if (time && disabledSlots.has(time)) {
      onTimeChange("");
    }
  }, [disabledSlots, onTimeChange, time]);

  return (
    <div className="date-time-selector">
      <div className="field date-field">
        <span>Дата начала</span>
        <div className="date-chip-grid">
          {dateOptions.map((option) => (
            <button
              className={`date-chip ${safeDate === option.value ? "is-selected" : ""}`}
              key={option.value}
              type="button"
              onClick={() => {
                onDateChange(option.value);
                onTimeChange("");
              }}
            >
              <strong>{option.title}</strong>
              <span>{option.caption}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="field time-field">
        <span>Время получения</span>
        <div className="time-grid">
          {slots.map((slot) => {
            const disabled = disabledSlots.has(slot);
            return (
              <button
                className={`time-slot ${time === slot ? "is-selected" : ""}`}
                key={slot}
                type="button"
                disabled={disabled}
                onClick={() => onTimeChange(slot)}
              >
                {slot}
              </button>
            );
          })}
        </div>
        {disabledSlots.size === slots.length ? (
          <span className="muted small">На сегодня свободных слотов нет, выберите другую дату.</span>
        ) : null}
      </div>
    </div>
  );
}
