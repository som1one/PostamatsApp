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

export function saveSelectedCityId(cityId: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SELECTED_CITY_STORAGE_KEY, cityId);
  window.dispatchEvent(new CustomEvent("postamats:city-change", { detail: cityId }));
}

export function useCitySync(cityId: string, onCityChange: (cityId: string) => void) {
  useEffect(() => {
    const saved = readSavedCityId();
    if (saved && !cityId) {
      onCityChange(saved);
    }

    function handleStorage(event: StorageEvent) {
      if (event.key === SELECTED_CITY_STORAGE_KEY && event.newValue) {
        onCityChange(event.newValue);
      }
    }

    function handleCustom(event: Event) {
      const custom = event as CustomEvent<string>;
      if (custom.detail) {
        onCityChange(custom.detail);
      }
    }

    window.addEventListener("storage", handleStorage);
    window.addEventListener("postamats:city-change", handleCustom);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("postamats:city-change", handleCustom);
    };
  }, [cityId, onCityChange]);
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
      <span>{compact ? "Город" : "Город"}</span>
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
        {!cities.length && !allLabel ? <option value="">Города загружаются</option> : null}
        {cities.map((city) => (
          <option key={city.id} value={city.id}>
            {city.name}
          </option>
        ))}
      </select>
    </label>
  );
}

