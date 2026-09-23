import type { ReactNode } from "react";
import Link from "next/link";

type ConsentCheckboxProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  name?: string;
};

/**
 * Галочка согласия под формой. По умолчанию не отмечена — пользователь
 * ставит её сам, иначе согласие по 152-ФЗ не считается выраженным.
 */
export function ConsentCheckbox({ checked, onChange, children, name }: ConsentCheckboxProps) {
  return (
    <label className="consent-checkbox">
      <input
        type="checkbox"
        name={name}
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        required
      />
      <span>{children}</span>
    </label>
  );
}

/** Одна галочка для форм обратной связи. */
export function PersonalDataConsent({
  checked,
  onChange,
}: Pick<ConsentCheckboxProps, "checked" | "onChange">) {
  return (
    <ConsentCheckbox checked={checked} onChange={onChange} name="personalDataConsent">
      Даю{" "}
      <Link className="legal-link" href="/consent" target="_blank">
        согласие на обработку персональных данных
      </Link>
    </ConsentCheckbox>
  );
}
