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

function movePastDateForward(value: string, minDate: string, maxDate: string) {
  if (!value) {
    return minDate;
  }

  const min = parseInputDate(minDate);
  const max = parseInputDate(maxDate);
  const next = parseInputDate(value);

  while (next < min) {
    next.setMonth(next.getMonth() + 1);
  }

  if (next > max) {
    return maxDate;
  }

  return toInputDate(next);
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
  const safeDate = useMemo(() => {
    if (!date) {
      return today;
    }
    if (date < today) {
      return movePastDateForward(date, today, maxDate);
    }
    if (date > maxDate) {
      return maxDate;
    }
    return date;
  }, [date, maxDate, today]);
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
    if (date && date !== safeDate) {
      onDateChange(safeDate);
      onTimeChange("");
    }
  }, [date, onDateChange, onTimeChange, safeDate]);

  return (
    <div className="date-time-selector">
      <label className="field date-field">
        <span>Дата начала</span>
        <input
          className="input"
          type="date"
          min={today}
          max={maxDate}
          value={safeDate}
          onChange={(event) => {
            onDateChange(event.target.value);
            onTimeChange("");
          }}
        />
      </label>
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
