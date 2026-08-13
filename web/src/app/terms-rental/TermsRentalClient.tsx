import { LegalDocument } from "@/components/LegalDocument";
import { PageChrome } from "@/components/PageChrome";
import { offerDoc } from "@/shared/legal/offer";

export function TermsRentalClient() {
  return (
    <PageChrome>
      <section className="faq-hero legal-hero">
        <p className="eyebrow">Документы</p>
        <h1 className="page-title">{offerDoc.title}</h1>
        <p className="page-subtitle">
          Условия аренды техники и вещей через постаматы naprokatberu.
        </p>
        <p className="legal-meta">
          {offerDoc.place ? <span>{offerDoc.place}</span> : null}
          <span>{offerDoc.edition}</span>
        </p>
      </section>

      <LegalDocument doc={offerDoc} />
    </PageChrome>
  );
}
