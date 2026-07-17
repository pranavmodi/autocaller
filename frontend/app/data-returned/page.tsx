"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Clipboard, Database, Loader2, RefreshCw, Save, Terminal } from "lucide-react";
import {
  getDataReturnedEvents,
  getDataReturnedScript,
  saveDataReturnedScript,
  type DataReturnedEvent,
} from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

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
    second: "2-digit",
  });
}

function jsonPreview(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function payloadLabel(event: DataReturnedEvent) {
  if (Array.isArray(event.payload)) {
    return `Array (${event.payload.length})`;
  }
  const keys = Object.keys(event.payload || {});
  if (!keys.length) return "Object";
  return keys.slice(0, 4).join(", ");
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-neutral-200 bg-white px-3 py-2">
      <div className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold text-neutral-950">{value}</div>
    </div>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      disabled={!text}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable */
        }
      }}
      className="inline-flex items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Clipboard className="h-3.5 w-3.5" />}
      {copied ? "Copied" : label}
    </button>
  );
}

function EventRow({ event }: { event: DataReturnedEvent }) {
  return (
    <article className="rounded-lg border border-neutral-200 bg-white">
      <div className="grid gap-3 border-b border-neutral-100 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-neutral-900 px-2 py-0.5 text-xs font-medium text-white">
              #{event.id}
            </span>
            <h2 className="min-w-0 text-sm font-semibold text-neutral-950">
              {payloadLabel(event)}
            </h2>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
            <span>{formatDateTime(event.received_at)}</span>
            <span>{event.source_ip || "unknown IP"}</span>
            <span>{event.content_type || "unknown content type"}</span>
          </div>
        </div>
        <div className="max-w-full text-xs text-neutral-500 sm:max-w-xs sm:text-right">
          <span className="block truncate" title={event.user_agent || ""}>
            {event.user_agent || "No user agent"}
          </span>
        </div>
      </div>
      <div className="grid gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]">
        <div className="min-w-0">
          <div className="mb-2 text-xs font-medium uppercase tracking-wider text-neutral-400">
            Payload
          </div>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md bg-neutral-950 p-3 text-xs leading-relaxed text-neutral-50">
            {jsonPreview(event.payload)}
          </pre>
        </div>
        <div className="min-w-0">
          <div className="mb-2 text-xs font-medium uppercase tracking-wider text-neutral-400">
            Headers
          </div>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md bg-neutral-50 p-3 text-xs leading-relaxed text-neutral-700">
            {jsonPreview(event.headers)}
          </pre>
        </div>
      </div>
    </article>
  );
}

export default function DataReturnedPage() {
  const [activeTab, setActiveTab] = useState("events");
  const [scriptDraft, setScriptDraft] = useState("");
  const [lastSavedScript, setLastSavedScript] = useState("");
  const [scriptInitialized, setScriptInitialized] = useState(false);
  const eventsQuery = useQuery({
    queryKey: ["datareturned"],
    queryFn: () => getDataReturnedEvents(100),
    refetchInterval: 15_000,
  });
  const scriptQuery = useQuery({
    queryKey: ["datareturned-script"],
    queryFn: getDataReturnedScript,
    staleTime: 60_000,
  });
  const saveScript = useMutation({
    mutationFn: () => saveDataReturnedScript(scriptDraft),
    onSuccess: (saved) => {
      setScriptDraft(saved.script);
      setLastSavedScript(saved.script);
    },
  });

  useEffect(() => {
    if (scriptQuery.data === undefined || scriptInitialized) return;
    setScriptDraft(scriptQuery.data);
    setLastSavedScript(scriptQuery.data);
    setScriptInitialized(true);
  }, [scriptInitialized, scriptQuery.data]);

  const events = eventsQuery.data?.events ?? [];
  const latest = events[0]?.received_at ?? null;
  const uniqueSources = useMemo(
    () => new Set(events.map((event) => event.source_ip).filter(Boolean)).size,
    [events],
  );

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="rounded-lg bg-neutral-900 p-2 text-white">
          <Database className="h-4 w-4" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-neutral-950">Data Returned</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            payloads posted to <span className="font-mono">/datareturned</span>
          </p>
        </div>
        <div className="ml-auto">
          {activeTab === "events" ? (
            <button
              type="button"
              onClick={() => eventsQuery.refetch()}
              disabled={eventsQuery.isFetching}
              className="inline-flex items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {eventsQuery.isFetching ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Refresh
            </button>
          ) : (
            <div className="flex items-center gap-2">
              {saveScript.isSuccess && scriptDraft === lastSavedScript ? (
                <span className="text-xs font-medium text-emerald-600">Saved</span>
              ) : null}
              <CopyButton text={scriptDraft} label="Copy script" />
              <button
                type="button"
                onClick={() => saveScript.mutate()}
                disabled={
                  saveScript.isPending ||
                  !scriptDraft.trim() ||
                  scriptDraft === lastSavedScript
                }
                className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saveScript.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                {saveScript.isPending ? "Saving" : "Save"}
              </button>
            </div>
          )}
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="events">Returned Data</TabsTrigger>
          <TabsTrigger value="script">Shell Script</TabsTrigger>
        </TabsList>

        <TabsContent value="events" className="space-y-4">
          <section className="grid gap-3 sm:grid-cols-3">
            <Stat label="Received" value={eventsQuery.data?.total ?? events.length} />
            <Stat label="Sources" value={uniqueSources} />
            <Stat label="Latest" value={formatDateTime(latest)} />
          </section>

          {eventsQuery.isLoading ? (
            <div className="flex min-h-64 items-center justify-center rounded-lg border border-neutral-200 bg-white text-sm text-neutral-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading returned data
            </div>
          ) : eventsQuery.isError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Could not load returned data.
            </div>
          ) : events.length === 0 ? (
            <div className="rounded-lg border border-neutral-200 bg-white px-4 py-10 text-center text-sm text-neutral-500">
              No payloads received yet.
            </div>
          ) : (
            <section className="space-y-3">
              {events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </section>
          )}
        </TabsContent>

        <TabsContent value="script">
          <section className="rounded-lg border border-neutral-200 bg-white">
            <div className="flex flex-wrap items-start gap-3 border-b border-neutral-100 px-4 py-4">
              <div className="rounded-md bg-neutral-900 p-2 text-white">
                <Terminal className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-neutral-950">Diagnostic callback script</h2>
                <p className="mt-1 max-w-3xl text-sm text-neutral-500">
                  Edit the script served by <span className="font-mono">/datareturned/script</span>. Saved content is publicly retrievable and may be executed by machines that fetch this endpoint.
                </p>
              </div>
              <CopyButton text="/datareturned/script" label="Copy endpoint" />
            </div>
            {scriptQuery.isLoading ? (
              <div className="flex min-h-64 items-center justify-center text-sm text-neutral-500">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Loading shell script
              </div>
            ) : scriptQuery.isError ? (
              <div className="m-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                Could not load the shell script.
              </div>
            ) : (
              <div className="p-4">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-500">
                  <span>
                    Endpoint: <span className="font-mono text-neutral-700">GET /datareturned/script</span>
                  </span>
                  <span>{scriptDraft.length.toLocaleString()} / 100,000 characters</span>
                </div>
                <textarea
                  aria-label="Data returned shell script"
                  value={scriptDraft}
                  onChange={(event) => {
                    setScriptDraft(event.target.value);
                    saveScript.reset();
                  }}
                  maxLength={100_000}
                  spellCheck={false}
                  className="min-h-[32rem] max-h-[60rem] w-full resize-y rounded-md border border-neutral-800 bg-neutral-950 p-4 font-mono text-xs leading-relaxed text-neutral-50 outline-none focus:border-neutral-500 focus:ring-2 focus:ring-neutral-200"
                />
                {saveScript.isError ? (
                  <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    Could not save the shell script. {saveScript.error instanceof Error ? saveScript.error.message : ""}
                  </div>
                ) : null}
              </div>
            )}
          </section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
