"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

export function FAQAccordion({
  items,
}: {
  items: Array<{ question: string; answer: string; category: string }>;
}) {
  const [openQuestion, setOpenQuestion] = useState(items[0]?.question || "");

  return (
    <div className="faq-list">
      {items.map((item) => {
        const open = openQuestion === item.question;
        return (
          <article className={`faq-item ${open ? "is-open" : ""}`} key={item.question}>
            <button
              type="button"
              onClick={() => setOpenQuestion(open ? "" : item.question)}
              aria-expanded={open}
            >
              <span>{item.question}</span>
              <ChevronDown size={18} />
            </button>
            {open ? <p>{item.answer}</p> : null}
          </article>
        );
      })}
    </div>
  );
}

