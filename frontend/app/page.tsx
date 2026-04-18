"use client";

import Link from "next/link";
import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getDispatcherStatus,
  toggleDispatcher,
  startDispatcherBatch,
  listCalls,
  listLeads,
  listNextUp,
  getSettings,
  setSystemEnabled,
  setMockMode,
  setVoiceProvider,
  setDispatcherCooldown,
  setDispatcherBatchSize,
  setIVRNavigate,
} from "@/lib/api";
import { useDashboardEvents } from "@/hooks/useDashboardEvents";
import { OutcomePill } from "@/components/OutcomePill";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import {
  Play,
  Pause,
  Phone,
  PhoneOff,
  Zap,
  Shield,
  TreePine,
  Mic,
  ChevronRight,
  Headphones,
} from "lucide-react";
import { WebCallModal } from "@/components/WebCallModal";
import type { Lead } from "@/types";

export default function NowPage() {
  const qc = useQueryClient();
  const { lastDecision } = useDashboardEvents();

  const dispatcher = useQuery({
    queryKey: ["dispatcher-status"],
    queryFn: getDispatcherStatus,
    refetchInterval: 5_000,
  });
  const running = dispatcher.data?.running ?? false;

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => toggleDispatcher(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dispatcher-status"] }),
  });

  const startBatch = useMutation({
    mutationFn: (count: number) => startDispatcherBatch(count),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dispatcher-status"] }),
  });

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
    refetchInterval: 15_000,
  });
  const systemEnabled = Boolean(settings.data?.system_enabled);
  const mockOn = Boolean(settings.data?.mock_mode);
  const mockPhone = String(settings.data?.mock_phone ?? "");
  const ivrNavigateOn = Boolean(settings.data?.ivr_navigate_enabled);
  const voiceProvider =
    (settings.data?.voice_provider as "openai" | "gemini" | undefined) ?? "openai";

  const toggleSystem = useMutation({
    mutationFn: (enabled: boolean) => setSystemEnabled(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const [mockPhoneDraft, setMockPhoneDraft] = useState<string | null>(null);
  const toggleMock = useMutation({
    mutationFn: (enabled: boolean) => setMockMode(enabled, mockPhone),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const saveMockPhone = useMutation({
    mutationFn: (phone: string) => setMockMode(true, phone),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const toggleIVR = useMutation({
    mutationFn: (enabled: boolean) => setIVRNavigate(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const switchVoice = useMutation({
    mutationFn: (next: "openai" | "gemini") => setVoiceProvider(next),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const cooldownServer =
    Number(
      (settings.data?.dispatcher_settings as Record<string, unknown> | undefined)
        ?.cooldown_seconds ?? 0,
    ) || 0;
  const [cooldownDraft, setCooldownDraft] = useState<number | null>(null);
  const effectiveCooldown = cooldownDraft ?? cooldownServer;
  const saveCooldown = useMutation({
    mutationFn: (secs: number) => setDispatcherCooldown(secs),
    onSuccess: () => {
      setCooldownDraft(null);
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const recentCalls = useQuery({
    queryKey: ["recent-calls", 5],
    queryFn: () => listCalls(5, 0),
    refetchInterval: 10_000,
  });

  const nextUp = useQuery({
    queryKey: ["leads-next-up"],
    queryFn: listNextUp,
    refetchInterval: 10_000,
  });

  const defaultBatch = (settings.data as any)?.dispatcher_settings?.default_batch_size ?? 5;
  const [batchCount, setBatchCount] = useState<number | null>(null);
  const effectiveBatch = batchCount ?? defaultBatch;

  const saveBatchSize = useMutation({
    mutationFn: (size: number) => setDispatcherBatchSize(size),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  const latestReason = lastDecision?.detail ?? dispatcher.data?.recent_decisions?.[0]?.detail ?? "—";
  const [webCallLead, setWebCallLead] = useState<Lead | null>(null);

  return (
    <div className="space-y-5">
      {/* Status bar */}
      <div className="flex items-center gap-3 rounded-xl bg-gradient-to-r from-neutral-900 to-neutral-800 px-5 py-3.5 text-white shadow-sm">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              running ? "animate-pulse bg-emerald-400" : "bg-neutral-500",
            )}
          />
          <span className="text-sm font-semibold">
            {running ? "Dispatcher active" : "Dispatcher idle"}
          </span>
        </div>
        {dispatcher.data?.batch?.target && (
          <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-medium">
            {dispatcher.data.batch.placed}/{dispatcher.data.batch.target} calls
          </span>
        )}
        <span className="ml-auto text-xs text-neutral-400 max-w-[40%] truncate">
          {latestReason}
        </span>
      </div>

      {/* Controls grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ControlCard
          icon={<Shield className="h-4 w-4" />}
          label="System"
          checked={systemEnabled}
          disabled={toggleSystem.isPending}
          onToggle={(v) => toggleSystem.mutate(v)}
          color={systemEnabled ? "emerald" : "rose"}
        />
        <ControlCard
          icon={<PhoneOff className="h-4 w-4" />}
          label="Mock mode"
          checked={mockOn}
          disabled={toggleMock.isPending}
          onToggle={(v) => toggleMock.mutate(v)}
          color={mockOn ? "amber" : "neutral"}
          sub={mockOn && mockPhone ? mockPhone : undefined}
        />
        <ControlCard
          icon={<TreePine className="h-4 w-4" />}
          label="IVR nav"
          checked={ivrNavigateOn}
          disabled={toggleIVR.isPending}
          onToggle={(v) => toggleIVR.mutate(v)}
          color={ivrNavigateOn ? "emerald" : "neutral"}
        />
        <div className="flex items-center justify-between rounded-xl border border-neutral-200 bg-white px-4 py-3">
          <div className="flex items-center gap-2">
            <Mic className="h-4 w-4 text-neutral-400" />
            <span className="text-sm font-medium text-neutral-700">Voice</span>
          </div>
          <div className="flex overflow-hidden rounded-lg border border-neutral-200 text-[11px] font-medium">
            <button
              onClick={() => switchVoice.mutate("openai")}
              disabled={switchVoice.isPending}
              className={cn(
                "px-2.5 py-1 transition-colors",
                voiceProvider === "openai"
                  ? "bg-sky-600 text-white"
                  : "bg-white text-neutral-600 hover:bg-neutral-50",
              )}
            >
              OpenAI
            </button>
            <button
              onClick={() => switchVoice.mutate("gemini")}
              disabled={switchVoice.isPending}
              className={cn(
                "border-l border-neutral-200 px-2.5 py-1 transition-colors",
                voiceProvider === "gemini"
                  ? "bg-violet-600 text-white"
                  : "bg-white text-neutral-600 hover:bg-neutral-50",
              )}
            >
              Gemini
            </button>
          </div>
        </div>
      </div>

      {/* Mock phone editor */}
      {mockOn && (
        <div className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50/50 px-4 py-2.5">
          <Phone className="h-3.5 w-3.5 text-amber-600" />
          <span className="text-xs font-medium text-amber-800">Mock redirect:</span>
          <input
            type="tel"
            placeholder="+1234567890"
            value={mockPhoneDraft ?? mockPhone}
            onChange={(e) => setMockPhoneDraft(e.target.value)}
            className="w-40 rounded-lg border border-amber-300 bg-white px-2.5 py-1 text-xs font-mono text-neutral-800 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
          />
          {mockPhoneDraft !== null && mockPhoneDraft !== mockPhone && (
            <button
              onClick={() => {
                saveMockPhone.mutate(mockPhoneDraft);
                setMockPhoneDraft(null);
              }}
              disabled={saveMockPhone.isPending}
              className="rounded-lg bg-amber-600 px-3 py-1 text-[11px] font-medium text-white hover:bg-amber-700 transition-colors"
            >
              Save
            </button>
          )}
        </div>
      )}

      {/* Dispatcher controls */}
      <section className="rounded-xl border border-neutral-200 bg-white p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="h-4 w-4 text-neutral-400" />
            <h2 className="text-sm font-semibold text-neutral-900">Dispatcher</h2>
          </div>
          <Switch
            checked={running}
            disabled={toggle.isPending}
            onCheckedChange={(v) => toggle.mutate(v)}
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">
              Batch
            </label>
            <input
              type="number"
              min={1}
              max={200}
              value={effectiveBatch}
              onChange={(e) => {
                const v = Math.max(1, parseInt(e.target.value || "1", 10));
                setBatchCount(v);
                saveBatchSize.mutate(v);
              }}
              className="w-14 rounded-lg border border-neutral-200 bg-neutral-50 px-2 py-1.5 text-center text-sm font-medium text-neutral-800 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
              disabled={running}
            />
          </div>
          <div className="flex items-center gap-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">
              Cooldown
            </label>
            <input
              type="number"
              min={0}
              max={3600}
              value={effectiveCooldown}
              onChange={(e) =>
                setCooldownDraft(Math.max(0, parseInt(e.target.value || "0", 10)))
              }
              className="w-14 rounded-lg border border-neutral-200 bg-neutral-50 px-2 py-1.5 text-center text-sm font-medium text-neutral-800 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
              disabled={saveCooldown.isPending}
            />
            <span className="text-[10px] text-neutral-400">sec</span>
          </div>
          {cooldownDraft !== null && cooldownDraft !== cooldownServer && (
            <button
              onClick={() => saveCooldown.mutate(cooldownDraft)}
              disabled={saveCooldown.isPending}
              className="rounded-lg bg-neutral-900 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-neutral-800 transition-colors"
            >
              Save cooldown
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => startBatch.mutate(effectiveBatch)}
              disabled={running || startBatch.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 transition-colors disabled:opacity-40"
            >
              <Play className="h-3 w-3" />
              Start batch
            </button>
            {running && (
              <button
                onClick={() => toggle.mutate(false)}
                className="flex items-center gap-1.5 rounded-lg bg-rose-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-rose-700 transition-colors"
              >
                <Pause className="h-3 w-3" />
                Stop
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Next up + Recent calls */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* Next up */}
        <section className="rounded-xl border border-neutral-200 bg-white">
          <div className="border-b border-neutral-100 px-5 py-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Next up
            </h2>
          </div>
          <div className="divide-y divide-neutral-100">
            {nextUp.isLoading && (
              <div className="px-5 py-4 text-xs text-neutral-400">loading...</div>
            )}
            {nextUp.data?.patients?.slice(0, 5).map((l) => (
              <div
                key={l.patient_id}
                className="flex items-center gap-3 px-5 py-3 hover:bg-neutral-50 transition-colors"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-100 text-[11px] font-bold text-neutral-500">
                  {l.name.charAt(0)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-neutral-900 truncate">{l.name}</div>
                  <div className="text-[11px] text-neutral-500 truncate">
                    {l.firm_name ?? "—"}
                    {l.state ? ` · ${l.state}` : ""}
                  </div>
                </div>
                <button
                  onClick={() => setWebCallLead(l)}
                  className="rounded-lg border border-neutral-200 p-1.5 text-neutral-400 hover:border-neutral-300 hover:text-neutral-600 transition-colors"
                  title="Test web call"
                >
                  <Headphones className="h-3.5 w-3.5" />
                </button>
                <span className="rounded-md bg-neutral-100 px-1.5 py-0.5 text-[10px] font-semibold text-neutral-500 tabular-nums">
                  P{l.priority_bucket}
                </span>
              </div>
            ))}
            {nextUp.data && (nextUp.data.patients?.length ?? 0) === 0 && (
              <div className="px-5 py-6 text-center text-xs text-neutral-400">
                No eligible leads in queue
              </div>
            )}
          </div>
        </section>

        {/* Recent calls */}
        <section className="rounded-xl border border-neutral-200 bg-white">
          <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Recent calls
            </h2>
            <Link
              href="/calls"
              className="flex items-center gap-0.5 text-[11px] font-medium text-neutral-500 hover:text-neutral-800 transition-colors"
            >
              View all
              <ChevronRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="divide-y divide-neutral-100">
            {recentCalls.isLoading && (
              <div className="px-5 py-4 text-xs text-neutral-400">loading...</div>
            )}
            {recentCalls.data?.calls?.map((c) => (
              <Link
                key={c.call_id}
                href={`/calls/${c.call_id}`}
                className="flex items-center gap-3 px-5 py-3 hover:bg-neutral-50 transition-colors"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-100 text-[11px] font-bold text-neutral-500">
                  {(c.patient_name || "?").charAt(0)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-neutral-900">
                    {c.patient_name}
                  </div>
                  <div className="text-[11px] text-neutral-500">
                    {c.firm_name && <span>{c.firm_name} · </span>}
                    {c.started_at
                      ? formatDistanceToNow(new Date(c.started_at), { addSuffix: true })
                      : ""}
                    {" · "}
                    {c.duration_seconds}s
                  </div>
                </div>
                <OutcomePill outcome={c.outcome} />
              </Link>
            ))}
            {recentCalls.data && (recentCalls.data.calls?.length ?? 0) === 0 && (
              <div className="px-5 py-6 text-center text-xs text-neutral-400">
                No calls yet
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Web call modal */}
      {webCallLead && (
        <WebCallModal
          lead={webCallLead}
          onClose={() => setWebCallLead(null)}
        />
      )}
    </div>
  );
}

function ControlCard({
  icon,
  label,
  checked,
  disabled,
  onToggle,
  color,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  checked: boolean;
  disabled?: boolean;
  onToggle: (v: boolean) => void;
  color: "emerald" | "rose" | "amber" | "neutral";
  sub?: string;
}) {
  const colors = {
    emerald: { bg: "bg-emerald-50", dot: "bg-emerald-500", text: "text-emerald-700" },
    rose: { bg: "bg-rose-50", dot: "bg-rose-500", text: "text-rose-700" },
    amber: { bg: "bg-amber-50", dot: "bg-amber-500", text: "text-amber-700" },
    neutral: { bg: "bg-neutral-50", dot: "bg-neutral-400", text: "text-neutral-600" },
  }[color];

  return (
    <div
      className={cn(
        "flex items-center justify-between rounded-xl border px-4 py-3 transition-colors",
        checked ? `${colors.bg} border-${color}-200` : "border-neutral-200 bg-white",
      )}
    >
      <div className="flex items-center gap-2.5">
        <span className={cn("text-neutral-400", checked && colors.text)}>{icon}</span>
        <div>
          <span className="text-sm font-medium text-neutral-800">{label}</span>
          {sub && (
            <div className="text-[10px] font-mono text-neutral-500 truncate max-w-[120px]">
              {sub}
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            checked ? colors.dot : "bg-neutral-300",
          )}
        />
        <Switch checked={checked} disabled={disabled} onCheckedChange={onToggle} />
      </div>
    </div>
  );
}
