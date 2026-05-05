import Link from "next/link";
import { Boxes, Leaf, LockKeyhole, MapPinned, PackageCheck, ShieldCheck } from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { safetyItems } from "@/shared/content";

export default function AboutPage() {
  return (
    <PageChrome>
      <section className="about-hero">
        <div>
          <p className="eyebrow">О сервисе</p>
          <h1 className="page-title">Мы делаем вещи доступными без лишних покупок</h1>
          <p className="page-subtitle">
            naprokatberu помогает брать технику и бытовые вещи на время: для вечера, ремонта,
            уборки, поездки или разовой задачи. Получение и возврат строятся вокруг постаматов,
            чтобы аренда была предсказуемой и быстрой.
          </p>
          <Link className="button button-primary" href="/catalog">
            Перейти в каталог
          </Link>
        </div>
        <div className="about-visual" aria-hidden="true">
          <ol className="about-plan">
            <li className="about-plan-step">
              <span className="about-plan-index">01</span>
              <span className="about-plan-icon">
                <Boxes size={22} />
              </span>
              <span>
                <strong>Каталог</strong>
                <small>выберите вещь и срок</small>
              </span>
            </li>
            <li className="about-plan-step">
              <span className="about-plan-index">02</span>
              <span className="about-plan-icon">
                <MapPinned size={22} />
              </span>
              <span>
                <strong>Постамат</strong>
                <small>заберите заказ по коду</small>
              </span>
            </li>
            <li className="about-plan-step">
              <span className="about-plan-index">03</span>
              <span className="about-plan-icon">
                <PackageCheck size={22} />
              </span>
              <span>
                <strong>Возврат</strong>
                <small>верните комплект обратно</small>
              </span>
            </li>
          </ol>
        </div>
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Shared economy</p>
          <h2 className="section-heading">Одна вещь работает для многих людей</h2>
        </div>
        <div className="benefit-grid">
          <article className="benefit-card">
            <span className="icon-badge">
              <Leaf size={20} />
            </span>
            <strong>Меньше импульсных покупок</strong>
            <p>Редкая техника не лежит без дела после одного сценария.</p>
          </article>
          <article className="benefit-card">
            <span className="icon-badge">
              <MapPinned size={20} />
            </span>
            <strong>Городская доступность</strong>
            <p>Постаматы превращают выдачу в понятный маршрут рядом с домом.</p>
          </article>
          <article className="benefit-card">
            <span className="icon-badge">
              <ShieldCheck size={20} />
            </span>
            <strong>Порядок в процессе</strong>
            <p>Товар, тариф, резерв, оплата и возврат разделены на контролируемые шаги.</p>
          </article>
        </div>
      </section>

      <section className="section-band about-grid">
        <div className="surface detail-panel">
          <p className="eyebrow">Что мы делаем</p>
          <h2 className="section-title">Собираем аренду в один цифровой сценарий</h2>
          <p className="muted">
            Каталог показывает наличие по городу, карточка товара помогает выбрать постамат и
            срок, а оформление помогает закрепить товар и перейти к оплате.
          </p>
        </div>
        <div className="surface detail-panel">
          <p className="eyebrow">Почему удобно</p>
          <h2 className="section-title">Не нужно договариваться вручную</h2>
          <p className="muted">
            Пользователь видит стоимость до оформления, получает код после оплаты и возвращает
            комплект через понятный процесс.
          </p>
        </div>
      </section>

      <section className="section-band">
        <div className="section-kicker">
          <p className="eyebrow">Безопасность</p>
          <h2 className="section-heading">Как поддерживаем порядок</h2>
        </div>
        <div className="benefit-grid">
          {safetyItems.map((item) => {
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

      <section className="surface support-wide">
        <LockKeyhole size={28} />
        <div>
          <p className="eyebrow">Надежный процесс</p>
          <h2 className="section-title">Аренда идет по понятным и прозрачным шагам</h2>
          <p className="muted">
            Вы видите товар, срок, точку получения и стоимость до оплаты, а все ключевые действия
            остаются собранными в одном маршруте аренды.
          </p>
        </div>
        <Link className="button button-dark" href="/catalog">
          Начать аренду
        </Link>
      </section>
    </PageChrome>
  );
}
