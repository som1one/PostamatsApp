"use client";

import { useEffect } from "react";
import type { City } from "@/shared/api/types";

export const SELECTED_CITY_STORAGE_KEY = "postamats:selected-city";

export function readSavedCityId() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(SELECTED_CITY_STORAGE_KEY) || "";
}

export function resolveSelectedCityId(cities: City[], preferredCityId: string) {
  if (preferredCityId && cities.some((city) => city.id === preferredCityId)) {
    return preferredCityId;
  }
  return cities[0]?.id || "";
}

export function saveSelectedCityId(cityId: string) {
  if (typeof window === "undefined") {
    return;
  }
  if (cityId) {
    window.localStorage.setItem(SELECTED_CITY_STORAGE_KEY, cityId);
  } else {
    window.localStorage.removeItem(SELECTED_CITY_STORAGE_KEY);
  }
  window.dispatchEvent(new CustomEvent("postamats:city-change", { detail: cityId }));
}

export function useCitySync(
  cities: City[],
  cityId: string,
  onCityChange: (cityId: string) => void,
) {
  useEffect(() => {
    const saved = readSavedCityId();
    const next = resolveSelectedCityId(cities, saved || cityId);
    if (next !== cityId) {
      onCityChange(next);
    }
  }, [cities, cityId, onCityChange]);

  useEffect(() => {
    function applyCityChange(nextCityId: string | null) {
      const next = resolveSelectedCityId(cities, nextCityId || "");
      if (next !== cityId) {
        onCityChange(next);
      }
    }

    function handleStorage(event: StorageEvent) {
      if (event.key === SELECTED_CITY_STORAGE_KEY) {
        applyCityChange(event.newValue);
      }
    }

    function handleCustom(event: Event) {
      const custom = event as CustomEvent<string>;
      applyCityChange(custom.detail ?? "");
    }

    window.addEventListener("storage", handleStorage);
    window.addEventListener("postamats:city-change", handleCustom);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("postamats:city-change", handleCustom);
    };
  }, [cities, cityId, onCityChange]);
}

export function CitySelector({
  cities,
  value,
  onChange,
  compact = false,
  allLabel,
}: {
  cities: City[];
  value: string;
  onChange: (cityId: string) => void;
  compact?: boolean;
  allLabel?: string;
}) {
  return (
    <label className={compact ? "city-select city-select-compact" : "field"}>
      <span>Город</span>
      <select
        className="select"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          saveSelectedCityId(event.target.value);
        }}
        aria-label="Выбор города"
      >
        {allLabel ? <option value="">{allLabel}</option> : null}
        {!cities.length && !allLabel ? (
          <option value="">{compact ? "Выберите город" : "Города загружаются"}</option>
        ) : null}
        {cities.map((city) => (
          <option key={city.id} value={city.id}>
            {city.name}
          </option>
        ))}
      </select>
    </label>
  );
}
