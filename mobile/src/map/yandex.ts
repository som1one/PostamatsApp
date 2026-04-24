import type { Locker, LockerAvailabilityItem } from "../types";
import type { GeoPoint } from "./mapHelpers";

export const YANDEX_MAPS_API_KEY = process.env.EXPO_PUBLIC_YANDEX_MAPS_API_KEY?.trim() ?? "";

export type YandexMapInstance = {
  destroy: () => void;
  setBounds: (
    bounds: [[number, number], [number, number]],
    options?: Record<string, unknown>,
  ) => void;
  setCenter: (center: [number, number], zoom?: number, options?: Record<string, unknown>) => void;
  geoObjects: {
    add: (geoObject: unknown) => void;
    remove: (geoObject: unknown) => void;
  };
};

export type YandexPlacemarkInstance = {
  events?: {
    add: (name: string, callback: () => void) => void;
  };
  balloon?: {
    open: () => void;
  };
};

type YandexMapsApi = {
  ready: (callback: () => void) => void;
  Map: new (
    element: unknown,
    state: { center: [number, number]; zoom: number; controls?: string[] },
    options?: Record<string, unknown>,
  ) => YandexMapInstance;
  Placemark: new (
    coordinates: [number, number],
    properties?: Record<string, unknown>,
    options?: Record<string, unknown>,
  ) => YandexPlacemarkInstance;
};

export type MappableLocker = Locker & { point: GeoPoint; distanceKm: number | null };

let yandexScriptPromise: Promise<void> | null = null;

export function getYandexMapsApi() {
  const scope = globalThis as unknown as { ymaps?: YandexMapsApi };
  return scope.ymaps ?? null;
}

export function loadYandexMapsScript(apiKey: string) {
  const scope = globalThis as unknown as {
    ymaps?: YandexMapsApi;
    document?: {
      querySelector: (selector: string) => any;
      createElement: (tagName: string) => any;
      head?: { appendChild: (node: unknown) => void };
    };
  };

  if (scope.ymaps) {
    return Promise.resolve();
  }
  if (!scope.document) {
    return Promise.reject(new Error("Яндекс.Карта доступна только в web-версии."));
  }
  if (yandexScriptPromise) {
    return yandexScriptPromise;
  }

  yandexScriptPromise = new Promise<void>((resolve, reject) => {
    const existingScript = scope.document?.querySelector('script[data-yandex-maps-script="1"]');
    if (existingScript) {
      if (scope.ymaps) {
        resolve();
        return;
      }
      existingScript.addEventListener?.("load", () => resolve(), { once: true });
      existingScript.addEventListener?.(
        "error",
        () => {
          yandexScriptPromise = null;
          reject(new Error("Не удалось загрузить Яндекс.Карты."));
        },
        { once: true },
      );
      return;
    }

    const script = scope.document?.createElement("script");
    if (!script) {
      reject(new Error("Не удалось создать скрипт Яндекс.Карт."));
      return;
    }

    script.type = "text/javascript";
    script.async = true;
    script.src = `https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(apiKey)}&lang=ru_RU`;
    script.dataset.yandexMapsScript = "1";
    script.onload = () => resolve();
    script.onerror = () => {
      yandexScriptPromise = null;
      reject(new Error("Не удалось загрузить Яндекс.Карты."));
    };

    scope.document?.head?.appendChild(script);
  });

  return yandexScriptPromise;
}

function escapeHtmlText(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function buildLockerBalloonHtml(
  locker: MappableLocker,
  availabilityItems: LockerAvailabilityItem[] | undefined,
) {
  const listHtml =
    availabilityItems && availabilityItems.length
      ? `<ul style="margin:6px 0 0 0;padding-left:16px;font-size:12px;line-height:16px;color:#1f2330;">${availabilityItems
          .slice(0, 5)
          .map(
            (item) =>
              `<li>${escapeHtmlText(item.productName)} <span style="color:#6e7482;">(${item.availableUnits} шт.)</span></li>`,
          )
          .join("")}${availabilityItems.length > 5 ? `<li style="color:#6e7482;">+ еще ${availabilityItems.length - 5}</li>` : ""}</ul>`
      : '<div style="margin-top:6px;font-size:12px;line-height:16px;color:#6e7482;">Наличие загружается после выбора постамата.</div>';

  return `
    <div style="min-width:220px;padding:2px 0 4px 0;">
      <div style="font-size:14px;line-height:18px;font-weight:700;color:#1f2330;">${escapeHtmlText(locker.name)}</div>
      <div style="font-size:12px;line-height:16px;color:#6e7482;margin-top:2px;">${escapeHtmlText(locker.address)}</div>
      <div style="font-size:12px;line-height:16px;font-weight:700;color:#1f2330;margin-top:8px;">Наличие инструментов</div>
      ${listHtml}
    </div>
  `;
}
