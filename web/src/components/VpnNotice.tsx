"use client";

import { useEffect, useState } from "react";
import { Globe2, X } from "lucide-react";
import { fetchVisitorGeo } from "@/shared/api/endpoints";

/**
 * Плашка для посетителей с иностранным IP: «похоже, включён VPN».
 *
 * Страну определяет бэкенд (`/api/geo/visitor`) — по таймзоне браузера VPN
 * не поймать, у клиента с включённым VPN она остаётся московской.
 *
 * Вердикт и закрытие плашки живут в sessionStorage: за одну сессию мы не
 * дёргаем бэкенд повторно при перезагрузках страницы, но и не запоминаем
 * решение навсегда — VPN выключают и включают, а вместе с ним меняется и
 * ответ. Ошибка запроса не показывает ничего: ложная плашка у клиента без
 * VPN хуже, чем её отсутствие у клиента с VPN.
 *
 * Посмотреть плашку без заграничного IP: `?vpn-notice=preview` в адресе.
 */

const DISMISS_KEY = "geo-vpn-notice-dismissed";
const VERDICT_KEY = "geo-vpn-notice-verdict";
const PREVIEW_PARAM = "vpn-notice";

function readSession(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSession(key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    // Приватный режим/заблокированное хранилище — плашка просто
    // перепроверится на следующей загрузке.
  }
}

export function VpnNotice() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get(PREVIEW_PARAM) === "preview") {
      setVisible(true);
      return;
    }

    if (readSession(DISMISS_KEY) === "1") {
      return;
    }

    const cached = readSession(VERDICT_KEY);
    if (cached) {
      setVisible(cached === "warn");
      return;
    }

    let cancelled = false;
    fetchVisitorGeo()
      .then((geo) => {
        if (cancelled) {
          return;
        }
        writeSession(VERDICT_KEY, geo.shouldSuggestVpnOff ? "warn" : "ok");
        setVisible(geo.shouldSuggestVpnOff);
      })
      .catch(() => {
        // Гео не определилось — молчим.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (!visible) {
    return null;
  }

  return (
    <div className="vpn-notice" role="status">
      <span className="vpn-notice-icon" aria-hidden="true">
        <Globe2 size={18} />
      </span>
      <div className="vpn-notice-copy">
        <strong>Похоже, вы заходите из-за границы</strong>
        <span>
          Если включён VPN — выключите его и обновите страницу. С зарубежным IP
          оплата, карта постаматов и вход по СМС могут не работать.
        </span>
      </div>
      <button
        type="button"
        className="vpn-notice-close"
        aria-label="Скрыть уведомление"
        onClick={() => {
          writeSession(DISMISS_KEY, "1");
          setVisible(false);
        }}
      >
        <X size={16} />
      </button>
    </div>
  );
}
