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

// Имя постамата в БД часто хранится с префиксом города ("СПб Невский",
// "Великий Новгород Центр"). На карточке мы выводим город отдельной
// строкой, поэтому из `locker.name` префикс города надо убрать —
// иначе он дублируется. Сравниваем регистронезависимо, аккуратно
// чистим разделитель и оставшиеся пустоты.
function stripCityPrefix(name: string, cityName?: string | null): string {
  if (!name) {
    return "";
  }
  const candidates: string[] = [];
  if (cityName) {
    candidates.push(cityName);
  }
  // Сокращения, которые в каталоге используются вместо полного названия.
  candidates.push("СПб", "Санкт-Петербург", "Спб", "В.Новгород", "Великий Новгород");
  const trimmed = name.trim();
  for (const prefix of candidates) {
    if (!prefix) continue;
    if (trimmed.toLowerCase().startsWith(prefix.toLowerCase())) {
      return trimmed.slice(prefix.length).replace(/^[\s,;:.\-—]+/, "").trim() || trimmed;
    }
  }
  return trimmed;
}

export function LockerCard({
  locker,
  cityName,
  selected = false,
  onSelect,
  showAction = false,
}: {
  locker: Locker;
  cityName?: string | null;
  selected?: boolean;
  onSelect?: (lockerId: string) => void;
  showAction?: boolean;
}) {
  const shortName = stripCityPrefix(locker.name, cityName);
  return (
    <article className={`locker-card-pro ${selected ? "is-selected" : ""}`}>
      <button
        className="locker-card-hit"
        type="button"
        onClick={() => onSelect?.(locker.id)}
        aria-label={`Выбрать постамат ${locker.name}`}
      />
      <div className="locker-card-heading">
        <div className="locker-card-titles">
          {cityName ? (
            <span className="locker-card-city">{cityName}</span>
          ) : null}
          <strong>{shortName || locker.name}</strong>
        </div>
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
