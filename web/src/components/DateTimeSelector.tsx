"use client";

import { useMemo } from "react";

function toInputDate(date: Date) {
  return date.toISOString().slice(0, 10);
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
  const disabledSlots = useMemo(() => {
    if (date !== today) {
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
  }, [date, today]);

  return (
    <div className="date-time-selector">
      <label className="field">
        <span>Дата начала</span>
        <input
          className="input"
          type="date"
          min={today}
          max={maxDate}
          value={date}
          onChange={(event) => {
            onDateChange(event.target.value);
            onTimeChange("");
          }}
        />
      </label>
      <div className="field">
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

