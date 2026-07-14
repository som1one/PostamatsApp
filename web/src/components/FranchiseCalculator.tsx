"use client";

import { useMemo, useState } from "react";
import { ArrowRight, CalendarClock, TrendingUp, Wallet } from "lucide-react";

/**
 * Ориентировочный калькулятор доходности сети постаматов НаПрокатБеру.
 * Привязан к опубликованным цифрам: старт от 550 000 ₽ за постамат,
 * прибыль от 55 000 ₽/мес с точки, окупаемость 7–12 мес, средний чек 1490 ₽.
 * `base` — прибыль с одной точки в месяц при реалистичном сценарии, по размеру города.
 */
const INVESTMENT_PER_POSTAMAT = 550_000;
// Для оценки годовой выручки из прибыли (модель без затрат на персонал).
const PROFIT_MARGIN = 0.82;

const COUNT_MIN = 2;
const COUNT_MAX = 20;

const CITIES = [
  { id: "s", label: "До 500 тыс.", base: 55_000, hint: "спрос ниже среднего" },
  { id: "m", label: "500 тыс.–1 млн", base: 62_000, hint: "стабильный спрос" },
  { id: "l", label: "Более 1 млн", base: 72_000, hint: "высокий спрос" },
  { id: "x", label: "Москва / СПб", base: 85_000, hint: "максимальный спрос" },
] as const;

const SCENARIOS = [
  { id: "low", label: "Осторожный", mult: 0.85 },
  { id: "real", label: "Базовый", mult: 1 },
  { id: "high", label: "Активный", mult: 1.3 },
] as const;

function roundTo(value: number, step: number) {
  return Math.round(value / step) * step;
}

function formatRub(value: number) {
  return `${Math.round(value)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ")} ₽`;
}

// Крупные суммы коротко («2,75 млн ₽»), чтобы не переносились в узких плитках.
function formatRubCompact(value: number) {
  if (value >= 1_000_000) {
    const mln = Math.round((value / 1_000_000) * 100) / 100;
    return `${mln.toString().replace(".", ",")} млн ₽`;
  }
  return formatRub(value);
}

export function FranchiseCalculator() {
  const [count, setCount] = useState(5);
  const [cityId, setCityId] = useState<(typeof CITIES)[number]["id"]>("m");
  const [scenarioId, setScenarioId] = useState<(typeof SCENARIOS)[number]["id"]>("real");

  const city = CITIES.find((c) => c.id === cityId) ?? CITIES[1];
  const scenario = SCENARIOS.find((s) => s.id === scenarioId) ?? SCENARIOS[1];

  const result = useMemo(() => {
    const profitPerPostamat = city.base * scenario.mult;
    const profitMonth = roundTo(count * profitPerPostamat, 1_000);
    const investment = count * INVESTMENT_PER_POSTAMAT;
    const payback = Math.max(1, Math.round(investment / (count * profitPerPostamat)));
    const revenueYear = roundTo((count * profitPerPostamat * 12) / PROFIT_MARGIN, 100_000);
    return { profitMonth, investment, payback, revenueYear };
  }, [count, city, scenario]);

  return (
    <div className="franchise-calc">
      <div className="franchise-calc-controls">
        <div className="calc-field">
          <div className="calc-field-head">
            <span className="calc-field-label">Количество постаматов</span>
            <span className="calc-field-value">{count} шт.</span>
          </div>
          <input
            className="calc-slider"
            type="range"
            min={COUNT_MIN}
            max={COUNT_MAX}
            step={1}
            value={count}
            onChange={(event) => setCount(Number(event.target.value))}
            style={
              {
                "--calc-fill": `${((count - COUNT_MIN) / (COUNT_MAX - COUNT_MIN)) * 100}%`,
              } as React.CSSProperties
            }
            aria-label="Количество постаматов"
          />
          <div className="calc-slider-scale">
            <span>{COUNT_MIN}</span>
            <span>{COUNT_MAX}</span>
          </div>
        </div>

        <div className="calc-field">
          <div className="calc-field-head">
            <span className="calc-field-label">Население города</span>
          </div>
          <div className="calc-segments calc-segments--4" role="group" aria-label="Население города">
            {CITIES.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`calc-segment ${cityId === c.id ? "is-active" : ""}`}
                aria-pressed={cityId === c.id}
                onClick={() => setCityId(c.id)}
              >
                <strong>{c.label}</strong>
                <small>{c.hint}</small>
              </button>
            ))}
          </div>
        </div>

        <div className="calc-field">
          <div className="calc-field-head">
            <span className="calc-field-label">Сценарий выручки</span>
          </div>
          <div className="calc-switch" role="group" aria-label="Сценарий выручки">
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                type="button"
                className={scenarioId === s.id ? "is-active" : ""}
                aria-pressed={scenarioId === s.id}
                onClick={() => setScenarioId(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <p className="calc-hint">Расчёт основан на данных работающих точек: средний чек ~1490 ₽.</p>
      </div>

      <div className="franchise-calc-result">
        <div className="calc-result-hero">
          <span className="calc-result-kicker">Прибыль в месяц со всей сети</span>
          <strong className="calc-result-value">{formatRub(result.profitMonth)}</strong>
          <span className="calc-result-note">после расходов, без затрат на персонал</span>
        </div>
        <div className="calc-result-tiles">
          <div className="calc-tile">
            <CalendarClock size={18} />
            <span>окупаемость</span>
            <strong>{result.payback} мес</strong>
          </div>
          <div className="calc-tile">
            <Wallet size={18} />
            <span>инвестиции</span>
            <strong>{formatRubCompact(result.investment)}</strong>
          </div>
          <div className="calc-tile">
            <TrendingUp size={18} />
            <span>выручка в год</span>
            <strong>{formatRubCompact(result.revenueYear)}</strong>
          </div>
        </div>
        <a className="button button-primary calc-result-cta" href="#consultation">
          Получить точный расчёт
          <ArrowRight size={18} />
        </a>
        <p className="calc-result-fine">
          Расчёт ориентировочный и зависит от локации и скорости раскрутки точки. Точную
          финансовую модель пришлём после заявки.
        </p>
      </div>
    </div>
  );
}
