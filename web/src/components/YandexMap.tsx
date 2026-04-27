"use client";

import { useEffect, useRef, useState } from "react";
import type { Locker } from "@/shared/api/types";

declare global {
  interface Window {
    ymaps?: {
      ready: (callback: () => void) => void;
      Map: new (
        element: HTMLElement,
        state: Record<string, unknown>,
        options?: Record<string, unknown>,
      ) => {
        geoObjects: {
          add: (value: unknown) => void;
          removeAll: () => void;
        };
        setBounds: (
          bounds: [[number, number], [number, number]],
          options?: Record<string, unknown>,
        ) => void;
        destroy: () => void;
      };
      Placemark: new (
        coordinates: [number, number],
        properties: Record<string, unknown>,
        options?: Record<string, unknown>,
      ) => {
        events?: {
          add: (eventName: string, callback: () => void) => void;
        };
      };
    };
  }
}

let scriptPromise: Promise<void> | null = null;

function loadScript(apiKey: string) {
  if (scriptPromise) {
    return scriptPromise;
  }

  scriptPromise = new Promise<void>((resolve, reject) => {
    if (window.ymaps) {
      resolve();
      return;
    }

    const script = document.createElement("script");
    script.src = `https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(apiKey)}&lang=ru_RU`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Yandex Maps script failed"));
    document.head.appendChild(script);
  });

  return scriptPromise;
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
  const mapRef = useRef<InstanceType<NonNullable<typeof window.ymaps>["Map"]> | null>(
    null,
  );
  const [error, setError] = useState("");
  const apiKey = process.env.NEXT_PUBLIC_YANDEX_MAPS_API_KEY?.trim();
  const points = lockers.filter(
    (locker) => typeof locker.lat === "number" && typeof locker.lon === "number",
  );

  useEffect(() => {
    if (!apiKey || !hostRef.current || !points.length) {
      return;
    }

    let cancelled = false;

    loadScript(apiKey)
      .then(
        () =>
          new Promise<void>((resolve) => {
            window.ymaps?.ready(resolve);
          }),
      )
      .then(() => {
        if (cancelled || !hostRef.current || !window.ymaps) {
          return;
        }

        if (!mapRef.current) {
          const first = points[0];
          mapRef.current = new window.ymaps.Map(
            hostRef.current,
            {
              center: [first.lat as number, first.lon as number],
              zoom: 12,
              controls: ["zoomControl"],
            },
            { suppressMapOpenBlock: true },
          );
        }

        mapRef.current.geoObjects.removeAll();
        points.forEach((locker) => {
          const placemark = new window.ymaps!.Placemark(
            [locker.lat as number, locker.lon as number],
            {
              hintContent: locker.name,
              balloonContent: `<strong>${locker.name}</strong><br/>${locker.address}`,
            },
            {
              preset:
                locker.id === selectedLockerId
                  ? "islands#darkOrangeIcon"
                  : locker.status === "online"
                    ? "islands#redIcon"
                    : "islands#grayIcon",
            },
          );
          placemark.events?.add("click", () => onSelectLocker?.(locker.id));
          mapRef.current?.geoObjects.add(placemark);
        });

        if (points.length > 1) {
          const lats = points.map((item) => item.lat as number);
          const lons = points.map((item) => item.lon as number);
          mapRef.current.setBounds(
            [
              [Math.min(...lats), Math.min(...lons)],
              [Math.max(...lats), Math.max(...lons)],
            ],
            { checkZoomRange: true, zoomMargin: 54 },
          );
        }
      })
      .catch(() => setError("Карта недоступна"));

    return () => {
      cancelled = true;
    };
  }, [apiKey, onSelectLocker, points, selectedLockerId]);

  useEffect(() => {
    return () => {
      mapRef.current?.destroy();
      mapRef.current = null;
    };
  }, []);

  if (!apiKey || error || !points.length) {
    return (
      <div className="surface map-shell map-fallback">
        <strong>{error || "Список постаматов"}</strong>
        <span className="muted">
          {apiKey ? "У выбранных точек нет координат." : "Карта временно недоступна."}
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
