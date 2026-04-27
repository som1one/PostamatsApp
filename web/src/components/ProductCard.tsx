import Link from "next/link";
import { ArrowRight, ImageIcon, MapPinned, PackageCheck } from "lucide-react";
import type { ProductListItem } from "@/shared/api/types";
import { formatMoney } from "@/shared/format";

export function ProductCard({ product }: { product: ProductListItem }) {
  const href = `/catalog/${product.slug || product.id}`;

  return (
    <article className="card product-card">
      <Link className="product-cover" href={href} aria-label={`Открыть ${product.name}`}>
        {product.coverUrl ? (
          <img src={product.coverUrl} alt={product.name} />
        ) : (
          <div className="product-placeholder">
            <ImageIcon size={44} />
          </div>
        )}
        <span className={`availability-badge ${product.available ? "is-available" : ""}`}>
          {product.available ? "Доступно" : "Нет в наличии"}
        </span>
      </Link>
      <div className="product-body">
        <div>
          <p className="eyebrow">{product.brand || "Аренда на время"}</p>
          <h3>{product.name}</h3>
          {product.shortDescription ? (
            <p className="product-description">{product.shortDescription}</p>
          ) : null}
        </div>
        <div className="product-facts">
          <span>
            <MapPinned size={15} />
            {product.availableLockerCount} постаматов
          </span>
          <span>
            <PackageCheck size={15} />
            {product.availableUnitCount ?? 0} шт.
          </span>
        </div>
        <div className="product-meta">
          <strong className="product-price">от {formatMoney(product.priceFrom, product.currency)}</strong>
          <Link className="button button-dark product-action" href={href}>
            Выбрать
            <ArrowRight size={16} />
          </Link>
        </div>
      </div>
    </article>
  );
}
