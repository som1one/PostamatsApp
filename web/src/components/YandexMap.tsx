"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Locker } from "@/shared/api/types";

type YMapBounds = [[number, number], [number, number]];
type YMapCoords = [number, number];

type YPlacemark = {
  balloon: {
    open: () => Promise<unknown> | void;
  };
  events: {
    add: (name: string, handler: () => void) => void;
  };
};

type YMap = {
  balloon: {
    close: () => void;
  };
  container: {
    fitToViewport: () => void;
  };
  destroy: () => void;
  geoObjects: {
    add: (placemark: YPlacemark) => void;
    removeAll: () => void;
  };
  getZoom: () => number;
  setBounds: (bounds: YMapBounds, options?: Record<string, unknown>) => void;
  setCenter: (
    coords: YMapCoords,
    zoom?: number,
    options?: Record<string, unknown>,
  ) => void;
};

type YMapsApi = {
  Map: new (
    element: HTMLElement,
    state: { center: YMapCoords; zoom: number; controls?: string[] },
    options?: Record<string, unknown>,
  ) => YMap;
  Placemark: new (
    coords: YMapCoords,
    properties?: Record<string, unknown>,
    options?: Record<string, unknown>,
  ) => YPlacemark;
  ready: (
    successCallback?: (ymaps?: YMapsApi) => void,
    errorCallback?: (error: unknown) => void,
  ) => Promise<unknown>;
};

declare global {
  interface Window {
    __postamatsYandexMapsOnError?: (error?: unknown) => void;
    __postamatsYandexMapsOnLoad?: (ymaps?: YMapsApi) => void;
    ymaps?: YMapsApi;
  }
}

const YANDEX_MAPS_SCRIPT_ID = "postamats-yandex-maps-api";
const YANDEX_MAPS_API_KEY = process.env.NEXT_PUBLIC_YANDEX_MAPS_API_KEY;
const YANDEX_MAPS_ONERROR = "__postamatsYandexMapsOnError";
const YANDEX_MAPS_ONLOAD = "__postamatsYandexMapsOnLoad";
const YANDEX_MAPS_READY_EVENT = "postamats:yandex-ready";
const YANDEX_MAPS_ERROR_EVENT = "postamats:yandex-error";

let yandexMapsPromise: Promise<YMapsApi> | null = null;

function whenYandexMapsReady(ymaps: YMapsApi) {
  return new Promise<YMapsApi>((resolve, reject) => {
    ymaps.ready(
      () => resolve(ymaps),
      (error) => reject(error),
    );
  });
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function lockerPopup(locker: Locker) {
  const units = locker.availableUnitCount ?? 0;
  return `
    <div class="locker-popup">
      <strong>${escapeHtml(locker.name)}</strong>
      <span>${escapeHtml(locker.address)}</span>
      <small>${locker.availableProductCount} SKU · ${units} ед.</small>
    </div>
  `;
}

function markerOptions(selected: boolean, offline: boolean) {
  if (selected) {
    return {
      preset: "islands#circleDotIcon",
      iconColor: "#181818",
      hideIconOnBalloonOpen: false,
    };
  }

  if (offline) {
    return {
      preset: "islands#circleDotIcon",
      iconColor: "#a6a19c",
      hideIconOnBalloonOpen: false,
    };
  }

  return {
    preset: "islands#circleDotIcon",
    iconColor: "#c40404",
    hideIconOnBalloonOpen: false,
  };
}

function getBounds(points: Locker[]): YMapBounds | null {
  if (!points.length) {
    return null;
  }

  let minLat = points[0].lat as number;
  let maxLat = points[0].lat as number;
  let minLon = points[0].lon as number;
  let maxLon = points[0].lon as number;

  for (const locker of points) {
    const lat = locker.lat as number;
    const lon = locker.lon as number;
    minLat = Math.min(minLat, lat);
    maxLat = Math.max(maxLat, lat);
    minLon = Math.min(minLon, lon);
    maxLon = Math.max(maxLon, lon);
  }

  return [
    [minLat, minLon],
    [maxLat, maxLon],
  ];
}

function normalizeYandexError(error?: unknown) {
  return error instanceof Error
    ? error
    : new Error("YANDEX_MAPS_INITIALIZATION_FAILED");
}

function loadYandexMaps() {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("WINDOW_UNAVAILABLE"));
  }

  if (!YANDEX_MAPS_API_KEY) {
    return Promise.reject(new Error("YANDEX_MAPS_API_KEY_MISSING"));
  }

  if (window.ymaps) {
    return whenYandexMapsReady(window.ymaps);
  }

  if (yandexMapsPromise) {
    return yandexMapsPromise;
  }

  yandexMapsPromise = new Promise<YMapsApi>((resolve, reject) => {
    let settled = false;

    const cleanupCallbacks = () => {
      delete window.__postamatsYandexMapsOnLoad;
      delete window.__postamatsYandexMapsOnError;
    };

    const finalizeError = (script: HTMLScriptElement, error?: unknown) => {
      if (settled) {
        return;
      }

      settled = true;
      cleanupCallbacks();
      yandexMapsPromise = null;

      const normalized = normalizeYandexError(error);
      script.dataset.ymapsStatus = "error";
      script.dataset.ymapsError = normalized.message;
      script.dispatchEvent(
        new CustomEvent<string>(YANDEX_MAPS_ERROR_EVENT, {
          detail: normalized.message,
        }),
      );
      reject(normalized);
    };

    const finalizeSuccess = (
      script: HTMLScriptElement,
      ymapsFromCallback?: YMapsApi,
    ) => {
      if (settled) {
        return;
      }

      const api = ymapsFromCallback ?? window.ymaps;
      if (!api) {
        finalizeError(script, new Error("YANDEX_MAPS_NOT_AVAILABLE"));
        return;
      }

      void whenYandexMapsReady(api)
        .then((readyApi) => {
          if (settled) {
            return;
          }

          settled = true;
          cleanupCallbacks();
          script.dataset.ymapsStatus = "ready";
          delete script.dataset.ymapsError;
          script.dispatchEvent(new Event(YANDEX_MAPS_READY_EVENT));
          resolve(readyApi);
        })
        .catch((error) => {
          finalizeError(script, error);
        });
    };

    const existingScript = document.getElementById(
      YANDEX_MAPS_SCRIPT_ID,
    ) as HTMLScriptElement | null;

    const script = existingScript ?? document.createElement("script");

    window.__postamatsYandexMapsOnLoad = (ymaps) => {
      finalizeSuccess(script, ymaps);
    };
    window.__postamatsYandexMapsOnError = (error) => {
      finalizeError(script, error);
    };

    if (existingScript) {
      if (existingScript.dataset.ymapsStatus === "ready" && window.ymaps) {
        finalizeSuccess(existingScript, window.ymaps);
        return;
      }

      if (existingScript.dataset.ymapsStatus === "error") {
        finalizeError(
          existingScript,
          new Error(
            existingScript.dataset.ymapsError ??
              "YANDEX_MAPS_INITIALIZATION_FAILED",
          ),
        );
        return;
      }

      existingScript.addEventListener(
        YANDEX_MAPS_READY_EVENT,
        () => finalizeSuccess(existingScript, window.ymaps),
        { once: true },
      );
      existingScript.addEventListener(
        YANDEX_MAPS_ERROR_EVENT,
        (event) => {
          const detail =
            event instanceof CustomEvent ? event.detail : undefined;
          finalizeError(existingScript, detail ? new Error(detail) : undefined);
        },
        { once: true },
      );
      existingScript.addEventListener(
        "error",
        () => finalizeError(existingScript, new Error("YANDEX_MAPS_SCRIPT_FAILED")),
        { once: true },
      );
      return;
    }

    script.id = YANDEX_MAPS_SCRIPT_ID;
    script.dataset.ymapsStatus = "loading";
    script.src =
      `https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(YANDEX_MAPS_API_KEY)}` +
      `&lang=ru_RU&onload=${YANDEX_MAPS_ONLOAD}&onerror=${YANDEX_MAPS_ONERROR}`;
    script.async = true;
    script.onload = () => {
      finalizeSuccess(script, window.ymaps);
    };
    script.onerror = () => {
      finalizeError(script, new Error("YANDEX_MAPS_SCRIPT_FAILED"));
    };
    document.head.appendChild(script);
  });

  return yandexMapsPromise;
}

export function YandexMap({
  lockers,
  selectedLockerId,
  onSelectLocker,
}: {
  lockers: Locker[];
  selectedLockerId?: string;
  onSelectLocker?: (lockerId: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<YMap | null>(null);
  const [error, setError] = useState("");

  const points = useMemo(
    () =>
      lockers.filter(
        (locker) =>
          typeof locker.lat === "number" && typeof locker.lon === "number",
      ),
    [lockers],
  );

  useEffect(() => {
    if (!hostRef.current || !points.length) {
      return;
    }

    let cancelled = false;

    async function init() {
      try {
        const ymaps = await loadYandexMaps();
        if (cancelled || !hostRef.current) {
          return;
        }

        setError("");

        if (!mapRef.current) {
          const first = points[0];
          mapRef.current = new ymaps.Map(
            hostRef.current,
            {
              center: [first.lat as number, first.lon as number],
              zoom: points.length === 1 ? 13 : 11,
              controls: ["zoomControl"],
            },
            {
              suppressMapOpenBlock: true,
            },
          );
        }

        const map = mapRef.current;
        if (!map) {
          return;
        }

        map.geoObjects.removeAll();
        map.balloon.close();

        for (const locker of points) {
          const coords: YMapCoords = [locker.lat as number, locker.lon as number];
          const placemark = new ymaps.Placemark(
            coords,
            {
              balloonContent: lockerPopup(locker),
              hintContent: locker.name,
            },
            markerOptions(locker.id === selectedLockerId, locker.status !== "online"),
          );

          placemark.events.add("click", () => {
            onSelectLocker?.(locker.id);
          });

          map.geoObjects.add(placemark);

          if (locker.id === selectedLockerId) {
            map.setCenter(coords, Math.max(map.getZoom(), 14), {
              duration: 280,
            });
            void placemark.balloon.open();
          }
        }

        if (!selectedLockerId) {
          if (points.length === 1) {
            const first = points[0];
            map.setCenter([first.lat as number, first.lon as number], 13);
          } else {
            const bounds = getBounds(points);
            if (bounds) {
              map.setBounds(bounds, {
                checkZoomRange: true,
                zoomMargin: 36,
              });
            }
          }
        }

        requestAnimationFrame(() => {
          map.container.fitToViewport();
        });
      } catch {
        if (!cancelled) {
          setError(
            "Не удалось загрузить Яндекс Карты. Пока показываем список постаматов.",
          );
        }
      }
    }

    void init();

    return () => {
      cancelled = true;
    };
  }, [onSelectLocker, points, selectedLockerId]);

  useEffect(() => {
    return () => {
      mapRef.current?.destroy();
      mapRef.current = null;
    };
  }, []);

  if (error || !points.length) {
    return (
      <div className="surface map-shell map-fallback">
        <strong>
          {error || "Карта появится, как только у постаматов будут координаты"}
        </strong>
        <span className="muted">
          {points.length
            ? "Выберите точку из списка справа."
            : "Список точек уже доступен и готов к выбору."}
        </span>
        <div className="grid">
          {lockers.slice(0, 5).map((locker) => (
            <button
              className={`locker-card choice-card ${locker.id === selectedLockerId ? "is-selected" : ""}`}
              key={locker.id}
              type="button"
              onClick={() => onSelectLocker?.(locker.id)}
            >
              <strong>{locker.name}</strong>
              <span className="muted">{locker.address}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="surface map-shell">
      <div ref={hostRef} className="map-canvas" />
    </div>
  );
}
