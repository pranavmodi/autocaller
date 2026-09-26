"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2 } from "lucide-react";
import { createEngagementCampaignLink, searchEngagementCampaignContacts } from "@/lib/api";
import { listPifFirms } from "@/lib/emailtag";

const field = "h-10 w-full min-w-0 rounded-md border border-neutral-300 bg-white px-3 text-sm outline-none focus:border-cyan-600";

export function CampaignTrackingLinkForm({ campaignId, destination }: { campaignId: string; destination: string }) {
  const client = useQueryClient();
  const [channel, setChannel] = useState<"email" | "linkedin" | "public">("linkedin");
  const [mode, setMode] = useState<"existing" | "new">("new");
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [firmSearch, setFirmSearch] = useState("");
  const [firmId, setFirmId] = useState("");
  const [contactSearch, setContactSearch] = useState("");
  const [contactId, setContactId] = useState("");
  const [sent, setSent] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const contacts = useQuery({
    queryKey: ["engagement-campaign-contacts", contactSearch],
    queryFn: () => searchEngagementCampaignContacts(contactSearch, 30),
    enabled: channel !== "public" && mode === "existing",
  });
  const firms = useQuery({
    queryKey: ["campaign-recipient-firms", firmSearch],
    queryFn: () => listPifFirms({ search: firmSearch, page_size: 25 }),
    enabled: channel !== "public" && mode === "new" && firmSearch.trim().length > 1,
  });
  const create = useMutation({
    mutationFn: () => createEngagementCampaignLink(campaignId, {
      channel, destination_url: url.trim(), label: label.trim(),
      contact_id: channel !== "public" && mode === "existing" ? contactId : "",
      ...(channel !== "public" && mode === "new" ? {
        recipient_name: name.trim(), recipient_email: email.trim(), recipient_firm_id: firmId,
      } : {}),
      mark_sent: channel !== "public" && sent,
    }),
    onSuccess: () => {
      setCopied(false);
      setCopyFailed(false);
      client.invalidateQueries({ queryKey: ["engagement-campaign", campaignId] });
      client.invalidateQueries({ queryKey: ["engagement-campaigns"] });
      client.invalidateQueries({ queryKey: ["engagement-campaign-contacts"] });
    },
  });
  const error = create.error instanceof Error ? create.error.message : "";
  const errors: Record<string, string> = {
    recipient_email_invalid: "Enter a valid email address.",
    multiple_contacts_match_email_select_existing: "Several contacts share this email. Choose Existing contact to select the right person.",
    recipient_firm_mismatch_select_existing: "This email belongs to a contact with a different firm. Choose Existing contact to review it.",
    recipient_firm_not_found: "This firm is no longer available. Search again.",
  };
  return (
    <details className="border-y border-cyan-200 py-3">
      <summary className="cursor-pointer text-sm font-semibold text-cyan-800">Create a tracking link</summary>
      <form className="mt-4 space-y-4" onChange={() => { if (!create.isPending) { create.reset(); setCopied(false); setCopyFailed(false); } }} onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
        <fieldset disabled={create.isPending} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
            <label className="space-y-1 text-xs font-medium text-neutral-700">Channel<select aria-label="Channel" className={field} value={channel} onChange={(event) => { setChannel(event.target.value as typeof channel); create.reset(); }}><option value="linkedin">LinkedIn</option><option value="email">Email</option><option value="public">Public post</option></select></label>
            <label className="space-y-1 text-xs font-medium text-neutral-700">Destination URL<input type="url" aria-label="Destination URL" required={!destination} className={field} placeholder={destination || "https://getpossibleminds.com/..."} value={url} onChange={(event) => setUrl(event.target.value)} /></label>
          </div>
          {channel !== "public" && <>
            <div role="group" aria-label="Recipient source" className="inline-flex max-w-full gap-1 rounded-md bg-neutral-100 p-1">
              {([ ["new", "New recipient"], ["existing", "Existing contact"] ] as const).map(([value, title]) => <button key={value} type="button" aria-pressed={mode === value} onClick={() => { setMode(value); create.reset(); }} className={`rounded px-3 py-2 text-xs font-medium ${mode === value ? "bg-white text-cyan-800 shadow-sm" : "text-neutral-600"}`}>{title}</button>)}
            </div>
            {mode === "new" ? <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs font-medium text-neutral-700">Name<input aria-label="Recipient name" required maxLength={255} className={field} value={name} onChange={(event) => setName(event.target.value)} /></label>
              <label className="space-y-1 text-xs font-medium text-neutral-700">Email (optional)<input aria-label="Recipient email" type="email" maxLength={320} className={field} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
              <label className="space-y-1 text-xs font-medium text-neutral-700">Firm (optional)<input aria-label="Search recipient firm" placeholder="Search firms" className={field} value={firmSearch} onChange={(event) => { setFirmSearch(event.target.value); setFirmId(""); }} /></label>
              <label className="space-y-1 text-xs font-medium text-neutral-700">Firm match<select aria-label="Recipient firm" className={field} value={firmId} onChange={(event) => setFirmId(event.target.value)}><option value="">No firm selected</option>{(firms.data?.items ?? []).map((firm) => <option key={firm.id} value={firm.id}>{firm.firm_name}</option>)}</select></label>
              {firms.isError && <p role="alert" className="text-xs text-red-700">Firm search unavailable. Try again or leave the firm unassigned.</p>}
            </div> : <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs font-medium text-neutral-700">Search contacts<input aria-label="Search contacts" className={field} value={contactSearch} onChange={(event) => { setContactSearch(event.target.value); setContactId(""); }} /></label>
              <label className="space-y-1 text-xs font-medium text-neutral-700">Contact<select aria-label="Contact" required className={field} value={contactId} onChange={(event) => setContactId(event.target.value)}><option value="">Select contact</option>{(contacts.data?.contacts ?? []).map((contact) => <option key={contact.id} value={contact.id}>{contact.name} · {contact.firm_name || contact.email}</option>)}</select></label>
              {contacts.isError && <p role="alert" className="text-xs text-red-700">Could not load contacts. Try searching again.</p>}
            </div>}
          </>}
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-0 flex-1 space-y-1 text-xs font-medium text-neutral-700">Label (optional)<input aria-label="Link label" maxLength={255} className={field} value={label} onChange={(event) => setLabel(event.target.value)} /></label>
            {channel !== "public" && <label className="flex h-10 items-center gap-2 text-xs text-neutral-600"><input type="checkbox" checked={sent} onChange={(event) => setSent(event.target.checked)} />Mark sent now</label>}
            <button type="submit" disabled={create.isPending || (channel !== "public" && (mode === "new" ? !name.trim() : !contactId))} className="inline-flex h-10 items-center gap-2 rounded-md bg-cyan-700 px-4 text-sm font-medium text-white hover:bg-cyan-800 disabled:opacity-50"><Link2 className="h-4 w-4" />{create.isPending ? "Creating..." : "Create link"}</button>
          </div>
        </fieldset>
        {create.isError && <p role="alert" className="text-sm text-red-700">{Object.entries(errors).find(([key]) => error.includes(key))?.[1] || "Could not create link. Check the recipient and Possible Minds destination URL."}</p>}
        {create.data && <div role="status" className="flex min-w-0 items-center gap-2 border-t border-neutral-200 pt-3">
          <input readOnly aria-label="Created tracking URL" value={create.data.tracking_url} className={`${field} flex-1 text-cyan-800`} onFocus={(event) => event.target.select()} />
          <button type="button" title={copied ? "Copied" : "Copy tracking URL"} aria-label="Copy tracking URL" className="h-10 w-10 shrink-0 rounded-md border border-neutral-300 p-2" onClick={async () => { try { await navigator.clipboard.writeText(create.data.tracking_url); setCopied(true); setCopyFailed(false); } catch { setCopyFailed(true); } }}>{copied ? <Check className="h-5 w-5 text-emerald-700" /> : <Copy className="h-5 w-5" />}</button>
        </div>}
        {copyFailed && <p role="alert" className="text-xs text-red-700">Clipboard unavailable. Select the URL to copy it.</p>}
      </form>
    </details>
  );
}
