"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Boxes,
  Building2,
  CreditCard,
  Factory,
  GraduationCap,
  Hotel,
  MapPinned,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  ShoppingCart,
  Store,
  Timer,
  TrendingUp,
  Truck,
  Users,
  Wallet,
} from "lucide-react";
import { PageChrome } from "@/components/PageChrome";

const CONTACT_EMAIL = "info@naprokatberu.ru";

const metrics = [
  { value: "от 550 000 ₽", label: "стартовые вложения", note: "* возможен лизинг от партнёра" },
  { value: "до 2,7 млн ₽", label: "выручка в год" },
  { value: "0 ₽", label: "затраты на персонал" },
  { value: "от 55 000 ₽", label: "прибыль в месяц с одного постамата" },
  { value: "7–12 месяцев", label: "окупаемость" },
  { value: "1490 ₽", label: "средний чек" },
];

const advantages = [
  {
    icon: PackageCheck,
    title: "Забрал сразу",
    text: "Самые востребованные вещи уже лежат в постамате — клиент берёт их в пару касаний, без ожидания.",
  },
  {
    icon: RefreshCw,
    title: "Вернул туда же",
    text: "Возврат идёт в тот же постамат после аренды — без встреч, курьеров и переписок.",
  },
  {
    icon: Boxes,
    title: "Ассортимент растёт",
    text: "Каталог пополняется регулярно, а под запрос курьер привозит расширенный набор товаров.",
  },
  {
    icon: ShieldCheck,
    title: "Без залога",
    text: "Привязка карты и автоматический скоринг заменяют залог и долгие проверки.",
  },
];

const clientSteps = [
  { icon: CreditCard, title: "Оформляет аренду", text: "Выбирает вещь и срок в приложении или на сайте." },
  { icon: Wallet, title: "Привязывает карту", text: "Оплата и гарантия — без наличного залога." },
  { icon: Timer, title: "Проходит скоринг", text: "Автоматическая проверка занимает около полутора минут." },
  { icon: PackageCheck, title: "Получает товар", text: "Открывает ячейку по коду и забирает вещь." },
  { icon: RefreshCw, title: "Возвращает или продлевает", text: "Возвращает вещь в тот же постамат или продлевает аренду." },
];

const placements = [
  { icon: Building2, title: "Подъезды и холлы ЖК", text: "Большие жилые комплексы с постоянным трафиком жильцов." },
  { icon: Store, title: "Прикассовые и розничные зоны", text: "Магазины у дома, супермаркеты, торговые центры." },
  { icon: GraduationCap, title: "Студенческие общежития", text: "Высокий спрос на технику и вещи на короткий срок." },
  { icon: Hotel, title: "Гостиницы и апарт-отели", text: "Дополнительный сервис для гостей без расходов на штат." },
  { icon: Truck, title: "ПВЗ и коворкинги", text: "Точки выдачи маркетплейсов и рабочие пространства." },
  { icon: ShoppingCart, title: "Торговые центры и гипермаркеты", text: "Высокий пеший трафик и готовая аудитория покупателей рядом с точкой." },
];

export function FranchiseClient() {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const name = String(data.get("name") || "").trim();
    const phone = String(data.get("phone") || "").trim();
    const city = String(data.get("city") || "").trim();
    const subject = encodeURIComponent("Заявка на франшизу naprokatberu");
    const body = encodeURIComponent(
      `Имя: ${name}\nТелефон: ${phone}\nГород: ${city}\n\nХочу обсудить открытие точки аренды через постаматы.`,
    );
    window.location.href = `mailto:${CONTACT_EMAIL}?subject=${subject}&body=${body}`;
    setSubmitted(true);
  }

  return (
    <PageChrome>
      <section className="franchise-hero">
        <div className="franchise-hero-copy">
          <p className="eyebrow">Франшиза</p>
          <h1 className="page-title">Постаматы с вещами в аренду — готовый бизнес без персонала</h1>
          <p className="page-subtitle">
            naprokatberu — это сеть автоматических точек аренды техники и бытовых вещей. Вы ставите
            постамат в проходном месте, а сервис, каталог, оплата и поддержка клиентов работают
            автоматически. Доход идёт круглосуточно, штат держать не нужно.
          </p>
          <div className="franchise-hero-banner">
            <img src="/franchise-hero.jpg" alt="Постамат naprokatberu с вещами в аренду" />
          </div>
          <a className="button button-primary" href="#consultation">
            Стать партнёром
            <ArrowRight size={18} />
          </a>
        </div>
        <div className="franchise-metrics" aria-label="Ключевые показатели">
          {metrics.map((m) => (
            <div className="franchise-metric" key={m.label}>
              <strong>{m.value}</strong>
              <span>{m.label}</span>
              {m.note ? <small>{m.note}</small> : null}
            </div>
          ))}
        </div>
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Новый формат шеринга</p>
          <h2 className="section-heading">Аренда через постаматы — следующий шаг рынка совместного потребления</h2>
        </div>
        <div className="benefit-grid benefit-grid--2col">
          {advantages.map((item) => {
            const Icon = item.icon;
            return (
              <article className="benefit-card" key={item.title}>
                <span className="icon-badge">
                  <Icon size={20} />
                </span>
                <strong>{item.title}</strong>
                <p>{item.text}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Как это работает для клиента</p>
          <h2 className="section-heading">«Вещь как услуга» — просто и быстро</h2>
        </div>
        <ol className="franchise-steps">
          {clientSteps.map((step, index) => {
            const Icon = step.icon;
            return (
              <li className="franchise-step" key={step.title}>
                <span className="franchise-step-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="franchise-step-icon">
                  <Icon size={22} />
                </span>
                <span>
                  <strong>{step.title}</strong>
                  <small>{step.text}</small>
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Где ставить постамат</p>
          <h2 className="section-heading">Подберём решение под ваше место</h2>
        </div>
        <div className="benefit-grid">
          {placements.map((item) => {
            const Icon = item.icon;
            return (
              <article className="benefit-card" key={item.title}>
                <span className="icon-badge">
                  <Icon size={20} />
                </span>
                <strong>{item.title}</strong>
                <p>{item.text}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="surface support-wide franchise-made-in-ru">
        <Factory size={28} />
        <div>
          <p className="eyebrow">Сделано в России</p>
          <h2 className="section-title">Оборудование российского производства</h2>
          <p className="muted">
            Постаматы выпускаются в России, не зависят от импорта и санкционных рисков. Запчасти и
            обслуживание доступны без долгого ожидания поставок из-за рубежа.
          </p>
        </div>
      </section>

      <section className="section-band franchise-economics">
        <div className="section-kicker">
          <p className="eyebrow">Экономика точки</p>
          <h2 className="section-heading">Прозрачная модель окупаемости</h2>
        </div>
        <div className="benefit-grid">
          <article className="benefit-card">
            <span className="icon-badge">
              <Wallet size={20} />
            </span>
            <strong>Низкий порог входа</strong>
            <p>Старт от 550 000 ₽, возможен лизинг оборудования от партнёра.</p>
          </article>
          <article className="benefit-card">
            <span className="icon-badge">
              <TrendingUp size={20} />
            </span>
            <strong>Доход без штата</strong>
            <p>Постамат работает 24/7, расходов на персонал нет.</p>
          </article>
          <article className="benefit-card">
            <span className="icon-badge">
              <Users size={20} />
            </span>
            <strong>Готовая аудитория</strong>
            <p>Сервисом уже пользуются десятки тысяч арендаторов.</p>
          </article>
          <article className="benefit-card">
            <span className="icon-badge">
              <MapPinned size={20} />
            </span>
            <strong>Поддержка запуска</strong>
            <p>Поможем с местом, наполнением каталога и продвижением точки.</p>
          </article>
        </div>
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Референсы в мире</p>
          <h2 className="section-heading">Модель уже доказала себя за рубежом</h2>
        </div>
        <div className="surface detail-panel">
          <p className="muted">
            Спрос на доступ вместо владения растёт во всём мире, и в России ниша только формируется.
          </p>
        </div>
      </section>

      <section className="surface franchise-cta" id="consultation">
        <div className="franchise-cta-copy">
          <p className="eyebrow">Получите консультацию</p>
          <h2 className="section-title">Расскажем, как открыть точку и сколько можно заработать</h2>
          <ul className="franchise-cta-list">
            <li>Все нюансы запуска под ключ</li>
            <li>Сроки открытия и подбор места</li>
            <li>Стоимость старта и расчёт прибыли</li>
          </ul>
        </div>
        {submitted ? (
          <div className="franchise-form-done" role="status">
            <PackageCheck size={28} />
            <p>Спасибо! Откроется почтовый клиент — отправьте письмо, и мы свяжемся с вами.</p>
          </div>
        ) : (
          <form className="franchise-form" onSubmit={handleSubmit}>
            <label className="field">
              <span>Как к вам обращаться</span>
              <input className="input" name="name" type="text" required placeholder="Имя" maxLength={120} />
            </label>
            <label className="field">
              <span>Телефон</span>
              <input className="input" name="phone" type="tel" required placeholder="+7 900 000-00-00" maxLength={32} />
            </label>
            <label className="field">
              <span>Город</span>
              <input className="input" name="city" type="text" placeholder="Город размещения" maxLength={120} />
            </label>
            <button className="button button-primary" type="submit">
              Получить консультацию
            </button>
            <p className="franchise-form-consent">
              Нажимая кнопку, вы соглашаетесь на обработку персональных данных.
            </p>
          </form>
        )}
      </section>

      <section className="section-band franchise-downloads">
        <div className="section-kicker">
          <p className="eyebrow">Материалы</p>
          <h2 className="section-heading">Полезное перед стартом</h2>
        </div>
        <div className="benefit-grid">
          <article className="benefit-card">
            <strong>Пошаговый план открытия</strong>
            <p>Как запустить точку аренды без персонала — по шагам.</p>
            <a className="button button-secondary" href="#consultation">
              Запросить план
            </a>
          </article>
          <article className="benefit-card">
            <strong>Финансовая модель</strong>
            <p>Расчёт окупаемости точки аренды через постамат.</p>
            <a className="button button-secondary" href="#consultation">
              Запросить модель
            </a>
          </article>
        </div>
      </section>

      <section className="surface support-wide">
        <Boxes size={28} />
        <div>
          <p className="eyebrow">Готовы обсудить?</p>
          <h2 className="section-title">Станьте партнёром naprokatberu</h2>
          <p className="muted">
            Оставьте заявку — подберём формат точки под ваше место и проведём через весь путь
            запуска: от установки постамата до первых аренд.
          </p>
        </div>
        <Link className="button button-dark" href="#consultation">
          Стать партнёром
        </Link>
      </section>
    </PageChrome>
  );
}
