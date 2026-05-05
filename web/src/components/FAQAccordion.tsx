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
      {items.map((item, index) => {
        const open = openQuestion === item.question;
        const answerId = `faq-answer-${index}`;
        return (
          <article className={`faq-item ${open ? "is-open" : ""}`} key={item.question}>
            <button
              type="button"
              onClick={() => setOpenQuestion(open ? "" : item.question)}
              aria-expanded={open}
              aria-controls={answerId}
            >
              <span>{item.question}</span>
              <ChevronDown size={18} />
            </button>
            <div className="faq-answer-wrap" id={answerId} aria-hidden={!open}>
              <div className="faq-answer-inner">
                <p>{item.answer}</p>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
