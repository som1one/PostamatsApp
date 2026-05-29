import Image from "next/image";
import Link from "next/link";
import { Mail, MessageCircle } from "lucide-react";

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
          <a href="mailto:info@naprokatberu.ru">
            <Mail size={16} />
            info@naprokatberu.ru
          </a>
          <a href="https://t.me/" target="_blank" rel="noreferrer">
            <MessageCircle size={16} />
            Telegram
          </a>
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
