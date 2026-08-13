import { LegalDocument } from "@/components/LegalDocument";
import { PageChrome } from "@/components/PageChrome";
import { privacyDoc } from "@/shared/legal/privacy";

export function PrivacyClient() {
  return (
    <PageChrome>
      <section className="faq-hero legal-hero">
        <p className="eyebrow">Документы</p>
        <h1 className="page-title">{privacyDoc.title}</h1>
        <p className="page-subtitle">
          Как naprokatberu собирает, обрабатывает, хранит и защищает персональные данные
          пользователей.
        </p>
        <p className="legal-meta">
          {privacyDoc.subtitle ? <span>{privacyDoc.subtitle}</span> : null}
          <span>{privacyDoc.edition}</span>
        </p>
      </section>

      <LegalDocument doc={privacyDoc} />
    </PageChrome>
  );
}
