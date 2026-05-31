import Image from "next/image";
import Link from "next/link";
import { Mail, MessageCircle, User } from "lucide-react";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container footer-grid">
        <div className="footer-intro">
          <Link className="brand footer-brand" href="/">
            <span className="brand-mark">
              <Image src="/naprokatberu-logo.png" alt="" width={40} height={40} />
            </span>
            <span>naprokatberu</span>
          </Link>
          <p className="footer-copy">Сервис аренды вещей</p>
        </div>
        <nav className="footer-section" aria-label="Разделы">
          <strong>Сервис</strong>
          <Link href="/catalog">Каталог</Link>
          <Link href="/lockers">Карта постаматов</Link>
          <Link href="/ideas">Идея для аренды</Link>
          <Link href="/faq">Вопрос-ответ</Link>
          <Link href="/about">О нас</Link>
          <Link href="/franchise">Франшиза</Link>
        </nav>
        <nav className="footer-section" aria-label="Документы">
          <strong>Документы</strong>
          <Link href="/terms-rental">Условия аренды товаров</Link>
          <Link href="/about">Политика данных</Link>
          <Link href="/profile">Личный кабинет</Link>
        </nav>
        <div className="footer-section">
          <strong>Поддержка</strong>
          <a href="https://vk.ru/naprokatberu" target="_blank" rel="noreferrer">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M22 12c0 5.523-4.477 10-10 10S2 17.523 2 12 6.477 2 12 2s10 4.477 10 10z" />
              <path d="M8 12c0 3 2 4 4 4v-2c0-1.5 2-1.5 2-1.5l1.5 1.5H17s-1.5-2.5-3.5-3.5C15.5 9.5 17 7 17 7h-1.5c-1 2-2 3-2 3V7H11v3c0-2-3-2-3-2" />
            </svg>
            ВКонтакте
          </a>
          <span>
            <User size={16} />
            Макс
          </span>
        </div>
      </div>
      <div className="container footer-bottom">
        <span>© naprokatberu, 2026</span>
        <span className="footer-bottom-note">Аренда техники и вещей по понятному цифровому сценарию.</span>
      </div>
      <div className="container footer-legal" aria-label="Реквизиты">
        <span>ИП Кириллов Виталий Валерьевич</span>
        <span>ИНН 532120829653</span>
        <span>ОГРНИП 318532100005699</span>
      </div>
    </footer>
  );
}
