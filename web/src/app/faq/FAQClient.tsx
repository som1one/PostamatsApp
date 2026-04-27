"use client";

import { useMemo, useState } from "react";
import { Headphones, Search } from "lucide-react";
import { FAQAccordion } from "@/components/FAQAccordion";
import { PageChrome } from "@/components/PageChrome";
import { faqItems } from "@/shared/content";

const categories = [
  "Все",
  "Общие вопросы",
  "Заказ",
  "Верификация",
  "Получение заказа",
  "Возврат",
  "Товары",
];

export function FAQClient() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Все");
  const items = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return faqItems.filter((item) => {
      const categoryMatch = category === "Все" || item.category === category;
      const queryMatch =
        !normalized ||
        item.question.toLowerCase().includes(normalized) ||
        item.answer.toLowerCase().includes(normalized);
      return categoryMatch && queryMatch;
    });
  }, [category, query]);

  return (
    <PageChrome>
      <section className="faq-hero">
        <p className="eyebrow">FAQ</p>
        <h1 className="page-title">Ответы перед первой арендой</h1>
        <p className="page-subtitle">
          Собрали вопросы про заказ, верификацию, получение, возврат и работу
          постаматов. Поиск работает по вопросу и ответу.
        </p>
      </section>

      <section className="surface faq-controls">
        <label className="field">
          <span>Поиск</span>
          <span className="search-field">
            <Search size={18} />
            <input
              className="input"
              value={query}
              placeholder="Например: возврат, код, оплата"
              onChange={(event) => setQuery(event.target.value)}
            />
          </span>
        </label>
        <div className="category-tabs">
          {categories.map((item) => (
            <button
              className={`category-tab ${category === item ? "is-active" : ""}`}
              key={item}
              type="button"
              onClick={() => setCategory(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </section>

      <FAQAccordion items={items} />

      <section className="surface support-wide">
        <Headphones size={28} />
        <div>
          <p className="eyebrow">Поддержка</p>
          <h2 className="section-title">Не нашли ответ?</h2>
          <p className="muted">
            Напишите в поддержку: поможем выбрать товар, разобраться с постаматом
            или проверить статус оплаты.
          </p>
        </div>
        <a className="button button-primary" href="mailto:support@example.com">
          Связаться
        </a>
      </section>
    </PageChrome>
  );
}

