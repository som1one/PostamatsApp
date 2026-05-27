"use client";

import { useEffect, useMemo, useState } from "react";
import { MapPinned, PackageSearch } from "lucide-react";
import {
  CitySelector,
  readSavedCityId,
  resolveSelectedCityId,
  saveSelectedCityId,
  useCitySync,
} from "@/components/CitySelector";
import { EmptyState } from "@/components/EmptyState";
import { LockerCard } from "@/components/LockerCard";
import { PageChrome } from "@/components/PageChrome";
import { YandexMap } from "@/components/YandexMap";
import { fetchAllLockers, fetchCities, fetchLockers } from "@/shared/api/endpoints";
import { formatCountRu, pluralizeRu } from "@/shared/format";
import type { City, Locker } from "@/shared/api/types";
import { buildYandexMapsUrl } from "@/shared/maps";

export function LockersClient() {
  const [cities, setCities] = useState<City[]>([]);
  const [cityId, setCityId] = useState("");
  const [allLockers, setAllLockers] = useState<Locker[]>([]);
  const [lockers, setLockers] = useState<Locker[]>([]);
  const [selectedLockerId, setSelectedLockerId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selectedCity = useMemo(
    () => cities.find((city) => city.id === cityId),
    [cities, cityId],
  );
  const selectedLocker = useMemo(
    () => lockers.find((locker) => locker.id === selectedLockerId) ?? lockers[0],
    [lockers, selectedLockerId],
  );

  useCitySync(cities, cityId, setCityId);

  useEffect(() => {
    let active = true;
    fetchCities()
      .then((items) => {
        if (!active) {
          return;
        }
        setCities(items);
        const next = resolveSelectedCityId(items, readSavedCityId());
        setCityId(next);
        if (next) {
          saveSelectedCityId(next);
        }
      })
      .catch(() => {
        setError("Не удалось загрузить города. Попробуйте обновить страницу.");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    fetchAllLockers()
      .then((items) => {
        if (!active) {
          return;
        }
        setAllLockers(items);
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setAllLockers([]);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    fetchLockers(cityId || undefined)
      .then((items) => {
        if (!active) {
          return;
        }
        setLockers(items);
        setSelectedLockerId((current) =>
          current && items.some((locker) => locker.id === current) ? current : items[0]?.id || "",
        );
      })
      .catch(() => {
        if (active) {
          setError("Не удалось загрузить постаматы. Попробуйте обновить страницу.");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [cityId]);

  const statsLockers = allLockers.length ? allLockers : lockers;
  const totalLockerCount = statsLockers.length;
  const totalUnitCount = statsLockers.reduce(
    (total, locker) => total + (locker.availableUnitCount ?? 0),
    0,
  );
  const totalOnlineCount = statsLockers.filter(
    (locker) => locker.status === "online",
  ).length;

  return (
    <PageChrome>
      <section className="catalog-topline lockers-hero">
        <div>
          <p className="eyebrow">Карта постаматов</p>
          <h1 className="page-title">Постаматы рядом с вами</h1>
          <p className="page-subtitle">
            Выберите город, посмотрите точки на карте и сразу переходите к товарам или
            маршруту.
          </p>
        </div>
        <CitySelector cities={cities} value={cityId} onChange={setCityId} allLabel="Все города" />
      </section>

      <section className="stats-grid" aria-label="Сводка по постаматам">
        <article className="stat-card">
          <strong>{cities.length || "—"}</strong>
          <span>{pluralizeRu(cities.length, ["город", "города", "городов"])}</span>
        </article>
        <article className="stat-card">
          <strong>{totalLockerCount}</strong>
          <span>{pluralizeRu(totalLockerCount, ["постамат", "постамата", "постаматов"])}</span>
        </article>
        <article className="stat-card">
          <strong>{totalUnitCount}</strong>
          <span>единиц</span>
        </article>
        <article className="stat-card">
          <strong>{totalOnlineCount}</strong>
          <span>онлайн</span>
        </article>
      </section>

      {error ? <div className="alert alert-danger">{error}</div> : null}

      {loading ? (
        <div className="loader">Загружаем точки выдачи</div>
      ) : lockers.length ? (
        <div className="lockers-layout">
          <YandexMap
            lockers={lockers}
            selectedLockerId={selectedLockerId}
            onSelectLocker={setSelectedLockerId}
          />

          <aside className="surface lockers-panel">
            <div className="card-row">
              <div>
                <p className="eyebrow">{selectedCity?.name || "Все города"}</p>
                <h2 className="section-title">
                  {formatCountRu(lockers.length, ["постамат", "постамата", "постаматов"])}
                </h2>
              </div>
              <span className="icon-badge">
                <MapPinned size={20} />
              </span>
            </div>

            {selectedLocker ? (
              <div className="selected-locker-callout">
                <PackageSearch size={20} />
                <div>
                  <strong>{selectedLocker.name}</strong>
                  <span>
                    {selectedLocker.availableProductCount} SKU ·{" "}
                    {selectedLocker.availableUnitCount ?? 0} ед.
                  </span>
                  <a
                    className="button button-ghost button-inline selected-locker-link"
                    href={buildYandexMapsUrl({
                      name: selectedLocker.name,
                      address: selectedLocker.address,
                      lat: selectedLocker.lat,
                      lon: selectedLocker.lon,
                    })}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Открыть в Яндекс Картах
                  </a>
                </div>
              </div>
            ) : null}

            <div className="locker-list">
              {lockers.map((locker) => (
                <LockerCard
                  key={locker.id}
                  locker={locker}
                  cityName={cities.find((city) => city.id === locker.cityId)?.name ?? null}
                  selected={selectedLockerId === locker.id}
                  onSelect={setSelectedLockerId}
                  showAction
                />
              ))}
            </div>
          </aside>
        </div>
      ) : (
        <EmptyState
          icon={<MapPinned size={34} />}
          title="Точек пока нет"
          text="Когда появятся доступные постаматы, карта и список обновятся."
        />
      )}
    </PageChrome>
  );
}
