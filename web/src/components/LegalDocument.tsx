import type { LegalBlock, LegalDoc } from "@/shared/legal/types";

function BlockView({ block }: { block: LegalBlock }) {
  switch (block.kind) {
    case "text":
      return <p className="legal-text">{block.text}</p>;
    case "clause":
      return (
        <p className="legal-clause">
          <span className="legal-clause-n">{block.n}</span>
          <span>{block.text}</span>
        </p>
      );
    case "subtitle":
      return <h3 className="legal-subtitle">{block.text}</h3>;
    case "list":
      return (
        <ul className="legal-list">
          {block.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      );
    case "definitions":
      return (
        <dl className="legal-definitions">
          {block.items.map((item) => (
            <div className="legal-definition" key={item.term}>
              <dt>{item.term}</dt>
              <dd>{item.text}</dd>
            </div>
          ))}
        </dl>
      );
    case "contacts":
      return (
        <ul className="legal-contacts">
          {block.items.map((item) => (
            <li key={`${item.label ?? ""}${item.value}`}>
              {item.label ? <span className="legal-contact-label">{item.label}</span> : null}
              {item.href ? (
                <a className="legal-contact-value legal-link" href={item.href}>
                  {item.value}
                </a>
              ) : (
                <span className="legal-contact-value">{item.value}</span>
              )}
            </li>
          ))}
        </ul>
      );
    case "priceTable":
      return (
        <div className="legal-table-scroll">
          <table className="legal-table">
            <thead>
              <tr>
                <th scope="col">{block.head[0]}</th>
                <th scope="col">{block.head[1]}</th>
                <th scope="col">{block.head[2]}</th>
              </tr>
            </thead>
            {block.groups.map((group) => (
              <tbody key={group.title}>
                <tr className="legal-table-group">
                  <th scope="colgroup" colSpan={3}>
                    {group.title}
                  </th>
                </tr>
                {group.rows.map((row) => (
                  <tr key={`${group.title}-${row.name}`}>
                    <td>{row.name}</td>
                    <td className="legal-table-num">{row.qty}</td>
                    <td className="legal-table-num">{row.price}</td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      );
    default:
      return null;
  }
}

export function LegalDocument({ doc }: { doc: LegalDoc }) {
  const tocSections = doc.sections.filter((section) => section.title !== "");

  return (
    <div className="legal-doc">
      <nav className="surface legal-toc" aria-label="Содержание документа">
        <p className="eyebrow">Содержание</p>
        <ol className="legal-toc-list">
          {tocSections.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`}>
                {section.number ? (
                  <span className="legal-toc-n">{section.number}.</span>
                ) : null}
                <span>{section.title}</span>
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <div className="surface legal-body">
        {doc.sections.map((section) => (
          <section className="legal-section" id={section.id} key={section.id}>
            {section.title ? (
              <h2 className="legal-section-title">
                {section.number ? (
                  <span className="legal-section-n">{section.number}.</span>
                ) : null}
                <span>{section.title}</span>
              </h2>
            ) : null}
            {section.blocks.map((block, index) => (
              <BlockView block={block} key={`${section.id}-${index}`} />
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
