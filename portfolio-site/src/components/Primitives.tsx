import type { ReactNode } from "react";
import type { StatusTone } from "@/data/caseStudy";

interface SectionHeaderProps {
  number: string;
  title: string;
  description: string;
  label: string;
}

export function SectionHeader({ number, title, description, label }: SectionHeaderProps) {
  return (
    <header className="section-head">
      <div>
        <div className="section-head__number">{number} / 08</div>
        <div className="kicker mt-3">{label}</div>
      </div>
      <h2 className="section-head__title">{title}</h2>
      <p className="section-head__description">{description}</p>
    </header>
  );
}

export function Badge({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function EvidenceNote({ children }: { children: ReactNode }) {
  return <p className="evidence-note">{children}</p>;
}

interface StatProps {
  value: string;
  label: string;
  note: string;
}

export function Stat({ value, label, note }: StatProps) {
  return (
    <div className="stat">
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
      <p className="stat__note">{note}</p>
    </div>
  );
}
