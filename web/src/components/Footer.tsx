import Link from "next/link";
import { Mail, MessageCircle, ShieldCheck } from "lucide-react";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container footer-grid">
        <div>
          <Link className="brand footer-brand" href="/">
            <span className="brand-mark">
              <ShieldCheck size={20} />
            </span>
            <span>Postamats</span>
          </Link>
          <p>
            Сервис аренды техники и вещей через постаматы: выбирайте товар,
            точку получения и срок без лишних покупок.
          </p>
        </div>
        <nav aria-label="Разделы">
          <strong>Сервис</strong>
          <Link href="/catalog">Каталог</Link>
          <Link href="/lockers">Карта постаматов</Link>
          <Link href="/faq">FAQ</Link>
          <Link href="/about">О нас</Link>
        </nav>
        <nav aria-label="Документы">
          <strong>Документы</strong>
          <Link href="/about">Условия аренды</Link>
          <Link href="/about">Политика данных</Link>
          <Link href="/profile">Личный кабинет</Link>
        </nav>
        <div>
          <strong>Связь</strong>
          <a href="mailto:support@example.com">
            <Mail size={16} />
            support@example.com
          </a>
          <a href="https://t.me/" target="_blank" rel="noreferrer">
            <MessageCircle size={16} />
            Telegram
          </a>
        </div>
      </div>
      <div className="container footer-bottom">
        <span>© Postamats, 2026</span>
        <span>Production-ready frontend для подключения к API.</span>
      </div>
    </footer>
  );
}

