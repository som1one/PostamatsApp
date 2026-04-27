import type { PricePlan } from "@/shared/api/types";
import { formatMoney } from "@/shared/format";

function durationLabel(plan: PricePlan) {
  if (plan.name) {
    return plan.name;
  }
  const unit = plan.durationType === "hour" ? "ч" : plan.durationType === "day" ? "дн." : plan.durationType;
  return `${plan.durationValue} ${unit}`;
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
    return <div className="alert alert-warn">Тарифы для товара еще не настроены.</div>;
  }

  return (
    <div className="tariff-grid">
      {plans.map((plan) => (
        <button
          className={`tariff-card ${selectedPlanId === plan.id ? "is-selected" : ""}`}
          key={plan.id}
          type="button"
          onClick={() => onSelect(plan.id)}
        >
          <span>{durationLabel(plan)}</span>
          <strong>{formatMoney(plan.baseAmount, plan.currency)}</strong>
          <small>
            {formatMoney(Math.round(plan.baseAmount / Math.max(plan.durationValue, 1)), plan.currency)}
            {plan.durationType === "hour" ? "/ч" : "/период"}
          </small>
        </button>
      ))}
    </div>
  );
}

