import { LegalDocument } from "@/components/LegalDocument";
import { PageChrome } from "@/components/PageChrome";
import { consentDoc } from "@/shared/legal/consent";

export function ConsentClient() {
  return (
    <PageChrome>
      <section className="faq-hero legal-hero">
        <p className="eyebrow">Документы</p>
        <h1 className="page-title">{consentDoc.title}</h1>
        <p className="page-subtitle">
          Какие персональные данные и для чего обрабатывает naprokatberu, если вы отметили
          согласие в форме на сайте.
        </p>
        <p className="legal-meta">
          {consentDoc.subtitle ? <span>{consentDoc.subtitle}</span> : null}
          <span>{consentDoc.edition}</span>
        </p>
      </section>

      <LegalDocument doc={consentDoc} />
    </PageChrome>
  );
}
