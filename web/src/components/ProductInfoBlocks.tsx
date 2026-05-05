import { AlertTriangle, Boxes, CheckCircle2, ShieldCheck } from "lucide-react";
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
