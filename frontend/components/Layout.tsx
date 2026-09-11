import { ReactNode } from "react";

export function Panel({ title, subtitle, actions, children }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-bg-raised">
      {(title || actions) && (
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
          <div>
            {title && <h2 className="text-[13px] font-semibold text-text">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[12px] text-text-faint">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, breadcrumb }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; breadcrumb?: ReactNode }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div>
        {breadcrumb && <div className="mb-1 text-[12px] text-text-faint">{breadcrumb}</div>}
        <h1 className="text-[19px] font-semibold text-text tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-text-muted max-w-3xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border py-12 text-center">
      <p className="text-[13px] font-medium text-text-muted">{title}</p>
      {detail && <p className="max-w-sm text-[12px] text-text-faint">{detail}</p>}
    </div>
  );
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-danger/30 bg-danger-muted px-4 py-3 text-[13px] text-danger">
      {message}
    </div>
  );
}

export function StatCard({ label, value, tone = "neutral", href }: { label: string; value: ReactNode; tone?: "neutral" | "warn" | "danger"; href?: string }) {
  const toneClass = tone === "warn" ? "text-warn" : tone === "danger" ? "text-danger" : "text-text";
  const content = (
    <div className="rounded-lg border border-border bg-bg-raised px-4 py-3 transition-colors hover:border-border-strong">
      <p className="text-[11px] font-medium uppercase tracking-wide text-text-faint">{label}</p>
      <p className={`mt-1.5 text-[22px] font-semibold tabular-nums ${toneClass}`}>{value}</p>
    </div>
  );
  if (href) {
    return <a href={href} className="block">{content}</a>;
  }
  return content;
}

export function KeyValue({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-1.5">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-text-faint">{label}</dt>
      <dd className="text-[13px] text-text">{children}</dd>
    </div>
  );
}
