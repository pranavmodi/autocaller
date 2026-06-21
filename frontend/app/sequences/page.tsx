"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Mail,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Trash2,
  Quote,
  Building2,
  Users,
  Search,
  Phone,
  MailX,
} from "lucide-react";
import {
  backfillFirmContacts,
  deleteContact,
  getContactDetail,
  listSequenceTemplates,
  listContactsForFirm,
  listFirmsWithContacts,
  listSequences,
  pauseSequence,
  previewSequence,
  resumeSequence,
  startSequence,
  type FirmContact,
  type FirmWithContacts,
  type SequenceListItem,
  type SequenceTemplate,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export default function SequencesPage() {
  const qc = useQueryClient();

  const firms = useQuery({
    queryKey: ["firms-with-contacts"],
    queryFn: listFirmsWithContacts,
  });

  const [pifId, setPifId] = useState<string>("");
  const [contactId, setContactId] = useState<string>("");
  const [templateKey, setTemplateKey] = useState<string>("possible_minds_dynamic");

  const templates = useQuery({
    queryKey: ["sequence-templates"],
    queryFn: listSequenceTemplates,
  });

  const contacts = useQuery({
    queryKey: ["contacts-for-firm", pifId],
    queryFn: () => listContactsForFirm(pifId),
    enabled: !!pifId,
  });

  // Reset selected contact when firm changes.
  useEffect(() => {
    setContactId("");
  }, [pifId]);

  const detail = useQuery({
    queryKey: ["contact-detail", contactId, templateKey],
    queryFn: () => getContactDetail(contactId, templateKey),
    enabled: !!contactId,
  });

  const preview = useQuery({
    queryKey: ["sequence-preview", contactId, templateKey],
    queryFn: () => previewSequence(contactId, templateKey),
    enabled: !!contactId,
  });

  const backfill = useMutation({
    mutationFn: backfillFirmContacts,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["firms-with-contacts"] }),
  });

  return (
    <div className="mx-auto min-w-0 max-w-[1400px] space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <span className="text-neutral-300">/</span>
        <h1 className="text-lg font-semibold text-neutral-900">
          Email Sequences
        </h1>
        <span className="text-xs text-neutral-400">
          selectable templates — one contact at a time
        </span>
        <button
          onClick={() => backfill.mutate()}
          disabled={backfill.isPending}
          className="rounded-md border border-neutral-200 px-2.5 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50 disabled:opacity-60 sm:ml-auto"
        >
          {backfill.isPending ? "backfilling…" : "Refresh contacts"}
        </button>
      </div>

      {backfill.data && (
        <div className="mb-3 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          Backfill complete: {backfill.data.inserted} new contacts,{" "}
          {backfill.data.updated} updated across {backfill.data.firms} firms.
        </div>
      )}

      <ActiveSequencesPanel
        onJump={(s) => {
          setTemplateKey(s.template_key);
          setPifId(s.pif_id);
          // Set contactId after pifId so the contact list has loaded.
          setTimeout(() => setContactId(s.contact_id), 0);
        }}
      />

      <div className="grid gap-4 lg:grid-cols-12">
        {/* Left rail — firm + contact dropdowns */}
        <aside className="col-span-12 space-y-3 lg:col-span-4 xl:col-span-3">
          <FirmDropdown
            firms={firms.data ?? []}
            isLoading={firms.isLoading}
            value={pifId}
            onChange={setPifId}
          />
          <ContactDropdown
            contacts={contacts.data ?? []}
            isLoading={contacts.isLoading}
            disabled={!pifId}
            value={contactId}
            onChange={setContactId}
          />
          <TemplateDropdown
            templates={templates.data ?? []}
            isLoading={templates.isLoading}
            value={templateKey}
            onChange={setTemplateKey}
          />
        </aside>

        {/* Right pane — contact + preview + start */}
        <main className="col-span-12 lg:col-span-8 xl:col-span-9">
          {!contactId && (
            <div className="rounded-xl border border-dashed border-neutral-200 bg-white px-6 py-12 text-center text-sm text-neutral-400">
              Pick a firm, then a contact. The four rendered emails will
              appear here. The Start button stays disabled until you've
              confirmed the drafts.
            </div>
          )}
          {contactId && detail.data && preview.data && (
            <ContactPanel
              detail={detail.data}
              steps={preview.data}
              templateKey={templateKey}
              onStarted={() => {
                qc.invalidateQueries({ queryKey: ["contact-detail", contactId, templateKey] });
              }}
              onDeleted={() => {
                qc.invalidateQueries({ queryKey: ["contacts-for-firm", pifId] });
                qc.invalidateQueries({ queryKey: ["firms-with-contacts"] });
                qc.invalidateQueries({ queryKey: ["sequences-list"] });
                setContactId("");
              }}
            />
          )}
          {contactId && (detail.isLoading || preview.isLoading) && (
            <div className="flex items-center gap-2 rounded-xl border border-neutral-200 bg-white px-6 py-8 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              loading…
            </div>
          )}
        </main>
      </div>
    </div>
  );
}


function ActiveSequencesPanel({
  onJump,
}: {
  onJump: (s: SequenceListItem) => void;
}) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"active" | "paused" | "completed" | "all">("active");
  const seqs = useQuery({
    queryKey: ["all-sequences", filter],
    queryFn: () => listSequences(filter === "all" ? undefined : filter),
    refetchInterval: 30_000,
  });

  const pause = useMutation({
    mutationFn: (vars: { contactId: string; reason: string; templateKey: string }) =>
      pauseSequence(vars.contactId, vars.reason, vars.templateKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      qc.invalidateQueries({ queryKey: ["contact-detail"] });
    },
  });
  const resume = useMutation({
    mutationFn: (s: SequenceListItem) => resumeSequence(s.contact_id, s.template_key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      qc.invalidateQueries({ queryKey: ["contact-detail"] });
    },
  });

  const items = seqs.data ?? [];

  return (
    <section className="mb-4 rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
          All sequences
        </h2>
        <div className="flex gap-1">
          {(["active", "paused", "completed", "all"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={cn(
                "rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors",
                filter === s
                  ? "bg-neutral-900 text-white"
                  : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200",
              )}
            >
              {s}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-neutral-400">
          {seqs.isLoading ? "loading…" : `${items.length} ${filter}`}
        </span>
      </div>
      {items.length === 0 && !seqs.isLoading && (
        <div className="px-4 py-6 text-center text-xs text-neutral-400">
          No {filter === "all" ? "" : filter} sequences yet.
          {filter === "active" && " Pick a firm + contact below to start one."}
        </div>
      )}
      {items.length > 0 && (
        <div className="mobile-table-card max-h-72 overflow-y-auto md:overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-neutral-100 text-[11px] uppercase tracking-wider text-neutral-500">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Contact</th>
                <th className="px-2 py-2 text-left font-medium">Firm</th>
                <th className="px-2 py-2 text-left font-medium">Step</th>
                <th className="px-2 py-2 text-left font-medium">Variant</th>
                <th className="px-2 py-2 text-left font-medium">Next due</th>
                <th className="px-2 py-2 text-left font-medium">Status</th>
                <th className="px-2 py-2 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr
                  key={s.sequence_id}
                  className="cursor-pointer border-b border-neutral-100 hover:bg-neutral-50"
                  onClick={() => onJump(s)}
                >
                  <td data-label="Contact" className="px-4 py-2">
                    <div className="font-medium text-neutral-800">
                      {s.contact_name || "—"}
                    </div>
                    <div className="font-mono text-[11px] text-neutral-500">
                      {s.contact_email || "no email"}
                    </div>
                  </td>
                  <td data-label="Firm" className="px-2 py-2 text-xs text-neutral-700">
                    {s.firm_name || s.pif_id.slice(0, 8)}
                  </td>
                  <td data-label="Step" className="px-2 py-2 font-mono text-xs text-neutral-700">
                    {s.current_step}/{s.steps_total}
                  </td>
	                  <td data-label="Variant" className="px-2 py-2 text-xs text-neutral-600">
	                    <div>{s.template_key}</div>
	                    <div className="text-[10px] text-neutral-400">{s.variant}</div>
	                  </td>
                  <td data-label="Next due" className="px-2 py-2 font-mono text-[11px] text-neutral-500">
                    {s.next_step_due_at
                      ? new Date(s.next_step_due_at).toLocaleString("en-IN", {
                          timeZone: "Asia/Kolkata",
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit",
                        })
                      : "—"}
                  </td>
                  <td data-label="Status" className="px-2 py-2">
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[11px] font-medium",
                        s.status === "active" && "bg-emerald-50 text-emerald-700",
                        s.status === "paused" && "bg-amber-50 text-amber-700",
                        s.status === "completed" && "bg-neutral-100 text-neutral-600",
                      )}
                    >
                      {s.status}
                    </span>
                    {s.paused_reason && (
                      <div
                        className="mt-0.5 max-w-[16rem] truncate text-[10px] text-amber-700"
                        title={s.paused_reason}
                      >
                        {s.paused_reason}
                      </div>
                    )}
                  </td>
                  <td
                    data-label="Action"
                    className="px-2 py-2 text-right"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {s.status === "active" && (
                      <button
                        onClick={() => {
                          const reason = window.prompt(
                            `Pause sequence for ${s.contact_name}?\n\nReason (e.g. 'replied: not interested'):`,
                            "replied",
                          );
                          if (reason !== null) {
	                            pause.mutate({
	                              contactId: s.contact_id,
	                              reason,
	                              templateKey: s.template_key,
	                            });
                          }
                        }}
                        disabled={pause.isPending}
                        className="rounded border border-amber-300 bg-white px-2 py-0.5 text-[11px] font-medium text-amber-800 hover:bg-amber-50 disabled:opacity-60"
                      >
                        Pause
                      </button>
                    )}
                    {s.status === "paused" && (
                      <button
	                        onClick={() => resume.mutate(s)}
                        disabled={resume.isPending}
                        className="rounded border border-emerald-300 bg-white px-2 py-0.5 text-[11px] font-medium text-emerald-800 hover:bg-emerald-50 disabled:opacity-60"
                      >
                        Resume
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}


function FirmDropdown({
  firms,
  isLoading,
  value,
  onChange,
}: {
  firms: FirmWithContacts[];
  isLoading: boolean;
  value: string;
  onChange: (pifId: string) => void;
}) {
  const [filter, setFilter] = useState("");
  // Server returns firms with quote first (ordered by extraction recency
  // desc), then firms without a quote (alphabetical). We trust that order
  // and only narrow it client-side via the filter.
  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return firms;
    return firms.filter((r) => (r.firm_name || "").toLowerCase().includes(f));
  }, [firms, filter]);
  const withQuoteCount = useMemo(
    () => firms.filter((f) => f.has_pain_quote).length,
    [firms],
  );

  return (
    <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
      <header className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <Building2 className="h-3.5 w-3.5 text-neutral-400" />
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Firm
        </h2>
        <span className="ml-auto text-[10px] tabular-nums text-neutral-400">
          {firms.length}
          {withQuoteCount > 0 && (
            <span className="text-amber-600"> · {withQuoteCount} with quote</span>
          )}
        </span>
      </header>
      <div className="border-b border-neutral-100 px-3 py-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-neutral-400" />
          <input
            type="text"
            placeholder="Filter by name…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full rounded-md border border-neutral-200 bg-neutral-50 py-1.5 pl-7 pr-2 text-xs text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:bg-white focus:outline-none"
          />
        </div>
      </div>
      {isLoading && (
        <div className="px-4 py-6 text-center text-xs text-neutral-400">
          loading…
        </div>
      )}
      {!isLoading && firms.length === 0 && (
        <div className="m-3 rounded border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-800">
          No firms with contacts yet. Click <b>Refresh contacts</b> at the
          top to backfill from PIF Stats.
        </div>
      )}
      {!isLoading && firms.length > 0 && filtered.length === 0 && (
        <div className="px-4 py-6 text-center text-xs text-neutral-400">
          No firms match &ldquo;{filter}&rdquo;
        </div>
      )}
      <div className="max-h-[520px] overflow-y-auto py-1">
        {filtered.map((f) => {
          const selected = value === f.pif_id;
          const ago = humanAgo(f.extracted_at);
          return (
            <button
              key={f.pif_id}
              onClick={() => onChange(f.pif_id)}
              className={cn(
                "group relative flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors",
                selected
                  ? "bg-neutral-50"
                  : "hover:bg-neutral-50",
              )}
            >
              {selected && (
                <span className="absolute inset-y-1 left-0 w-0.5 rounded-r bg-neutral-900" />
              )}
              <span
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  f.has_pain_quote ? "bg-amber-400" : "bg-neutral-200",
                )}
                title={
                  f.has_pain_quote
                    ? "client_communication quote available"
                    : "no pain-point quote yet"
                }
              />
              <span className="min-w-0 flex-1">
                <span
                  className={cn(
                    "block truncate text-xs font-medium",
                    selected ? "text-neutral-900" : "text-neutral-800",
                  )}
                >
                  {f.firm_name || f.pif_id.slice(0, 8)}
                </span>
                {f.has_pain_quote && ago && (
                  <span className="mt-0.5 flex items-center gap-1 text-[10px] text-amber-700">
                    <Quote className="h-2.5 w-2.5" />
                    extracted {ago}
                  </span>
                )}
              </span>
              <span
                className={cn(
                  "flex shrink-0 items-center gap-0.5 text-[10px] tabular-nums",
                  selected ? "text-neutral-600" : "text-neutral-400",
                )}
                title={`${f.contact_count} contact${f.contact_count === 1 ? "" : "s"}`}
              >
                <Users className="h-2.5 w-2.5" />
                {f.contact_count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}


function ContactDropdown({
  contacts,
  isLoading,
  disabled,
  value,
  onChange,
}: {
  contacts: FirmContact[];
  isLoading: boolean;
  disabled: boolean;
  value: string;
  onChange: (id: string) => void;
}) {
  if (disabled) return null;
  // Contacts with email come first — those are the only ones a sequence
  // can actually start on. Otherwise preserve server order.
  const sorted = useMemo(() => {
    return [...contacts].sort((a, b) => {
      const ae = a.email ? 0 : 1;
      const be = b.email ? 0 : 1;
      if (ae !== be) return ae - be;
      return 0;
    });
  }, [contacts]);
  const withEmail = useMemo(
    () => contacts.filter((c) => c.email).length,
    [contacts],
  );

  return (
    <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
      <header className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <Users className="h-3.5 w-3.5 text-neutral-400" />
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Contact
        </h2>
        <span className="ml-auto text-[10px] tabular-nums text-neutral-400">
          {contacts.length}
          {withEmail < contacts.length && (
            <span className="text-rose-600">
              {" "}
              · {contacts.length - withEmail} no-email
            </span>
          )}
        </span>
      </header>
      {isLoading && (
        <div className="px-4 py-6 text-center text-xs text-neutral-400">
          loading…
        </div>
      )}
      {!isLoading && contacts.length === 0 && (
        <div className="px-4 py-6 text-center text-xs text-neutral-400">
          No contacts at this firm.
        </div>
      )}
      <div className="max-h-[520px] overflow-y-auto py-1">
        {sorted.map((c) => {
          const selected = value === c.id;
          const hasEmail = !!c.email;
          return (
            <button
              key={c.id}
              onClick={() => onChange(c.id)}
              className={cn(
                "group relative flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors",
                selected ? "bg-neutral-50" : "hover:bg-neutral-50",
                !hasEmail && "opacity-75",
              )}
              title={!hasEmail ? "No email on file — sequence cannot start" : undefined}
            >
              {selected && (
                <span className="absolute inset-y-1 left-0 w-0.5 rounded-r bg-neutral-900" />
              )}
              <span
                className={cn(
                  "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                  hasEmail ? "bg-emerald-400" : "bg-rose-300",
                )}
              />
              <span className="min-w-0 flex-1">
                <span
                  className={cn(
                    "block truncate text-xs font-medium",
                    selected ? "text-neutral-900" : "text-neutral-800",
                  )}
                >
                  {c.full_name || "—"}
                </span>
                {c.title && (
                  <span
                    className={cn(
                      "block truncate text-[10px]",
                      selected ? "text-neutral-600" : "text-neutral-500",
                    )}
                  >
                    {c.title}
                  </span>
                )}
                <span
                  className={cn(
                    "mt-0.5 flex items-center gap-1 truncate font-mono text-[10px]",
                    hasEmail
                      ? selected
                        ? "text-neutral-600"
                        : "text-neutral-500"
                      : "text-rose-600",
                  )}
                >
                  {hasEmail ? (
                    <Mail className="h-2.5 w-2.5 shrink-0" />
                  ) : (
                    <MailX className="h-2.5 w-2.5 shrink-0" />
                  )}
                  <span className="truncate">{c.email || "no email"}</span>
                </span>
                {c.phone && (
                  <span
                    className={cn(
                      "mt-0.5 flex items-center gap-1 truncate font-mono text-[10px]",
                      selected ? "text-neutral-500" : "text-neutral-400",
                    )}
                  >
                    <Phone className="h-2.5 w-2.5 shrink-0" />
                    <span className="truncate">{c.phone}</span>
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}


function TemplateDropdown({
  templates,
  isLoading,
  value,
  onChange,
}: {
  templates: SequenceTemplate[];
  isLoading: boolean;
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
      <header className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <Mail className="h-3.5 w-3.5 text-neutral-400" />
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Sequence template
        </h2>
      </header>
      <div className="p-3">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={isLoading}
          className="w-full rounded-md border border-neutral-200 bg-white px-2 py-2 text-xs text-neutral-800"
        >
          {templates.map((t) => (
            <option key={t.template_key} value={t.template_key}>
              {t.label} ({t.steps_total} steps)
            </option>
          ))}
        </select>
        {templates.find((t) => t.template_key === value)?.description && (
          <p className="mt-2 text-[11px] leading-relaxed text-neutral-500">
            {templates.find((t) => t.template_key === value)?.description}
          </p>
        )}
      </div>
    </div>
  );
}


function humanAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  if (sec < 86400 * 30) return `${Math.floor(sec / 86400)}d ago`;
  return `${Math.floor(sec / 86400 / 30)}mo ago`;
}


function ContactPanel({
  detail,
  steps,
  templateKey,
  onStarted,
  onDeleted,
}: {
  detail: import("@/lib/api").ContactDetail;
  steps: import("@/lib/api").RenderedSequenceStep[];
  templateKey: string;
  onStarted: () => void;
  onDeleted: () => void;
}) {
  const { contact, pain, sequence, sent_steps } = detail;
  const [reviewedAll, setReviewedAll] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const start = useMutation({
    mutationFn: () => startSequence(contact.id, templateKey),
    onSuccess: () => {
      setConfirming(false);
      onStarted();
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteContact(contact.id),
    onSuccess: () => {
      setConfirmingDelete(false);
      onDeleted();
    },
  });

  const noEmail = !contact.email;
  const hasSequence = !!sequence;
  const canStart = !noEmail && !hasSequence && reviewedAll;

  return (
    <div className="space-y-4">
      {/* Contact card */}
      <section className="rounded-xl border border-neutral-200 bg-white p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-neutral-900">
              {contact.full_name || "—"}
            </h2>
            <p className="mt-0.5 truncate text-xs text-neutral-500">
              {contact.title || "—"}
            </p>
            <div className="mt-3 grid gap-1 text-xs">
              <div className="flex items-center gap-2">
                <Mail className="h-3.5 w-3.5 text-neutral-400" />
                <span
                  className={cn(
                    "font-mono",
                    contact.email ? "text-neutral-700" : "text-red-600",
                  )}
                >
                  {contact.email || "no email on file"}
                </span>
              </div>
              <div className="text-neutral-500">
                <span className="text-neutral-400">source:</span> {contact.source}
              </div>
            </div>
          </div>

          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wider text-neutral-400">
              Sequence
            </div>
            <div className="text-sm font-medium text-neutral-700">
              {templateKey} · {sequence?.variant ?? steps.length + " steps"}
            </div>
          </div>
        </div>

        {pain.pain_quote && (
          <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-700">
              Pain quote that will be injected at step 2
            </div>
            <p className="mt-1 italic text-amber-900">
              &ldquo;{pain.pain_quote}&rdquo;
            </p>
            <p className="mt-1 text-[11px] text-amber-700">
              {pain.reviewer_name ?? "anonymous"}
              {pain.review_date ? ` · ${pain.review_date}` : ""}
            </p>
          </div>
        )}
      </section>

      {/* Sequence state — already running? */}
      {sequence && (
        <SequenceStatePanel
          contactId={contact.id}
          sequence={sequence}
          sent={sent_steps}
          onMutated={onStarted}
        />
      )}

      {/* Drafts — REVIEW BEFORE SENDING */}
      <section className="rounded-xl border border-neutral-200 bg-white">
        <header className="flex items-center justify-between border-b border-neutral-100 px-5 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Email drafts ({steps.length} steps) — review before sending
          </h2>
          <span className="text-[11px] text-neutral-400">
            click a row to expand the body
          </span>
        </header>
        <div className="divide-y divide-neutral-100">
          {steps.map((s) => {
            const open = openStep === s.step;
            return (
              <div key={s.step}>
                <button
                  onClick={() => setOpenStep(open ? null : s.step)}
                  className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left hover:bg-neutral-50"
                >
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400">
                      Step {s.step} · {s.message_type}
                    </div>
                    <div className="mt-0.5 truncate text-sm font-medium text-neutral-800">
                      {s.subject}
                    </div>
                  </div>
                  <span
                    className={cn(
                      "shrink-0 text-[11px]",
                      open ? "text-neutral-700" : "text-neutral-400",
                    )}
                  >
                    {open ? "hide" : "show"}
                  </span>
                </button>
                {open && (
                  <div className="bg-neutral-50 px-5 py-4">
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-neutral-800">
                      {s.body}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <footer className="border-t border-neutral-100 px-5 py-4">
          <label className="flex items-center gap-2 text-xs text-neutral-700">
            <input
              type="checkbox"
              checked={reviewedAll}
              onChange={(e) => setReviewedAll(e.target.checked)}
              disabled={hasSequence}
            />
            I've reviewed all {steps.length} email drafts above and they are
            ready to send.
          </label>

          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={() => setConfirming(true)}
              disabled={!canStart}
              className={cn(
                "rounded-md px-4 py-2 text-sm font-medium transition-colors",
                canStart
                  ? "bg-neutral-900 text-white hover:bg-neutral-700"
                  : "cursor-not-allowed bg-neutral-100 text-neutral-400",
              )}
            >
              Start {steps.length}-step sequence
            </button>
            {noEmail && (
              <span className="flex items-center gap-1 text-xs text-red-600">
                <AlertTriangle className="h-3.5 w-3.5" />
                Cannot start — contact has no email on file.
              </span>
            )}
            {hasSequence && (
              <span className="flex items-center gap-1 text-xs text-emerald-700">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Sequence already started for this contact (one-per-contact rule).
              </span>
            )}
            <div className="ml-auto">
              {!confirmingDelete ? (
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(true)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Delete contact
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-rose-900">
                    Delete {contact.full_name || "this contact"}?
                  </span>
                  <button
                    type="button"
                    onClick={() => remove.mutate()}
                    disabled={remove.isPending}
                    className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700 disabled:opacity-50"
                  >
                    {remove.isPending ? "Deleting…" : "Yes, delete"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmingDelete(false)}
                    disabled={remove.isPending}
                    className="rounded-md border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          </div>
          {remove.error && (
            <div className="mt-2 text-xs text-rose-700">
              Error: {(remove.error as Error).message}
            </div>
          )}
        </footer>
      </section>

      {confirming && (
        <ConfirmModal
          contact={contact}
          stepCount={steps.length}
          templateKey={templateKey}
          onCancel={() => setConfirming(false)}
          onConfirm={() => start.mutate()}
          isPending={start.isPending}
          error={start.error ? String((start.error as Error).message) : null}
        />
      )}
    </div>
  );
}


function SequenceStatePanel({
  contactId,
  sequence,
  sent,
  onMutated,
}: {
  contactId: string;
  sequence: import("@/lib/api").SequenceState;
  sent: import("@/lib/api").ContactDetail["sent_steps"];
  onMutated: () => void;
}) {
  const qc = useQueryClient();
  const isPaused = sequence.status === "paused";
  const isCompleted = sequence.status === "completed";

  const pause = useMutation({
    mutationFn: (reason: string) => pauseSequence(contactId, reason, sequence.template_key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      onMutated();
    },
  });
  const resume = useMutation({
    mutationFn: () => resumeSequence(contactId, sequence.template_key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      onMutated();
    },
  });

  const next = sequence.next_step_due_at
    ? new Date(sequence.next_step_due_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })
    : "—";

  const tone = isPaused
    ? { border: "border-amber-200", bg: "bg-amber-50", fg: "text-amber-700", body: "text-amber-900" }
    : { border: "border-emerald-200", bg: "bg-emerald-50", fg: "text-emerald-700", body: "text-emerald-900" };

  return (
    <section className={cn("rounded-xl border p-4", tone.border, tone.bg)}>
      <div className="flex items-center justify-between gap-3">
        <h3 className={cn("text-xs font-semibold uppercase tracking-wider", tone.fg)}>
          {isPaused ? "Sequence paused" : isCompleted ? "Sequence completed" : "Sequence in progress"}
        </h3>
        <span className={cn("text-[11px]", tone.fg)}>
          {sequence.status} · step {sequence.current_step}/{sequence.steps_total} · variant:{" "}
          {sequence.variant} · {sequence.template_key}
        </span>
        <div className="ml-auto flex gap-2">
          {!isCompleted && !isPaused && (
            <button
              onClick={() => {
                const reason = window.prompt(
                  "Pause reason (recorded on the row, e.g. 'replied: not interested'):",
                  "replied",
                );
                if (reason !== null) pause.mutate(reason);
              }}
              disabled={pause.isPending}
              className="rounded-md border border-amber-300 bg-white px-2.5 py-1 text-[11px] font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-60"
            >
              {pause.isPending ? "pausing…" : "Pause"}
            </button>
          )}
          {isPaused && (
            <button
              onClick={() => resume.mutate()}
              disabled={resume.isPending}
              className="rounded-md border border-emerald-300 bg-white px-2.5 py-1 text-[11px] font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-60"
            >
              {resume.isPending ? "resuming…" : "Resume"}
            </button>
          )}
        </div>
      </div>
      <div className={cn("mt-2 grid gap-1 text-xs", tone.body)}>
        <div>
          <span className={tone.fg}>
            {isPaused ? "would-be next due:" : "next due:"}
          </span>{" "}
          {next}
        </div>
        {sequence.paused_reason && (
          <div className="text-amber-800">
            <span className="font-semibold">paused:</span>{" "}
            {sequence.paused_reason}
          </div>
        )}
      </div>
      {sent.length > 0 && (
        <div className="mt-3">
          <div className={cn("text-[11px] font-semibold uppercase tracking-wider", tone.fg)}>
            Sent so far
          </div>
          <ul className="mt-1 space-y-1 text-xs">
            {sent.map((s) => (
              <li key={s.id} className={tone.body}>
                <span className={tone.fg}>{s.message_type}</span>:{" "}
                {s.subject}{" "}
                <span className="text-neutral-500">
                  ({s.sent_at?.slice(0, 19)} · {s.status})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}


function ConfirmModal({
  contact,
  stepCount,
  templateKey,
  onCancel,
  onConfirm,
  isPending,
  error,
}: {
  contact: FirmContact;
  stepCount: number;
  templateKey: string;
  onCancel: () => void;
  onConfirm: () => void;
  isPending: boolean;
  error: string | null;
}) {
  const cadenceDescription =
    "Each step is composed by the lead email composer skill at send time. Steps schedule for days 0, 3, 7, and 14.";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-base font-semibold text-neutral-900">
          Start sequence for {contact.full_name}?
        </h3>
        <div className="mt-3 space-y-2 text-sm text-neutral-700">
          <div>
            <span className="text-neutral-500">to:</span>{" "}
            <span className="font-mono">{contact.email}</span>
          </div>
          <div>
            <span className="text-neutral-500">cadence:</span>{" "}
            {cadenceDescription}
          </div>
          <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Sends are gated by <code>ALLOW_SEQUENCE_SEND=true</code>. If the
            gate is closed, the row stays active and the scheduler waits.
          </div>
        </div>
        {error && (
          <div className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={isPending}
            className="rounded-md px-3 py-1.5 text-sm text-neutral-600 hover:bg-neutral-100"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isPending}
            className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-60"
          >
            {isPending ? "starting…" : "Confirm and start"}
          </button>
        </div>
      </div>
    </div>
  );
}
