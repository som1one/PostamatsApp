import Link from "next/link";
import { Clock3, MapPin, PackageSearch } from "lucide-react";
import type { Locker } from "@/shared/api/types";
import { StatusPill } from "./StatusPill";

function workingHoursLabel(locker: Locker) {
  if (!locker.workingHours) {
    return "График уточняется";
  }
  if (locker.workingHours.mode === "24_7") {
    return "Круглосуточно";
  }
  if (locker.workingHours.from && locker.workingHours.to) {
    return `${locker.workingHours.from} - ${locker.workingHours.to}`;
  }
  return "По графику площадки";
}

export function LockerCard({
  locker,
  selected = false,
  onSelect,
  showAction = false,
}: {
  locker: Locker;
  selected?: boolean;
  onSelect?: (lockerId: string) => void;
  showAction?: boolean;
}) {
  return (
    <article className={`locker-card-pro ${selected ? "is-selected" : ""}`}>
      <button
        className="locker-card-hit"
        type="button"
        onClick={() => onSelect?.(locker.id)}
        aria-label={`Выбрать постамат ${locker.name}`}
      />
      <div className="card-row">
        <strong>{locker.name}</strong>
        <StatusPill status={locker.status} />
      </div>
      <div className="locker-card-line">
        <MapPin size={16} />
        <span>{locker.address}</span>
      </div>
      <div className="locker-card-line">
        <Clock3 size={16} />
        <span>{workingHoursLabel(locker)}</span>
      </div>
      <div className="locker-card-stats">
        <span>
          <PackageSearch size={15} />
          {locker.availableProductCount} SKU
        </span>
        <span>{locker.availableUnitCount ?? 0} ед.</span>
      </div>
      {showAction ? (
        <div className="locker-card-actions">
          <Link
            className="button button-secondary locker-card-action"
            href={`/catalog?lockerId=${locker.id}`}
          >
            Смотреть товары
          </Link>
        </div>
      ) : null}
    </article>
  );
}
