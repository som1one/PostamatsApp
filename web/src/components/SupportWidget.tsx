"use client";

import { useEffect, useRef, useState } from "react";
import { Headphones, Mail, MessageCircle, Phone, X } from "lucide-react";
import { getSupportChannels, type SupportChannelId } from "@/shared/support";

const ICONS: Record<SupportChannelId, typeof MessageCircle> = {
  telegram: MessageCircle,
  whatsapp: MessageCircle,
  phone: Phone,
  email: Mail,
};

export function SupportWidget() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const channels = getSupportChannels();

  // Закрываем по клику вне виджета и по Escape.
  useEffect(() => {
    if (!open) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className="support-widget" ref={rootRef}>
      {open ? (
        <div className="support-widget-panel" role="dialog" aria-label="Чат поддержки">
          <div className="support-widget-head">
            <span className="support-widget-head-icon">
              <Headphones size={18} />
            </span>
            <span>
              <strong>Поддержка naprokatberu</strong>
              <small>Выберите удобный способ связи</small>
            </span>
          </div>
          <div className="support-widget-channels">
            {channels.map((channel) => {
              const Icon = ICONS[channel.id];
              const isExternal = channel.href.startsWith("http");
              return (
                <a
                  key={channel.id}
                  className={`support-widget-channel support-widget-channel-${channel.id}`}
                  href={channel.href}
                  target={isExternal ? "_blank" : undefined}
                  rel={isExternal ? "noreferrer" : undefined}
                >
                  <span className="support-widget-channel-icon">
                    <Icon size={18} />
                  </span>
                  <span className="support-widget-channel-copy">
                    <strong>{channel.label}</strong>
                    <small>{channel.hint}</small>
                  </span>
                </a>
              );
            })}
          </div>
        </div>
      ) : null}

      <button
        type="button"
        className={`support-widget-toggle${open ? " is-open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={open ? "Закрыть чат поддержки" : "Открыть чат поддержки"}
      >
        {open ? <X size={24} /> : <Headphones size={24} />}
      </button>
    </div>
  );
}
