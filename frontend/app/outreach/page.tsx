"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowLeft,
  Mail,
  Send,
  SkipForward,
  RefreshCw,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Eye,
  PlusCircle,
  Users,
  Building2,
  ChevronRight,
} from "lucide-react";
import {
  addOutreachAudience,
  composeOutreachSend,
  createOutreachCampaign,
  getNextOutreachSend,
  getOutreachCampaign,
  listFirmsWithContacts,
  listContactsForFirm,
  listOutreachBlogPosts,
  listOutreachCampaigns,
  listOutreachEvents,
  updateOutreachCampaignBcc,
  listOutreachSends,
  previewOutreachSend,
  sendOutreachSend,
  skipOutreachSend,
  type FirmWithContacts,
  type OutreachCampaign,
  type OutreachCampaignDetail,
  type OutreachSend,
} from "@/lib/api";

// ============================================================================
// Outreach — LLM-composed blog-post emails, step-through one-at-a-time UI.
// ============================================================================

export default function OutreachPage() {
  const [campaignId, setCampaignId] = useState<number | null>(null);

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-8">
      <div className="mb-6 flex items-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <span className="text-neutral-300">/</span>
        <h1 className="text-lg font-semibold text-neutral-900">
          Blog-post outreach
        </h1>
        <span className="text-xs text-neutral-400">
          LLM composes each email — preview, edit, send one at a time
        </span>
      </div>

      <div className="grid grid-cols-12 gap-4">
        <aside className="col-span-12 space-y-3 lg:col-span-4">
          <CampaignsList
            selectedId={campaignId}
            onSelect={setCampaignId}
          />
          <NewCampaignPanel onCreated={(c) => setCampaignId(c.id)} />
        </aside>
        <main className="col-span-12 lg:col-span-8">
          {campaignId ? (
            <CampaignDetail campaignId={campaignId} />
          ) : (
            <div className="rounded-xl border border-dashed border-neutral-200 bg-white p-10 text-center text-sm text-neutral-500">
              Pick a campaign on the left, or create one to start.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

// ---- Campaigns list -------------------------------------------------------

function CampaignsList({
  selectedId,
  onSelect,
}: {
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const q = useQuery({
    queryKey: ["outreach-campaigns"],
    queryFn: () => listOutreachCampaigns(),
  });

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Campaigns
        </h2>
        {q.isFetching && (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-neutral-400" />
        )}
      </div>
      <div className="max-h-[360px] overflow-y-auto">
        {q.data && q.data.length === 0 && (
          <p className="px-4 py-6 text-center text-xs text-neutral-400">
            No campaigns yet.
          </p>
        )}
        {q.data?.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={
              "block w-full border-b border-neutral-50 px-4 py-2.5 text-left text-xs hover:bg-neutral-50 " +
              (selectedId === c.id ? "bg-emerald-50/40" : "")
            }
          >
            <div className="font-medium text-neutral-800">
              #{c.id} — {c.name}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-neutral-500">
              <span>{c.post_slug}</span>
              <StatusPill status={c.status} />
              <span className="ml-auto">{c.created_at.slice(0, 10)}</span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

// ---- New campaign form ----------------------------------------------------

function NewCampaignPanel({ onCreated }: { onCreated: (c: OutreachCampaign) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState("");
  const [intent, setIntent] = useState("share");
  const [senderEmail, setSenderEmail] = useState("");
  const [senderName, setSenderName] = useState("");
  const [bccEmail, setBccEmail] = useState("");

  const posts = useQuery({
    queryKey: ["outreach-blog-posts"],
    queryFn: listOutreachBlogPosts,
    enabled: open,
  });

  const create = useMutation({
    mutationFn: () =>
      createOutreachCampaign({
        post_slug: slug,
        intent,
        sender_email: senderEmail || undefined,
        sender_name: senderName || undefined,
        bcc_email: bccEmail || undefined,
      }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["outreach-campaigns"] });
      onCreated(c);
      setOpen(false);
      setSlug("");
    },
  });

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-neutral-500 hover:bg-neutral-50"
      >
        <span className="inline-flex items-center gap-1.5">
          <PlusCircle className="h-3.5 w-3.5" />
          New campaign
        </span>
        <span className="text-[10px] font-normal">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-neutral-100 px-4 py-3 text-xs">
          <label className="block">
            <span className="text-neutral-500">Blog post</span>
            <select
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="mt-0.5 w-full rounded border border-neutral-200 px-2 py-1.5 text-xs"
            >
              <option value="">— pick a post —</option>
              {posts.data?.map((p) => (
                <option key={p.slug} value={p.slug}>
                  {p.slug}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-neutral-500">Intent</span>
            <select
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              className="mt-0.5 w-full rounded border border-neutral-200 px-2 py-1.5 text-xs"
            >
              <option value="share">share — drop the link, no ask</option>
              <option value="nudge">nudge — re-engage past contact</option>
              <option value="book">book — drive consult click</option>
            </select>
          </label>
          <label className="block">
            <span className="text-neutral-500">Sender email (optional)</span>
            <input
              value={senderEmail}
              onChange={(e) => setSenderEmail(e.target.value)}
              placeholder="defaults to OUTREACH_SENDER_EMAIL env"
              className="mt-0.5 w-full rounded border border-neutral-200 px-2 py-1.5 text-xs"
            />
          </label>
          <label className="block">
            <span className="text-neutral-500">Sender name (optional)</span>
            <input
              value={senderName}
              onChange={(e) => setSenderName(e.target.value)}
              placeholder="defaults to OUTREACH_SENDER_NAME env"
              className="mt-0.5 w-full rounded border border-neutral-200 px-2 py-1.5 text-xs"
            />
          </label>
          <label className="block">
            <span className="text-neutral-500">BCC (optional)</span>
            <input
              value={bccEmail}
              onChange={(e) => setBccEmail(e.target.value)}
              placeholder="e.g. archive@yourdomain.com — gets a blind copy of every send"
              className="mt-0.5 w-full rounded border border-neutral-200 px-2 py-1.5 text-xs"
            />
          </label>
          <button
            disabled={!slug || create.isPending}
            onClick={() => create.mutate()}
            className="w-full rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            {create.isPending ? "Creating…" : "Create campaign"}
          </button>
          {create.error && (
            <p className="text-[11px] text-red-600">
              {(create.error as Error).message}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

// ---- Campaign detail (stats + audience + composer) ------------------------

function CampaignDetail({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();

  const detail = useQuery({
    queryKey: ["outreach-campaign", campaignId],
    queryFn: () => getOutreachCampaign(campaignId),
  });

  if (detail.isLoading) {
    return <p className="px-4 py-4 text-xs text-neutral-400">Loading…</p>;
  }
  if (!detail.data) {
    return null;
  }
  const c = detail.data;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["outreach-campaign", campaignId] });
    qc.invalidateQueries({ queryKey: ["outreach-next", campaignId] });
    qc.invalidateQueries({ queryKey: ["outreach-sends", campaignId] });
  };

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-neutral-200 bg-white p-5">
        <div className="flex items-start gap-3">
          <Mail className="mt-0.5 h-5 w-5 text-neutral-400" />
          <div className="flex-1">
            <h2 className="text-base font-semibold text-neutral-900">
              {c.name}
            </h2>
            <p className="mt-1 text-xs text-neutral-500">
              {c.post_title}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-neutral-500">
              <span>
                <span className="text-neutral-400">post: </span>
                <a
                  href={c.post_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-emerald-700 hover:underline"
                >
                  {c.post_slug}
                </a>
              </span>
              <span>
                <span className="text-neutral-400">intent: </span>
                {c.intent}
              </span>
              <span>
                <span className="text-neutral-400">from: </span>
                {c.sender_name} &lt;{c.sender_email}&gt;
              </span>
              <BccEditor
                campaignId={c.id}
                value={c.bcc_email ?? null}
                onSaved={refresh}
              />
              <StatusPill status={c.status} />
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
          <StatTile label="total" value={c.stats.total} />
          <StatTile label="pending" value={c.stats.pending} />
          <StatTile label="composed" value={c.stats.composed} accent="emerald" />
          <StatTile label="sent" value={c.stats.sent} accent="blue" />
          <StatTile label="skipped" value={c.stats.skipped} />
          <StatTile label="failed" value={c.stats.failed} accent={c.stats.failed > 0 ? "red" : undefined} />
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile label="opens" value={c.stats.opens} accent="blue" />
          <StatTile label="unique opens" value={c.stats.unique_opens} accent="blue" />
          <StatTile label="clicks" value={c.stats.clicks} accent="emerald" />
          <StatTile label="unique clicks" value={c.stats.unique_clicks} accent="emerald" />
        </div>
      </section>

      <ActivityPanel campaignId={campaignId} />

      <AudiencePanel campaignId={campaignId} onAdded={refresh} />

      <StepThroughComposer campaignId={campaignId} onAdvanced={refresh} />
    </div>
  );
}

// ---- Activity (open + click timeline) -------------------------------------

function ActivityPanel({ campaignId }: { campaignId: number }) {
  const [kind, setKind] = useState<"all" | "open" | "click">("all");
  const [open, setOpen] = useState(true);

  const events = useQuery({
    queryKey: ["outreach-events", campaignId, kind],
    queryFn: () =>
      listOutreachEvents(campaignId, {
        kind: kind === "all" ? undefined : kind,
        limit: 200,
      }),
    enabled: open,
    refetchInterval: open ? 15_000 : false,
  });

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-neutral-500 hover:bg-neutral-50"
      >
        <span className="inline-flex items-center gap-1.5">
          <Eye className="h-3.5 w-3.5" />
          Activity {events.data ? `(${events.data.length})` : ""}
        </span>
        <span className="text-[10px] font-normal">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <>
          <div className="flex items-center gap-1 border-t border-neutral-100 px-4 py-2">
            {(["all", "open", "click"] as const).map((k) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={
                  "rounded px-2 py-0.5 text-[11px] font-medium " +
                  (kind === k
                    ? "bg-neutral-900 text-white"
                    : "text-neutral-500 hover:bg-neutral-100")
                }
              >
                {k}
              </button>
            ))}
            <span className="ml-auto text-[10px] text-neutral-400">
              auto-refresh every 15s
            </span>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {events.isLoading && (
              <p className="px-4 py-3 text-[11px] text-neutral-400">Loading…</p>
            )}
            {events.data && events.data.length === 0 && (
              <p className="px-4 py-6 text-center text-[11px] text-neutral-400">
                No {kind === "all" ? "" : kind + " "}events yet. Opens fire when
                recipients view the email; clicks fire when they tap the
                tracked link.
              </p>
            )}
            {events.data && events.data.length > 0 && (
              <ul className="divide-y divide-neutral-100 text-xs">
                {events.data.map((e) => (
                  <li
                    key={e.id}
                    className="flex items-start gap-2 px-4 py-2"
                  >
                    <span
                      className={
                        "mt-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium " +
                        (e.kind === "click"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-blue-50 text-blue-700")
                      }
                    >
                      {e.kind}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-neutral-800">
                        {e.recipient_email}
                      </div>
                      <div className="truncate text-[11px] text-neutral-500">
                        {new Date(e.ts).toLocaleString()}
                        {e.ip && ` · ${e.ip}`}
                        {e.user_agent && ` · ${truncateUA(e.user_agent)}`}
                      </div>
                      {e.url && e.kind === "click" && (
                        <div className="truncate text-[11px] text-neutral-400">
                          → {e.url}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function BccEditor({
  campaignId,
  value,
  onSaved,
}: {
  campaignId: number;
  value: string | null;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");

  useEffect(() => {
    // If the server value changes (e.g. another tab), sync the draft
    // back when we're not actively editing.
    if (!editing) setDraft(value ?? "");
  }, [value, editing]);

  const save = useMutation({
    mutationFn: () => updateOutreachCampaignBcc(campaignId, draft.trim() || null),
    onSuccess: () => {
      setEditing(false);
      onSaved();
    },
  });

  if (!editing) {
    return (
      <span className="inline-flex items-center gap-1">
        <span className="text-neutral-400">bcc: </span>
        <span>{value || <span className="text-neutral-400 italic">none</span>}</span>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-emerald-700 hover:underline"
        >
          edit
        </button>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-neutral-400">bcc: </span>
      <input
        type="email"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="you@example.com"
        autoFocus
        className="rounded border border-neutral-200 px-1.5 py-0.5 text-[11px]"
      />
      <button
        type="button"
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="text-emerald-700 hover:underline disabled:opacity-50"
      >
        {save.isPending ? "saving…" : "save"}
      </button>
      <button
        type="button"
        onClick={() => {
          setDraft(value ?? "");
          setEditing(false);
          save.reset();
        }}
        className="text-neutral-500 hover:underline"
      >
        cancel
      </button>
      {save.error && (
        <span className="text-red-600">{(save.error as Error).message}</span>
      )}
    </span>
  );
}

function truncateUA(ua: string): string {
  // Most user-agent strings are 100-300 chars and unreadable; keep the
  // browser/OS hint and drop the rest.
  if (ua.length <= 60) return ua;
  return ua.slice(0, 57) + "…";
}

// ---- Audience builder -----------------------------------------------------

function AudiencePanel({
  campaignId,
  onAdded,
}: {
  campaignId: number;
  onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [selectedFirms, setSelectedFirms] = useState<Set<string>>(new Set());
  const [excludeRecentDays, setExcludeRecentDays] = useState(14);
  const [search, setSearch] = useState("");

  const firms = useQuery({
    queryKey: ["firms-with-contacts"],
    queryFn: listFirmsWithContacts,
    enabled: open,
  });

  const add = useMutation({
    mutationFn: () =>
      addOutreachAudience(campaignId, {
        pif_ids: Array.from(selectedFirms),
        exclude_recent_days: excludeRecentDays,
      }),
    onSuccess: () => {
      setSelectedFirms(new Set());
      onAdded();
    },
  });

  const toggleFirm = (pif: string) => {
    setSelectedFirms((s) => {
      const next = new Set(s);
      if (next.has(pif)) {
        next.delete(pif);
      } else {
        next.add(pif);
      }
      return next;
    });
  };

  const allFirms: FirmWithContacts[] = firms.data ?? [];
  const filteredFirms = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return allFirms;
    return allFirms.filter((f) => (f.firm_name || "").toLowerCase().includes(q));
  }, [allFirms, search]);

  // Upper-bound preview: sum of contact_count across selected firms,
  // before any no-email/dup/recent filtering happens server-side.
  const selectedContactCountMax = useMemo(
    () =>
      allFirms
        .filter((f) => selectedFirms.has(f.pif_id))
        .reduce((sum, f) => sum + (f.contact_count || 0), 0),
    [allFirms, selectedFirms],
  );

  const selectAllVisible = () => {
    setSelectedFirms((s) => {
      const next = new Set(s);
      filteredFirms.forEach((f) => next.add(f.pif_id));
      return next;
    });
  };
  const clearAll = () => setSelectedFirms(new Set());

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-neutral-500 hover:bg-neutral-50"
      >
        <span className="inline-flex items-center gap-1.5">
          <Users className="h-3.5 w-3.5" />
          Add audience
        </span>
        <span className="text-[10px] font-normal">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-neutral-100 px-4 py-3 text-xs">
          <p className="text-neutral-500">
            Pick firms — every emailable contact at the selected firms gets
            added as a pending recipient. Already-emailed contacts in the
            last N days are skipped.
          </p>
          <label className="flex items-center gap-2">
            <span className="text-neutral-500">Skip contacts emailed in last</span>
            <input
              type="number"
              min={0}
              value={excludeRecentDays}
              onChange={(e) => setExcludeRecentDays(Number(e.target.value) || 0)}
              className="w-16 rounded border border-neutral-200 px-2 py-1 text-xs"
            />
            <span className="text-neutral-500">days (0 = disable)</span>
          </label>

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search firms…"
              className="flex-1 rounded border border-neutral-200 px-2 py-1 text-xs"
            />
            <button
              type="button"
              onClick={selectAllVisible}
              disabled={filteredFirms.length === 0}
              className="rounded border border-neutral-200 px-2 py-1 text-[11px] text-neutral-600 hover:bg-neutral-50 disabled:opacity-50"
              title="Select every firm currently visible in the list"
            >
              Select visible
            </button>
            <button
              type="button"
              onClick={clearAll}
              disabled={selectedFirms.size === 0}
              className="rounded border border-neutral-200 px-2 py-1 text-[11px] text-neutral-600 hover:bg-neutral-50 disabled:opacity-50"
            >
              Clear
            </button>
          </div>

          <div className="max-h-[280px] overflow-y-auto rounded border border-neutral-100">
            {filteredFirms.length === 0 && (
              <p className="px-3 py-2 text-[11px] text-neutral-400">
                {firms.isLoading ? "Loading firms…" : "No firms match this search."}
              </p>
            )}
            {filteredFirms.map((f: FirmWithContacts) => (
              <label
                key={f.pif_id}
                className="flex cursor-pointer items-center gap-2 border-b border-neutral-50 px-3 py-1.5 text-xs hover:bg-neutral-50"
              >
                <input
                  type="checkbox"
                  checked={selectedFirms.has(f.pif_id)}
                  onChange={() => toggleFirm(f.pif_id)}
                />
                <Building2 className="h-3 w-3 text-neutral-400" />
                <span className="flex-1 truncate">{f.firm_name}</span>
                <span className="text-[10px] text-neutral-400">
                  {f.contact_count} contact{f.contact_count === 1 ? "" : "s"}
                </span>
              </label>
            ))}
          </div>

          {selectedFirms.size > 0 && (
            <p className="text-[11px] text-neutral-500">
              {selectedFirms.size} firm{selectedFirms.size === 1 ? "" : "s"} selected · up to{" "}
              {selectedContactCountMax} contact{selectedContactCountMax === 1 ? "" : "s"}{" "}
              before dedupe/skip
            </p>
          )}

          <button
            disabled={selectedFirms.size === 0 || add.isPending}
            onClick={() => add.mutate()}
            className="w-full rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            {add.isPending
              ? "Adding…"
              : selectedFirms.size === 0
              ? "Pick at least one firm"
              : `Add contacts from ${selectedFirms.size} firm${selectedFirms.size === 1 ? "" : "s"}`}
          </button>
          {add.data && (
            <p className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-emerald-700">
              Added {add.data.added}  ·  skipped {add.data.skipped_no_email} no-email,{" "}
              {add.data.skipped_duplicate} dup, {add.data.skipped_recent_outreach} recent
            </p>
          )}
          {add.error && (
            <p className="text-[11px] text-red-600">
              {(add.error as Error).message}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

// ---- Step-through composer (the main attraction) --------------------------

function useElapsedSeconds(active: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) {
      setSeconds(0);
      return;
    }
    const startedAt = Date.now();
    setSeconds(0);
    const id = setInterval(
      () => setSeconds(Math.floor((Date.now() - startedAt) / 1000)),
      500,
    );
    return () => clearInterval(id);
  }, [active]);
  return seconds;
}

function StepThroughComposer({
  campaignId,
  onAdvanced,
}: {
  campaignId: number;
  onAdvanced: () => void;
}) {
  const qc = useQueryClient();
  const [skipReason, setSkipReason] = useState("");

  const nextQ = useQuery({
    queryKey: ["outreach-next", campaignId],
    queryFn: () => getNextOutreachSend(campaignId),
  });

  const sendsQ = useQuery({
    queryKey: ["outreach-sends", campaignId],
    queryFn: () => listOutreachSends(campaignId),
  });

  const current = nextQ.data;
  const remaining = useMemo(
    () =>
      (sendsQ.data || []).filter(
        (s) => s.status === "pending" || s.status === "composed",
      ).length,
    [sendsQ.data],
  );
  const totalActionable = useMemo(
    () =>
      (sendsQ.data || []).filter(
        (s) => s.status !== "skipped" && s.status !== "failed",
      ).length,
    [sendsQ.data],
  );

  const compose = useMutation({
    mutationFn: (regenerate: boolean) =>
      composeOutreachSend(current!.id, regenerate),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["outreach-next", campaignId] });
      qc.invalidateQueries({ queryKey: ["outreach-sends", campaignId] });
      qc.invalidateQueries({ queryKey: ["outreach-preview", current?.id] });
    },
  });
  const composeElapsed = useElapsedSeconds(compose.isPending);

  const send = useMutation({
    mutationFn: () => sendOutreachSend(current!.id),
    onSuccess: () => {
      onAdvanced();
      setSkipReason("");
    },
  });

  const skip = useMutation({
    mutationFn: (reason: string) => skipOutreachSend(current!.id, reason),
    onSuccess: () => {
      onAdvanced();
      setSkipReason("");
    },
  });

  if (nextQ.isLoading) {
    return (
      <section className="rounded-xl border border-neutral-200 bg-white p-5 text-xs text-neutral-500">
        Loading next recipient…
      </section>
    );
  }

  if (!current) {
    return (
      <div className="space-y-4">
        <section className="rounded-xl border border-neutral-200 bg-white p-8 text-center text-sm text-neutral-500">
          <CheckCircle2 className="mx-auto h-6 w-6 text-emerald-500" />
          <p className="mt-2">All recipients drained.</p>
          <p className="text-xs text-neutral-400">
            Add more contacts via the audience panel, or pick another campaign.
          </p>
        </section>
        <QueuePanel sends={sendsQ.data ?? []} currentId={null} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
    <section className="rounded-xl border border-neutral-200 bg-white p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-neutral-800">
          Next recipient
        </h2>
        <span className="text-[11px] text-neutral-400">
          {remaining} of {totalActionable} remaining
        </span>
      </div>

      <RecipientCard send={current} />

      {current.status === "pending" && (
        <div className="mt-3 rounded border border-dashed border-neutral-200 px-3 py-3 text-center text-xs text-neutral-500">
          <p>Not yet composed.</p>
          <button
            disabled={compose.isPending}
            onClick={() => compose.mutate(false)}
            className="mt-2 inline-flex items-center gap-1.5 rounded bg-neutral-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-900 disabled:opacity-60"
          >
            {compose.isPending ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Composing… {composeElapsed}s
              </>
            ) : (
              <>
                <RefreshCw className="h-3.5 w-3.5" />
                Compose now (calls LLM gateway)
              </>
            )}
          </button>
          {compose.isPending && (
            <p className="mt-2 text-[11px] text-neutral-400">
              LLM calls usually take 30–90s. Don&apos;t refresh.
            </p>
          )}
          {compose.error && !compose.isPending && (
            <p className="mt-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
              Compose failed: {(compose.error as Error).message}
            </p>
          )}
        </div>
      )}

      {current.status === "composed" && (
        <>
          <ComposedCard send={current} />
          <PreviewPanel sendId={current.id} />

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              disabled={send.isPending}
              onClick={() => {
                if (
                  confirm(
                    `Really send to ${current.recipient_email}?\nSubject: ${current.composed_subject}`,
                  )
                ) {
                  send.mutate();
                }
              }}
              className="inline-flex items-center gap-1.5 rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
            >
              {send.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              Send now
            </button>
            <button
              disabled={compose.isPending}
              onClick={() => compose.mutate(true)}
              className="inline-flex items-center gap-1.5 rounded border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {compose.isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Regenerating… {composeElapsed}s
                </>
              ) : (
                <>
                  <RefreshCw className="h-3.5 w-3.5" />
                  Regenerate
                </>
              )}
            </button>
            <div className="ml-auto flex items-center gap-1.5">
              <input
                value={skipReason}
                onChange={(e) => setSkipReason(e.target.value)}
                placeholder="skip reason"
                className="rounded border border-neutral-200 px-2 py-1 text-xs"
              />
              <button
                disabled={!skipReason.trim() || skip.isPending}
                onClick={() => skip.mutate(skipReason.trim())}
                className="inline-flex items-center gap-1.5 rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-60"
              >
                <SkipForward className="h-3.5 w-3.5" />
                Skip
              </button>
            </div>
          </div>

          {send.data && (
            <p className="mt-3 rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-[11px] text-emerald-700">
              Sent · message_id={send.data.message_id} · transport={send.data.transport}
            </p>
          )}
          {send.error && (
            <p className="mt-3 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
              Send failed: {(send.error as Error).message}
            </p>
          )}
          {compose.isPending && (
            <p className="mt-3 rounded border border-neutral-200 bg-neutral-50 px-2 py-1.5 text-[11px] text-neutral-600">
              Regenerating with LLM… {composeElapsed}s elapsed (usually 30–90s).
            </p>
          )}
          {compose.error && !compose.isPending && (
            <p className="mt-3 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
              Regenerate failed: {(compose.error as Error).message}
            </p>
          )}
        </>
      )}
    </section>
    <QueuePanel sends={sendsQ.data ?? []} currentId={current.id} />
    </div>
  );
}

function QueuePanel({
  sends,
  currentId,
}: {
  sends: OutreachSend[];
  currentId: number | null;
}) {
  // Active items (pending/composed) first in insertion order; everything
  // else (sent/skipped/failed) below, also in insertion order. Same order
  // as the server-side queue, so "next up" in this list = next up in the
  // workbench.
  const ranked = useMemo(() => {
    const rank = (s: OutreachSend) =>
      s.status === "pending" || s.status === "composed" ? 0 : 1;
    return [...sends].sort((a, b) => {
      const dr = rank(a) - rank(b);
      if (dr !== 0) return dr;
      return a.id - b.id;
    });
  }, [sends]);

  if (sends.length === 0) {
    return (
      <section className="rounded-xl border border-neutral-200 bg-white p-4 text-xs text-neutral-500">
        Queue is empty. Add contacts via the Add audience panel.
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center justify-between px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-neutral-500">
        <span>Queue ({sends.length})</span>
        <span className="text-[10px] font-normal normal-case tracking-normal text-neutral-400">
          pending → composed → sent / skipped / failed
        </span>
      </div>
      <ul className="max-h-[420px] divide-y divide-neutral-100 overflow-y-auto border-t border-neutral-100">
        {ranked.map((s) => {
          const isCurrent = s.id === currentId;
          return (
            <li
              key={s.id}
              className={`flex items-center gap-3 px-4 py-2 text-xs ${
                isCurrent ? "bg-emerald-50/60" : "hover:bg-neutral-50"
              }`}
            >
              <span className="w-4 text-center text-[10px] text-neutral-400">
                {isCurrent ? "→" : ""}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-neutral-800">
                  {s.recipient_name || s.recipient_email}
                </div>
                <div className="truncate text-[11px] text-neutral-500">
                  {s.recipient_email}
                  {s.firm_name ? ` · ${s.firm_name}` : ""}
                </div>
              </div>
              <StatusPill status={s.status} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function RecipientCard({ send }: { send: OutreachSend }) {
  const opens = send.opens ?? 0;
  const clicks = send.clicks ?? 0;
  return (
    <div className="rounded-md border border-neutral-100 bg-neutral-50/60 px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium text-neutral-800">
          {send.recipient_name || send.recipient_email}
        </div>
        {(opens > 0 || clicks > 0) && (
          <div className="flex items-center gap-1 text-[10px]">
            {opens > 0 && (
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">
                {opens} open{opens !== 1 ? "s" : ""}
              </span>
            )}
            {clicks > 0 && (
              <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">
                {clicks} click{clicks !== 1 ? "s" : ""}
              </span>
            )}
            {send.last_event_at && (
              <span className="text-neutral-400">
                last {new Date(send.last_event_at).toLocaleString()}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="text-[11px] text-neutral-500">
        {send.recipient_email}
        {send.recipient_title && ` · ${send.recipient_title}`}
      </div>
      <div className="mt-0.5 text-[11px] text-neutral-400">
        {send.firm_name || "—"}
      </div>
    </div>
  );
}

function ComposedCard({ send }: { send: OutreachSend }) {
  return (
    <div className="mt-3 rounded border border-neutral-100 px-3 py-2 text-xs">
      <div className="text-[10px] uppercase tracking-wider text-neutral-400">
        Composed subject
      </div>
      <div className="mt-0.5 text-sm font-medium text-neutral-900">
        {send.composed_subject}
      </div>
      <div className="mt-2 text-[10px] uppercase tracking-wider text-neutral-400">
        Preheader
      </div>
      <div className="mt-0.5 text-neutral-700">{send.composed_preheader}</div>
      {send.composed_reasoning && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-neutral-400">
            LLM reasoning
          </summary>
          <div className="mt-1 whitespace-pre-wrap text-[11px] text-neutral-600">
            {send.composed_reasoning}
          </div>
        </details>
      )}
    </div>
  );
}

function PreviewPanel({ sendId }: { sendId: number }) {
  const [tab, setTab] = useState<"html" | "text">("html");
  const q = useQuery({
    queryKey: ["outreach-preview", sendId],
    queryFn: () => previewOutreachSend(sendId),
  });

  return (
    <div className="mt-3 rounded border border-neutral-100">
      <div className="flex items-center justify-between border-b border-neutral-100 px-3 py-1.5">
        <div className="flex items-center gap-1.5 text-[11px] text-neutral-500">
          <Eye className="h-3 w-3" />
          Exact bytes that will be sent
        </div>
        <div className="flex items-center gap-1">
          <TabButton active={tab === "html"} onClick={() => setTab("html")}>
            HTML
          </TabButton>
          <TabButton active={tab === "text"} onClick={() => setTab("text")}>
            Plaintext
          </TabButton>
        </div>
      </div>
      {q.isLoading && (
        <p className="px-3 py-4 text-xs text-neutral-400">Rendering…</p>
      )}
      {q.data && tab === "html" && (
        <iframe
          title={`outreach-preview-${sendId}`}
          srcDoc={q.data.full_html}
          sandbox=""
          className="h-[480px] w-full rounded-b bg-white"
        />
      )}
      {q.data && tab === "text" && (
        <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap rounded-b bg-neutral-50 p-3 text-[11px] text-neutral-800">
{q.data.full_plaintext}
        </pre>
      )}
      {q.data && (
        <div className="border-t border-neutral-100 px-3 py-1.5 text-[10px] text-neutral-400">
          to: {q.data.to} · from: {q.data.from_header} · click → {q.data.tracked_click_url}
        </div>
      )}
    </div>
  );
}

// ---- Bits -----------------------------------------------------------------

function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: "bg-neutral-100 text-neutral-600",
    ready: "bg-blue-50 text-blue-700",
    sending: "bg-amber-50 text-amber-700",
    paused: "bg-amber-50 text-amber-700",
    complete: "bg-emerald-50 text-emerald-700",
    archived: "bg-neutral-100 text-neutral-500",
    pending: "bg-neutral-100 text-neutral-600",
    composed: "bg-emerald-50 text-emerald-700",
    sent: "bg-blue-50 text-blue-700",
    skipped: "bg-amber-50 text-amber-700",
    failed: "bg-red-50 text-red-700",
  };
  return (
    <span
      className={
        "inline-block rounded px-1.5 py-0.5 text-[10px] font-medium " +
        (colors[status] || "bg-neutral-100 text-neutral-600")
      }
    >
      {status}
    </span>
  );
}

function StatTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: "emerald" | "blue" | "red";
}) {
  const accentClass =
    accent === "emerald"
      ? "text-emerald-700"
      : accent === "blue"
        ? "text-blue-700"
        : accent === "red"
          ? "text-red-700"
          : "text-neutral-800";
  return (
    <div className="rounded border border-neutral-100 bg-neutral-50/60 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-neutral-400">
        {label}
      </div>
      <div className={"text-base font-semibold " + accentClass}>{value}</div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded px-2 py-0.5 text-[11px] font-medium " +
        (active
          ? "bg-neutral-800 text-white"
          : "text-neutral-500 hover:bg-neutral-100")
      }
    >
      {children}
    </button>
  );
}
