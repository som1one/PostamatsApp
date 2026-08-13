export type LegalBlock =
  | { kind: "text"; text: string }
  | { kind: "clause"; n: string; text: string }
  | { kind: "subtitle"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "definitions"; items: Array<{ term: string; text: string }> }
  | { kind: "contacts"; items: Array<{ label?: string; value: string; href?: string }> }
  | {
      kind: "priceTable";
      head: [string, string, string];
      groups: Array<{
        title: string;
        rows: Array<{ name: string; qty: string; price: string }>;
      }>;
    };

export type LegalSection = {
  id: string;
  number?: string;
  title: string;
  blocks: LegalBlock[];
};

export type LegalDoc = {
  title: string;
  subtitle?: string;
  place?: string;
  edition: string;
  sections: LegalSection[];
};
