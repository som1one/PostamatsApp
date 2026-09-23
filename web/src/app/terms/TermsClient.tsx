import { LegalDocument } from "@/components/LegalDocument";
import { PageChrome } from "@/components/PageChrome";
import { userAgreementDoc } from "@/shared/legal/userAgreement";

export function TermsClient() {
  return (
    <PageChrome>
      <section className="faq-hero legal-hero">
        <p className="eyebrow">Документы</p>
        <h1 className="page-title">{userAgreementDoc.title}</h1>
        <p className="page-subtitle">
          Правила использования сайта, личного кабинета и постаматов naprokatberu.
        </p>
        <p className="legal-meta">
          {userAgreementDoc.subtitle ? <span>{userAgreementDoc.subtitle}</span> : null}
          <span>{userAgreementDoc.edition}</span>
        </p>
      </section>

      <LegalDocument doc={userAgreementDoc} />
    </PageChrome>
  );
}
