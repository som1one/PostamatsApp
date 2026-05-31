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
          <Link href="/catalog">Каталог</Link>
          <Link href="/lockers">Карта постаматов</Link>
          <Link href="/ideas">Идея для аренды</Link>
          <Link href="/faq">Вопрос-ответ</Link>
          <Link href="/about">О нас</Link>
          <Link href="/franchise">Франшиза</Link>
        </nav>
        <nav className="footer-section" aria-label="Документы">
          <Link href="/terms-rental">Условия аренды товаров</Link>
          <Link href="/about">Политика данных</Link>
          <Link href="/profile">Личный кабинет</Link>
        </nav>
        <div className="footer-section">
          <a href="https://vk.ru/naprokatberu" target="_blank" rel="noreferrer" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="24" height="24" rx="6" fill="#0077FF"/>
              <path d="M13.25 16.5h-1.45s-.3-.03-.45-.2c-.16-.18-.17-.52-.17-.52s-.02-1.25-.66-1.45c-.63-.2-1.18 1.33-2.02 1.82-.62.36-1.08.28-1.08.28l-2.31-.03s-.76-.05-1.02-.46c-.03-.06-.06-.13-.07-.22-.06-.37.44-1.14 1.81-3.08.97-1.38 1.92-2.76 2.78-4.19.4-.67.73-1.22.95-1.51.35-.47.83-.4.83-.4l2.47.02s.72.01.97.39c.05.07.08.18.09.32.03.57-.59 2.18-.64 2.92-.09 1.26.77 1.76 1.39 1.76 1.54 0 2.75-1.74 2.75-3.92 0-2.04-1.39-3.13-3.24-3.13-2.24 0-3.54 1.65-3.54 3.61 0 .66.23 1.26.5 1.68 0 0 .08.13.06.22-.02.09-.26 1.01-.3 1.15-.05.21-.2.27-.43.17-1.41-.6-2.31-2.3-2.31-3.86 0-2.8 2.12-5.51 6.39-5.51 3.43 0 6.06 2.38 6.06 5.78 0 3.58-2.13 6.38-4.7 6.38-.94 0-1.83-.51-2.14-1.06l-.41 2.05s-.13.96-.13.96z" fill="#fff"/>
            </svg>
            ВКонтакте
          </a>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="24" height="24" rx="6" fill="#111111"/>
              <text x="12" y="16" fill="white" fontSize="10" fontWeight="bold" fontFamily="sans-serif" textAnchor="middle">MAX</text>
            </svg>
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
