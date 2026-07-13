"use client";

import { useMemo, useState } from "react";
import { ArrowRight, CalendarClock, TrendingUp, Wallet } from "lucide-react";

/**
 * Ориентировочный калькулятор доходности сети постаматов.
 * Модель привязана к опубликованным цифрам франшизы НаПрокатБеру:
 * старт от 550 000 ₽ за постамат, прибыль от 55 000 ₽/мес с точки,
 * окупаемость 7–12 мес, средний чек 1490 ₽.
 */
const INVESTMENT_PER_POSTAMAT = 550_000;
// Доля прибыли после логистики и обслуживания (модель без штата).
const PROFIT_MARGIN = 0.82;

const COUNTS = [1, 2, 3, 5, 10];

const TRAFFIC = [
  { id: "calm", label: "Спокойная", orders: 32, hint: "двор, небольшой ЖК" },
  { id: "good", label: "Хорошая", orders: 45, hint: "супермаркет, ТЦ у дома" },
  { id: "high", label: "Высокая", orders: 60, hint: "крупный ТЦ, узел трафика" },
] as const;

const CHECK_MIN = 900;
const CHECK_MAX = 2500;

function formatRub(value: number) {
  return `${Math.round(value)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ")} ₽`;
}

export function FranchiseCalculator() {
  const [count, setCount] = useState(3);
  const [trafficId, setTrafficId] = useState<(typeof TRAFFIC)[number]["id"]>("good");
  const [check, setCheck] = useState(1490);

  const traffic = TRAFFIC.find((t) => t.id === trafficId) ?? TRAFFIC[1];

  const result = useMemo(() => {
    const revenueMonth = count * traffic.orders * check;
    const profitMonth = revenueMonth * PROFIT_MARGIN;
    const investment = count * INVESTMENT_PER_POSTAMAT;
    const payback = Math.max(1, Math.round(profitMonth > 0 ? investment / profitMonth : 0));
    return { profitMonth, revenueYear: revenueMonth * 12, investment, payback };
  }, [count, traffic, check]);

  const checkPercent = ((check - CHECK_MIN) / (CHECK_MAX - CHECK_MIN)) * 100;

  return (
    <div className="franchise-calc">
      <div className="franchise-calc-controls">
        <div className="calc-field">
          <div className="calc-field-head">
            <span className="calc-field-label">Количество постаматов</span>
            <span className="calc-field-value">{count} шт.</span>
          </div>
          <div className="calc-pills" role="group" aria-label="Количество постаматов">
            {COUNTS.map((c) => (
              <button
                key={c}
                type="button"
                className={`calc-pill ${count === c ? "is-active" : ""}`}
                aria-pressed={count === c}
                onClick={() => setCount(c)}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        <div className="calc-field">
          <div className="calc-field-head">
            <span className="calc-field-label">Проходимость места</span>
            <span className="calc-field-value">≈ {traffic.orders} аренд/мес</span>
          </div>
          <div className="calc-segments" role="group" aria-label="Проходимость места">
            {TRAFFIC.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`calc-segment ${trafficId === t.id ? "is-active" : ""}`}
                aria-pressed={trafficId === t.id}
                onClick={() => setTrafficId(t.id)}
              >
                <strong>{t.label}</strong>
                <small>{t.hint}</small>
              </button>
            ))}
          </div>
        </div>

        <div className="calc-field">
          <div className="calc-field-head">
            <span className="calc-field-label">Средний чек аренды</span>
            <span className="calc-field-value">{formatRub(check)}</span>
          </div>
          <input
            className="calc-slider"
            type="range"
            min={CHECK_MIN}
            max={CHECK_MAX}
            step={10}
            value={check}
            onChange={(event) => setCheck(Number(event.target.value))}
            style={{ "--calc-fill": `${checkPercent}%` } as React.CSSProperties}
            aria-label="Средний чек аренды, рублей"
          />
          <div className="calc-slider-scale">
            <span>{formatRub(CHECK_MIN)}</span>
            <span>{formatRub(CHECK_MAX)}</span>
          </div>
        </div>
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
            <strong>{result.payback} мес</strong>
            <span>окупаемость</span>
          </div>
          <div className="calc-tile">
            <Wallet size={18} />
            <strong>{formatRub(result.investment)}</strong>
            <span>стартовые вложения</span>
          </div>
          <div className="calc-tile">
            <TrendingUp size={18} />
            <strong>{formatRub(result.revenueYear)}</strong>
            <span>выручка в год</span>
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
