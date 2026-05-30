// Контакты поддержки для плавающего виджета и футера.
// Меняйте значения здесь — они подхватятся во всех местах.

export const SUPPORT_CONTACTS = {
  email: "info@naprokatberu.ru",
  // Укажите реальные хэндлы/номера. Пустые строки скрывают канал в виджете.
  telegram: "https://t.me/naprokatberu",
  whatsapp: "",
  phone: "",
} as const;

export type SupportChannelId = "telegram" | "whatsapp" | "phone" | "email";

export type SupportChannel = {
  id: SupportChannelId;
  label: string;
  hint: string;
  href: string;
};

function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}

function whatsappHref(phone: string): string {
  return `https://wa.me/${phone.replace(/[^\d]/g, "")}`;
}

// Собираем список доступных каналов, пропуская незаполненные.
export function getSupportChannels(): SupportChannel[] {
  const channels: SupportChannel[] = [];

  if (SUPPORT_CONTACTS.telegram) {
    channels.push({
      id: "telegram",
      label: "Telegram",
      hint: "Ответим в чате",
      href: SUPPORT_CONTACTS.telegram,
    });
  }

  if (SUPPORT_CONTACTS.whatsapp) {
    channels.push({
      id: "whatsapp",
      label: "WhatsApp",
      hint: "Напишите нам",
      href: whatsappHref(SUPPORT_CONTACTS.whatsapp),
    });
  }

  if (SUPPORT_CONTACTS.phone) {
    channels.push({
      id: "phone",
      label: "Позвонить",
      hint: SUPPORT_CONTACTS.phone,
      href: telHref(SUPPORT_CONTACTS.phone),
    });
  }

  channels.push({
    id: "email",
    label: "Почта",
    hint: SUPPORT_CONTACTS.email,
    href: `mailto:${SUPPORT_CONTACTS.email}`,
  });

  return channels;
}
