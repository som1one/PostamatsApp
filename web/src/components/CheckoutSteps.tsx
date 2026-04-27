import type { ReactNode } from "react";

export type CheckoutStep = {
  title: string;
  text?: string;
  icon?: ReactNode;
  state?: "complete" | "current" | "idle";
};

export function CheckoutSteps({ steps }: { steps: CheckoutStep[] }) {
  return (
    <div className="checkout-steps">
      {steps.map((step, index) => (
        <div
          className={`checkout-step ${step.state === "complete" ? "is-complete" : ""} ${
            step.state === "current" ? "is-current" : ""
          }`}
          key={`${step.title}-${index}`}
        >
          <span className="checkout-step-index">{step.icon || index + 1}</span>
          <div>
            <strong>{step.title}</strong>
            {step.text ? <span>{step.text}</span> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
