import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CreditCard,
  KeyRound,
  MapPinned,
  PackageSearch,
  ShieldCheck,
} from "lucide-react";
import type { ProductDetail } from "@/shared/api/types";

export function ProductEquipment({ product }: { product: ProductDetail }) {
  const items = (product.kitDescription || "")
    .split(/[;\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);

  return (
    <section className="surface detail-panel">
      <div className="card-row">
        <div>
          <p className="eyebrow">Комплектация</p>
          <h2 className="section-title">Что будет в ячейке</h2>
        </div>
        <span className="icon-badge">
          <Boxes size={20} />
        </span>
      </div>
      {items.length ? (
        <div className="equipment-grid">
          {items.map((item) => (
            <span key={item}>
              <CheckCircle2 size={16} />
              {item}
            </span>
          ))}
        </div>
      ) : (
        <p className="muted">Комплектация появится после заполнения карточки товара.</p>
      )}
    </section>
  );
}

export function ProductInstructions({ product }: { product: ProductDetail }) {
  return (
    <section className="surface detail-panel">
      <div className="card-row">
        <div>
          <p className="eyebrow">Правила</p>
          <h2 className="section-title">Перед получением</h2>
        </div>
        <span className="icon-badge">
          <ShieldCheck size={20} />
        </span>
      </div>
      <div className="alert alert-warn">
        <AlertTriangle size={24} />
        <div>
          <strong>Проверьте комплект сразу</strong>
          <span>
            Убедитесь, что товар включается, внешний вид в порядке, а все кабели,
            насадки и аксессуары на месте.
          </span>
        </div>
      </div>
      {product.rulesText ? <p className="muted">{product.rulesText}</p> : null}
    </section>
  );
}

const USAGE_STEPS: Array<{
  icon: typeof MapPinned;
  title: string;
  text: string;
}> = [
  {
    icon: MapPinned,
    title: "Выберите постамат",
    text: "Откройте карту или список и выберите ближайшую точку, где есть нужный товар.",
  },
  {
    icon: CreditCard,
    title: "Оплатите аренду",
    text: "Выберите тариф и оформите заказ. Деньги списываются после подтверждения брони.",
  },
  {
    icon: KeyRound,
    title: "Заберите товар",
    text: "В личном кабинете нажмите «Открыть ячейку» — постамат сам откроется. На забор есть 3 часа после оплаты.",
  },
  {
    icon: PackageSearch,
    title: "Верните в тот же постамат",
    text: "По окончании срока верните товар в тот же постамат, где забирали. Положите в ячейку и закройте дверцу. Подтверждение придёт автоматически.",
  },
];

export function ProductUsageGuide() {
  return (
    <section className="surface detail-panel">
      <div className="card-row">
        <div>
          <p className="eyebrow">Инструкция</p>
          <h2 className="section-title">Как пользоваться сервисом</h2>
        </div>
        <span className="icon-badge">
          <PackageSearch size={20} />
        </span>
      </div>
      <ol className="usage-guide-steps">
        {USAGE_STEPS.map((step, index) => {
          const Icon = step.icon;
          return (
            <li key={step.title} className="usage-guide-step">
              <span className="usage-guide-step-index" aria-hidden="true">
                {index + 1}
              </span>
              <span className="usage-guide-step-icon" aria-hidden="true">
                <Icon size={18} />
              </span>
              <div className="usage-guide-step-body">
                <strong>{step.title}</strong>
                <span className="muted">{step.text}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
