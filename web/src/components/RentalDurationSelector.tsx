import type { PricePlan } from "@/shared/api/types";
import { formatMoney } from "@/shared/format";

function durationLabel(plan: PricePlan) {
  if (plan.name) {
    return plan.name;
  }
  const unit = plan.durationType === "hour" ? "ч" : plan.durationType === "day" ? "дн." : plan.durationType;
  return `${plan.durationValue} ${unit}`;
}

function pickReferencePlan(plans: PricePlan[]): PricePlan | null {
  // Берём самый короткий «обычный» тариф с такой же единицей и сравниваем
  // среднюю цену за единицу против него. Это даёт честный процент скидки
  // вне зависимости от того, сидит товар в часовых тарифах или в дневных.
  const dayPlans = plans.filter((p) => p.durationType === "day");
  const hourPlans = plans.filter((p) => p.durationType === "hour");
  const pool = dayPlans.length ? dayPlans : hourPlans.length ? hourPlans : plans;
  return [...pool].sort((a, b) => a.durationValue - b.durationValue)[0] ?? null;
}

function discountPercent(plan: PricePlan, reference: PricePlan | null): number | null {
  if (!reference || reference.id === plan.id) {
    return null;
  }
  if (reference.durationType !== plan.durationType) {
    return null;
  }
  const referencePerUnit = reference.baseAmount / Math.max(reference.durationValue, 1);
  const currentPerUnit = plan.baseAmount / Math.max(plan.durationValue, 1);
  if (referencePerUnit <= 0) {
    return null;
  }
  const percent = Math.round((1 - currentPerUnit / referencePerUnit) * 100);
  return percent > 0 ? percent : null;
}

export function RentalDurationSelector({
  plans,
  selectedPlanId,
  onSelect,
}: {
  plans: PricePlan[];
  selectedPlanId: string;
  onSelect: (planId: string) => void;
}) {
  if (!plans.length) {
    return <div className="alert alert-warn">Тарифы для товара пока не настроены.</div>;
  }

  const reference = pickReferencePlan(plans);

  return (
    <div className="tariff-grid">
      {plans.map((plan) => {
        const discount = discountPercent(plan, reference);
        return (
          <button
            className={`tariff-card ${selectedPlanId === plan.id ? "is-selected" : ""}`}
            key={plan.id}
            type="button"
            onClick={() => onSelect(plan.id)}
          >
            {discount !== null ? (
              <span className="tariff-card-discount" aria-label={`Скидка ${discount} процентов`}>
                −{discount}%
              </span>
            ) : null}
            <div className="tariff-card-row">
              <span className="tariff-card-label">{durationLabel(plan)}</span>
              <strong className="tariff-card-price">{formatMoney(plan.baseAmount, plan.currency)}</strong>
            </div>
            <small className="tariff-card-meta">
              {formatMoney(Math.round(plan.baseAmount / Math.max(plan.durationValue, 1)), plan.currency)}
              {plan.durationType === "hour" ? "/ч" : "/день"}
            </small>
          </button>
        );
      })}
    </div>
  );
}
