"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  CalendarDays,
  CheckCircle2,
  Copy,
  Eye,
  ExternalLink,
  Globe2,
  Link2,
  Linkedin,
  Loader2,
  Mail,
  MessageSquareReply,
  MousePointerClick,
  Plus,
  RefreshCw,
  Search,
  Send,
  Users,
} from "lucide-react";
import {
  createEngagementCampaign,
  createEngagementCampaignLink,
  getEngagementAnalytics,
  getEngagementCampaign,
  listEngagementCampaigns,
  markEngagementCampaignLinkSent,
  searchEngagementCampaignContacts,
  type EngagementActivity,
  type EngagementCampaign,
  type EngagementCampaignActivity,
  type EngagementCampaignLink,
  type EngagementRecipient,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const WINDOWS = [
  { label: "24h", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: 0 },
];

const DEFAULT_WORKFLOWS = [{ key: "all", label: "All workflows" }];
const DEFAULT_CHANNELS = [
  { key: "all", label: "All channels" },
  { key: "email", label: "Email" },
  { key: "linkedin", label: "LinkedIn" },
];

function formatDateTime(value: string | null) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function Metric({
  label,
  value,
  note,
  icon: Icon,
}: {
  label: string;
  value: number;
  note?: string;
  icon: typeof Users;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-3">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase text-neutral-500">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-neutral-950">{value}</div>
      <div className="mt-1 min-h-4 text-[11px] text-neutral-400">{note}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: EngagementRecipient["status"] }) {
  return (
    <span
      className={cn(
        "inline-flex whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-semibold",
        status === "Replied" && "bg-emerald-100 text-emerald-800",
        status === "Engaged" && "bg-cyan-100 text-cyan-800",
        status === "Visited" && "bg-blue-100 text-blue-800",
        status === "Unconfirmed click" && "bg-amber-100 text-amber-800",
        status === "Delivered" && "bg-violet-100 text-violet-800",
        status === "Sent" && "bg-neutral-200 text-neutral-700",
        status === "Tracked" && "bg-neutral-100 text-neutral-500",
      )}
    >
      {status}
    </span>
  );
}

function QualityBadge({ quality }: { quality: EngagementActivity["quality"] }) {
  const label = {
    human: "Human",
    scanner: "Scanner",
    suspect: "Unconfirmed",
    system: "System",
  }[quality];
  return (
    <span
      className={cn(
        "inline-flex whitespace-nowrap rounded-md px-2 py-1 text-[10px] font-semibold uppercase",
        quality === "human" && "bg-emerald-100 text-emerald-800",
        quality === "scanner" && "bg-amber-100 text-amber-800",
        quality === "suspect" && "bg-neutral-100 text-neutral-600",
        quality === "system" && "bg-blue-50 text-blue-700",
      )}
    >
      {label}
    </span>
  );
}

function ChannelLabel({ channel }: { channel: "Email" | "LinkedIn" }) {
  const Icon = channel === "LinkedIn" ? Linkedin : Mail;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-neutral-700">
      <Icon className="h-3.5 w-3.5" />
      {channel}
    </span>
  );
}

function RecipientRow({ recipient }: { recipient: EngagementRecipient }) {
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="px-3 py-3">
        <div className="text-sm font-semibold text-neutral-950">{recipient.contact_name}</div>
        <div className="mt-0.5 text-xs text-neutral-500">{recipient.contact_email || "-"}</div>
        <div className="mt-0.5 text-xs text-neutral-400">
          {[recipient.title, recipient.firm_name].filter(Boolean).join(" · ")}
        </div>
      </td>
      <td className="px-3 py-3 text-xs text-neutral-700">{recipient.workflow_labels.join(", ")}</td>
      <td className="px-3 py-3">
        <div className="flex flex-col items-start gap-1">
          {recipient.channel_labels.map((label) => (
            <ChannelLabel key={label} channel={label as "Email" | "LinkedIn"} />
          ))}
        </div>
      </td>
      <td className="px-3 py-3"><StatusBadge status={recipient.status} /></td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">
        {recipient.sent}<span className="text-neutral-300"> / </span>{recipient.delivered}
        {recipient.delivery_failures ? (
          <div className="mt-0.5 text-[10px] text-red-600">{recipient.delivery_failures} failed</div>
        ) : null}
      </td>
      <td className="px-3 py-3 text-right text-sm font-semibold text-neutral-900">
        {recipient.raw_clicks}
        {recipient.scanner_or_suspect_clicks ? (
          <div className="mt-0.5 text-[10px] font-normal text-amber-700">
            {recipient.scanner_or_suspect_clicks} unconfirmed
          </div>
        ) : null}
      </td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{recipient.confirmed_visits}</td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{recipient.meaningful_actions}</td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{recipient.replies}</td>
      <td className="whitespace-nowrap px-3 py-3 text-xs text-neutral-500">
        {formatDateTime(recipient.last_activity_at)}
      </td>
    </tr>
  );
}

function ActivityRow({ activity }: { activity: EngagementActivity }) {
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="whitespace-nowrap px-3 py-3 text-xs text-neutral-500">
        {formatDateTime(activity.occurred_at)}
      </td>
      <td className="px-3 py-3">
        <div className="text-sm font-medium text-neutral-950">{activity.contact_name}</div>
        <div className="mt-0.5 text-xs text-neutral-400">{activity.firm_name}</div>
      </td>
      <td className="px-3 py-3 text-xs text-neutral-700">{activity.workflow_label}</td>
      <td className="px-3 py-3"><ChannelLabel channel={activity.channel_label} /></td>
      <td className="px-3 py-3">
        <div className="text-sm font-medium text-neutral-900">{activity.label}</div>
        <div className="mt-0.5 max-w-xl break-words text-xs text-neutral-500">{activity.detail}</div>
      </td>
      <td className="px-3 py-3"><QualityBadge quality={activity.quality} /></td>
    </tr>
  );
}

function CampaignChannel({ channel }: { channel: "email" | "linkedin" | "public" }) {
  const Icon = channel === "linkedin" ? Linkedin : channel === "public" ? Globe2 : Mail;
  const label = channel === "linkedin" ? "LinkedIn" : channel === "public" ? "Public" : "Email";
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium capitalize text-neutral-700">
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

function CampaignActivityRow({ activity }: { activity: EngagementCampaignActivity }) {
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="whitespace-nowrap px-3 py-3 text-xs text-neutral-500">{formatDateTime(activity.occurred_at)}</td>
      <td className="px-3 py-3">
        <div className="text-sm font-medium text-neutral-950">{activity.contact_name}</div>
        <div className="mt-0.5 text-xs text-neutral-400">{activity.firm_name || activity.contact_email}</div>
      </td>
      <td className="px-3 py-3"><CampaignChannel channel={activity.channel} /></td>
      <td className="px-3 py-3">
        <div className="text-sm font-medium text-neutral-900">{activity.label}</div>
        <div className="mt-0.5 max-w-xl break-words text-xs text-neutral-500">{activity.detail}</div>
        {activity.page ? <div className="mt-1 text-[10px] text-neutral-400">/{activity.page}</div> : null}
      </td>
      <td className="px-3 py-3"><QualityBadge quality={activity.quality} /></td>
    </tr>
  );
}

function CampaignLinkRow({
  link,
  onMarkSent,
  marking,
}: {
  link: EngagementCampaignLink;
  onMarkSent: (code: string) => void;
  marking: boolean;
}) {
  const copy = async () => navigator.clipboard.writeText(link.tracking_url);
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="px-3 py-3">
        <div className="text-sm font-medium text-neutral-950">{link.contact_name}</div>
        <div className="mt-0.5 text-xs text-neutral-400">{link.firm_name || link.contact_email || link.label || "Campaign-level link"}</div>
      </td>
      <td className="px-3 py-3"><CampaignChannel channel={link.channel} /></td>
      <td className="px-3 py-3">
        <div className="flex items-center gap-1">
          <button type="button" onClick={copy} title="Copy tracking URL" className="rounded-md p-1.5 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900">
            <Copy className="h-4 w-4" />
          </button>
          <a href={link.tracking_url} target="_blank" rel="noreferrer" title="Open tracking URL" className="rounded-md p-1.5 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900">
            <ExternalLink className="h-4 w-4" />
          </a>
          <span className="max-w-72 truncate font-mono text-[11px] text-neutral-500">{link.tracking_url}</span>
        </div>
        <div className="mt-1 max-w-80 truncate text-[10px] text-neutral-400">{link.destination_url}</div>
      </td>
      <td className="px-3 py-3 text-xs">
        {link.sent_at ? (
          <span className="text-emerald-700">Sent {formatDateTime(link.sent_at)}</span>
        ) : link.channel === "public" ? (
          <span className="text-neutral-400">Public link</span>
        ) : (
          <button type="button" disabled={marking} onClick={() => onMarkSent(link.code)} className="rounded-md border border-neutral-200 px-2 py-1 font-medium text-neutral-600 hover:bg-neutral-50 disabled:opacity-50">
            Mark sent
          </button>
        )}
      </td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{link.raw_clicks}</td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{link.confirmed_visits}</td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{link.deepest_scroll ? `${link.deepest_scroll}%` : "-"}</td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{link.meaningful_actions}</td>
    </tr>
  );
}

function CampaignWorkspace() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [campaignDate, setCampaignDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [destination, setDestination] = useState("");
  const [workflow, setWorkflow] = useState("content");
  const [linkChannel, setLinkChannel] = useState<"email" | "linkedin" | "public">("email");
  const [linkDestination, setLinkDestination] = useState("");
  const [linkLabel, setLinkLabel] = useState("");
  const [contactSearch, setContactSearch] = useState("");
  const [contactId, setContactId] = useState("");
  const [markSentOnCreate, setMarkSentOnCreate] = useState(false);

  const campaigns = useQuery({
    queryKey: ["engagement-campaigns", search],
    queryFn: () => listEngagementCampaigns({ search, limit: 100 }),
  });
  const selected = useQuery({
    queryKey: ["engagement-campaign", selectedId],
    queryFn: () => getEngagementCampaign(selectedId),
    enabled: Boolean(selectedId),
    refetchInterval: selectedId ? 30_000 : false,
  });
  const contacts = useQuery({
    queryKey: ["engagement-campaign-contacts", contactSearch],
    queryFn: () => searchEngagementCampaignContacts(contactSearch, 30),
    enabled: linkChannel !== "public",
  });

  const createCampaign = useMutation({
    mutationFn: () => createEngagementCampaign({
      name: name.trim(),
      campaign_date: campaignDate,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      workflow: workflow.trim() || "content",
      destination_url: destination.trim(),
    }),
    onSuccess: (campaign: EngagementCampaign) => {
      queryClient.invalidateQueries({ queryKey: ["engagement-campaigns"] });
      setSelectedId(campaign.id);
      setName("");
      setDestination("");
      setShowCreate(false);
    },
  });
  const createLink = useMutation({
    mutationFn: () => createEngagementCampaignLink(selectedId, {
      channel: linkChannel,
      destination_url: linkDestination.trim(),
      contact_id: linkChannel === "public" ? "" : contactId,
      label: linkLabel.trim(),
      mark_sent: linkChannel !== "public" && markSentOnCreate,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["engagement-campaign", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["engagement-campaigns"] });
      setContactId("");
      setContactSearch("");
      setLinkLabel("");
    },
  });
  const markSent = useMutation({
    mutationFn: markEngagementCampaignLinkSent,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["engagement-campaign", selectedId] }),
  });

  const campaignRows = campaigns.data?.campaigns ?? [];
  const data = selected.data;
  const summary = data?.summary;

  return (
    <section className="border-y border-neutral-200 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <CalendarDays className="h-4 w-4 text-neutral-600" />
          <h2 className="text-sm font-semibold text-neutral-950">Daily campaigns</h2>
        </div>
        <div className="relative min-w-56 flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-neutral-400" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search campaigns" className="h-9 w-full rounded-md border border-neutral-200 bg-white pl-8 pr-3 text-sm outline-none focus:border-neutral-400" />
        </div>
        <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)} className="h-9 min-w-64 rounded-md border border-neutral-200 bg-white px-3 text-sm text-neutral-700 outline-none focus:border-neutral-400">
          <option value="">Select a campaign</option>
          {campaignRows.map((campaign) => (
            <option key={campaign.id} value={campaign.id}>{campaign.campaign_date} · {campaign.name}</option>
          ))}
        </select>
        <button type="button" onClick={() => setShowCreate((value) => !value)} className="inline-flex h-9 items-center gap-2 rounded-md bg-neutral-900 px-3 text-xs font-medium text-white hover:bg-neutral-800">
          <Plus className="h-3.5 w-3.5" /> New campaign
        </button>
      </div>

      {showCreate ? (
        <form onSubmit={(event) => { event.preventDefault(); createCampaign.mutate(); }} className="mt-4 grid gap-3 border-t border-neutral-100 pt-4 md:grid-cols-2 xl:grid-cols-[1.3fr_170px_1fr_2fr_auto]">
          <input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Campaign name" className="h-9 rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-400" />
          <input required type="date" value={campaignDate} onChange={(event) => setCampaignDate(event.target.value)} className="h-9 rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-400" />
          <input value={workflow} onChange={(event) => setWorkflow(event.target.value)} placeholder="Workflow" className="h-9 rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-400" />
          <input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="Default https://getpossibleminds.com/... URL" className="h-9 rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-400" />
          <button type="submit" disabled={createCampaign.isPending} className="h-9 rounded-md bg-cyan-700 px-4 text-xs font-medium text-white hover:bg-cyan-800 disabled:opacity-50">
            {createCampaign.isPending ? "Creating..." : "Create"}
          </button>
          {createCampaign.isError ? <div className="text-xs text-red-600 md:col-span-full">Could not create campaign. Check the date and Possible Minds URL.</div> : null}
        </form>
      ) : null}

      {selectedId && selected.isLoading ? <div className="mt-4 flex items-center gap-2 text-sm text-neutral-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading campaign...</div> : null}
      {selected.isError ? <div className="mt-4 text-sm text-red-600">Could not load this campaign.</div> : null}

      {data ? (
        <div className="mt-5 space-y-5 border-t border-neutral-100 pt-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-base font-semibold text-neutral-950">{data.campaign.name}</div>
              <div className="mt-1 text-xs text-neutral-500">{data.campaign.campaign_date} · {data.campaign.workflow} · {data.campaign.status}</div>
            </div>
            {data.campaign.destination_url ? <a href={data.campaign.destination_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-xs font-medium text-cyan-700 hover:text-cyan-900">Open destination <ExternalLink className="h-3.5 w-3.5" /></a> : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
            <Metric label="Tracked people" value={summary?.tracked_people ?? 0} icon={Users} />
            <Metric label="Links" value={summary?.tracked_links ?? 0} icon={Link2} />
            <Metric label="Sent" value={summary?.sent ?? 0} icon={Send} />
            <Metric label="Raw clicks" value={summary?.raw_clicks ?? 0} note={summary?.scanner_or_suspect_clicks ? `${summary.scanner_or_suspect_clicks} unconfirmed` : undefined} icon={MousePointerClick} />
            <Metric label="Human visits" value={summary?.confirmed_visits ?? 0} note={summary?.anonymous_human_sessions ? `${summary.anonymous_human_sessions} anonymous` : undefined} icon={Eye} />
            <Metric label="Actions" value={summary?.meaningful_actions ?? 0} icon={Activity} />
            <Metric label="Engaged people" value={summary?.engaged_people ?? 0} icon={CheckCircle2} />
          </div>

          <div className="overflow-x-auto border-y border-neutral-100">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase text-neutral-500"><tr><th className="px-3 py-2">Channel</th><th className="px-3 py-2 text-right">Links</th><th className="px-3 py-2 text-right">People</th><th className="px-3 py-2 text-right">Sent</th><th className="px-3 py-2 text-right">Clicks</th><th className="px-3 py-2 text-right">Visits</th><th className="px-3 py-2 text-right">Actions</th><th className="px-3 py-2 text-right">Engaged</th></tr></thead>
              <tbody>{data.channels.map((channel) => <tr key={channel.channel} className="border-t border-neutral-100"><td className="px-3 py-3"><CampaignChannel channel={channel.channel} /></td><td className="px-3 py-3 text-right text-sm">{channel.tracked_links}</td><td className="px-3 py-3 text-right text-sm">{channel.tracked_people}</td><td className="px-3 py-3 text-right text-sm">{channel.sent}</td><td className="px-3 py-3 text-right text-sm">{channel.raw_clicks}</td><td className="px-3 py-3 text-right text-sm">{channel.confirmed_visits}</td><td className="px-3 py-3 text-right text-sm">{channel.meaningful_actions}</td><td className="px-3 py-3 text-right text-sm">{channel.engaged_people}</td></tr>)}</tbody>
            </table>
          </div>

          <form onSubmit={(event) => { event.preventDefault(); createLink.mutate(); }} className="grid gap-3 border-y border-neutral-100 py-4 md:grid-cols-2 xl:grid-cols-[150px_1.4fr_1.2fr_1fr_auto]">
            <select value={linkChannel} onChange={(event) => { setLinkChannel(event.target.value as "email" | "linkedin" | "public"); setContactId(""); }} className="h-9 rounded-md border border-neutral-200 bg-white px-3 text-sm outline-none focus:border-neutral-400">
              <option value="email">Email</option><option value="linkedin">LinkedIn</option><option value="public">Public post</option>
            </select>
            <input value={linkDestination} onChange={(event) => setLinkDestination(event.target.value)} placeholder={data.campaign.destination_url || "https://getpossibleminds.com/..."} className="h-9 rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-400" />
            {linkChannel === "public" ? (
              <input value={linkLabel} onChange={(event) => setLinkLabel(event.target.value)} placeholder="Link label" className="h-9 rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-400" />
            ) : (
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <input value={contactSearch} onChange={(event) => { setContactSearch(event.target.value); setContactId(""); }} placeholder="Search contact or firm" className="h-9 min-w-0 rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-400" />
                <select required value={contactId} onChange={(event) => setContactId(event.target.value)} className="h-9 max-w-52 rounded-md border border-neutral-200 bg-white px-2 text-xs outline-none focus:border-neutral-400">
                  <option value="">Select</option>
                  {(contacts.data?.contacts ?? []).map((contact) => <option key={contact.id} value={contact.id}>{contact.name} · {contact.firm_name || contact.email}</option>)}
                </select>
              </div>
            )}
            <label className="flex h-9 items-center gap-2 text-xs text-neutral-600"><input type="checkbox" checked={markSentOnCreate} disabled={linkChannel === "public"} onChange={(event) => setMarkSentOnCreate(event.target.checked)} /> Mark sent now</label>
            <button type="submit" disabled={createLink.isPending || (linkChannel !== "public" && !contactId)} className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-blue-700 px-4 text-xs font-medium text-white hover:bg-blue-800 disabled:opacity-50"><Link2 className="h-3.5 w-3.5" />{createLink.isPending ? "Creating..." : "Create link"}</button>
            {createLink.isSuccess ? <div className="flex items-center gap-2 text-xs text-emerald-700 md:col-span-full"><CheckCircle2 className="h-3.5 w-3.5" /> Tracking URL created.</div> : null}
            {createLink.isError ? <div className="text-xs text-red-600 md:col-span-full">Could not create link. Use a getpossibleminds.com destination and a valid contact.</div> : null}
          </form>

          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase text-neutral-500"><tr><th className="px-3 py-2">Contact</th><th className="px-3 py-2">Channel</th><th className="px-3 py-2">Tracking URL</th><th className="px-3 py-2">Status</th><th className="px-3 py-2 text-right">Clicks</th><th className="px-3 py-2 text-right">Visits</th><th className="px-3 py-2 text-right">Depth</th><th className="px-3 py-2 text-right">Actions</th></tr></thead>
              <tbody>{data.links.length ? data.links.map((link) => <CampaignLinkRow key={link.code} link={link} onMarkSent={(code) => markSent.mutate(code)} marking={markSent.isPending} />) : <tr><td colSpan={8} className="px-3 py-8 text-sm text-neutral-500">No tracking links yet.</td></tr>}</tbody>
            </table>
          </div>

          {data.activities.length ? <div className="overflow-x-auto border-t border-neutral-100 pt-4"><div className="mb-3 text-sm font-semibold text-neutral-950">Campaign activity</div><table className="min-w-full text-left"><thead className="bg-neutral-50 text-[11px] uppercase text-neutral-500"><tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Contact</th><th className="px-3 py-2">Channel</th><th className="px-3 py-2">Event</th><th className="px-3 py-2">Signal</th></tr></thead><tbody>{data.activities.map((activity) => <CampaignActivityRow key={activity.id} activity={activity} />)}</tbody></table></div> : null}
        </div>
      ) : null}
    </section>
  );
}

export default function ClickAnalyticsPage() {
  const [sinceDays, setSinceDays] = useState(1);
  const [workflow, setWorkflow] = useState("all");
  const [channel, setChannel] = useState("all");
  const analytics = useQuery({
    queryKey: ["engagement-analytics", sinceDays, workflow, channel],
    queryFn: () => getEngagementAnalytics({ sinceDays, workflow, channel, limit: 250 }),
    refetchInterval: 30_000,
  });

  const data = analytics.data;
  const summary = data?.summary;
  const workflows = data?.filters.workflows ?? DEFAULT_WORKFLOWS;
  const channels = data?.filters.channels ?? DEFAULT_CHANNELS;

  return (
    <div className="mx-auto max-w-[1600px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="rounded-lg bg-neutral-900 p-2 text-white">
          <Activity className="h-4 w-4" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-neutral-950">Engagement</h1>
          <p className="mt-0.5 text-sm text-neutral-500">Recipient activity across outreach workflows</p>
        </div>
        <button
          type="button"
          onClick={() => analytics.refetch()}
          disabled={analytics.isFetching}
          className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          {analytics.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </button>
      </div>

      <CampaignWorkspace />

      <div className="flex flex-wrap items-center gap-3 border-y border-neutral-200 py-3">
        <div className="flex flex-wrap gap-1">
          {WINDOWS.map((window) => (
            <button
              key={window.label}
              type="button"
              onClick={() => setSinceDays(window.days)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                sinceDays === window.days
                  ? "bg-neutral-900 text-white"
                  : "border border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-100",
              )}
            >
              {window.label}
            </button>
          ))}
        </div>
        <div className="h-5 w-px bg-neutral-200" />
        <div className="flex max-w-full flex-wrap gap-1">
          {workflows.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setWorkflow(option.key)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                workflow === option.key
                  ? "bg-cyan-700 text-white"
                  : "border border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-100",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="h-5 w-px bg-neutral-200" />
        <div className="flex flex-wrap gap-1">
          {channels.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setChannel(option.key)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                channel === option.key
                  ? "bg-blue-700 text-white"
                  : "border border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-100",
              )}
            >
              {option.key === "email" ? <Mail className="h-3.5 w-3.5" /> : null}
              {option.key === "linkedin" ? <Linkedin className="h-3.5 w-3.5" /> : null}
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        <Metric label="Tracked people" value={summary?.tracked_recipients ?? 0} icon={Users} />
        <Metric label="Sent" value={summary?.sent ?? 0} icon={Send} />
        <Metric
          label="Delivered"
          value={summary?.delivered ?? 0}
          note={summary?.delivery_failures ? `${summary.delivery_failures} failed or delayed` : undefined}
          icon={CheckCircle2}
        />
        <Metric
          label="Raw clicks"
          value={summary?.raw_clicks ?? 0}
          note={summary?.scanner_or_suspect_clicks ? `${summary.scanner_or_suspect_clicks} scanner or unconfirmed` : undefined}
          icon={MousePointerClick}
        />
        <Metric label="Confirmed visits" value={summary?.confirmed_visits ?? 0} icon={Eye} />
        <Metric label="Actions" value={summary?.meaningful_actions ?? 0} icon={Activity} />
        <Metric label="Replies" value={summary?.replies ?? 0} icon={MessageSquareReply} />
      </div>

      <section className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">People</h2>
        </div>
        {analytics.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading engagement...
          </div>
        ) : analytics.isError ? (
          <div className="px-4 py-8 text-sm text-red-600">Could not load engagement analytics.</div>
        ) : !data?.recipients.length ? (
          <div className="px-4 py-8 text-sm text-neutral-500">No tracked recipients in this view.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase text-neutral-500">
                <tr>
                  <th className="px-3 py-2 font-semibold">Contact</th>
                  <th className="px-3 py-2 font-semibold">Workflow</th>
                  <th className="px-3 py-2 font-semibold">Channel</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 text-right font-semibold">Sent / delivered</th>
                  <th className="px-3 py-2 text-right font-semibold">Raw clicks</th>
                  <th className="px-3 py-2 text-right font-semibold">Visits</th>
                  <th className="px-3 py-2 text-right font-semibold">Actions</th>
                  <th className="px-3 py-2 text-right font-semibold">Replies</th>
                  <th className="px-3 py-2 font-semibold">Last activity</th>
                </tr>
              </thead>
              <tbody>{data.recipients.map((recipient) => <RecipientRow key={recipient.contact_id} recipient={recipient} />)}</tbody>
            </table>
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Activity</h2>
        </div>
        {!data?.activities.length ? (
          <div className="px-4 py-8 text-sm text-neutral-500">No activity in this view.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase text-neutral-500">
                <tr>
                  <th className="px-3 py-2 font-semibold">When</th>
                  <th className="px-3 py-2 font-semibold">Contact</th>
                  <th className="px-3 py-2 font-semibold">Workflow</th>
                  <th className="px-3 py-2 font-semibold">Channel</th>
                  <th className="px-3 py-2 font-semibold">Event</th>
                  <th className="px-3 py-2 font-semibold">Signal</th>
                </tr>
              </thead>
              <tbody>{data.activities.map((activity) => <ActivityRow key={activity.id} activity={activity} />)}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
