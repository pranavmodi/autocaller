"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSettings,
  setVoiceProvider,
  setVoiceConfig,
  OPENAI_VOICES,
  GEMINI_VOICES,
  type VoiceConfigPatch,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Settings = {
  voice_provider?: string;
  voice_model?: string;
  voice_config?: {
    openai?: {
      voice?: string;
      temperature?: number;
      speed?: number;
    };
    gemini?: {
      voice?: string;
      temperature?: number;
      top_p?: number;
      affective_dialog?: boolean;
      proactive_audio?: boolean;
    };
  };
};

/**
 * Panel for configuring the realtime voice backends.
 *
 * Mirrors the CLI surface (`autocaller voice ...`) — default provider
 * selector, per-provider voice name, temperature, and the two
 * Gemini-only flags (affective dialog + proactive audio). Validation
 * lives on the backend; UI just sends the merge-patch.
 */
export function VoiceSettingsPanel() {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => getSettings() as Promise<Settings>,
    refetchInterval: 30_000,
  });

  const provider = (settings.data?.voice_provider || "openai") as "openai" | "gemini";
  const openaiCfg = settings.data?.voice_config?.openai ?? {};
  const geminiCfg = settings.data?.voice_config?.gemini ?? {};

  const switchProvider = useMutation({
    mutationFn: (p: "openai" | "gemini") => setVoiceProvider(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  const patchConfig = useMutation({
    mutationFn: (patch: VoiceConfigPatch) => setVoiceConfig(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Voice
        </h2>
        {settings.data && (
          <span className="text-xs text-neutral-500">
            default: <span className="font-mono">{provider}</span>
          </span>
        )}
      </div>

      {/* Default provider toggle */}
      <div className="mb-6 flex items-center gap-2">
        <span className="text-xs text-neutral-600">Default backend</span>
        {(["openai", "gemini"] as const).map((p) => (
          <button
            key={p}
            onClick={() => switchProvider.mutate(p)}
            disabled={switchProvider.isPending || provider === p}
            className={cn(
              "rounded-md border px-3 py-1 text-xs font-medium transition",
              provider === p
                ? "border-emerald-400 bg-emerald-50 text-emerald-900"
                : "border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50",
            )}
          >
            {p === "openai" ? "OpenAI Realtime" : "Gemini Live"}
          </button>
        ))}
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <ProviderBlock
          label="OpenAI Realtime"
          voices={OPENAI_VOICES}
          voice={openaiCfg.voice}
          temperature={openaiCfg.temperature}
          onVoice={(v) => patchConfig.mutate({ provider: "openai", voice: v })}
          onTemperature={(t) =>
            patchConfig.mutate({ provider: "openai", temperature: t })
          }
          pending={patchConfig.isPending}
        >
          <RangeSliderRow
            label="Speed"
            hint="Playback rate, 1.0 = normal."
            value={openaiCfg.speed}
            min={0.25}
            max={4}
            step={0.05}
            defaultDisplay={1.0}
            disabled={patchConfig.isPending}
            onCommit={(s) =>
              patchConfig.mutate({ provider: "openai", speed: s })
            }
          />
        </ProviderBlock>
        <ProviderBlock
          label="Gemini Live"
          voices={GEMINI_VOICES}
          voice={geminiCfg.voice}
          temperature={geminiCfg.temperature}
          onVoice={(v) => patchConfig.mutate({ provider: "gemini", voice: v })}
          onTemperature={(t) =>
            patchConfig.mutate({ provider: "gemini", temperature: t })
          }
          pending={patchConfig.isPending}
        >
          <RangeSliderRow
            label="Top-P"
            hint="Nucleus sampling cutoff. Lower = more deterministic."
            value={geminiCfg.top_p}
            min={0}
            max={1}
            step={0.01}
            defaultDisplay={0.95}
            disabled={patchConfig.isPending}
            onCommit={(p) =>
              patchConfig.mutate({ provider: "gemini", top_p: p })
            }
          />
          {/* Gemini-only flags */}
          <ToggleRow
            label="Affective dialog"
            hint="Model matches the caller's emotional tone."
            value={!!geminiCfg.affective_dialog}
            disabled={patchConfig.isPending}
            onChange={(v) =>
              patchConfig.mutate({ provider: "gemini", affective_dialog: v })
            }
          />
          <ToggleRow
            label="Proactive audio"
            hint="Model emits short non-verbal cues (mm-hmm, etc.)."
            value={!!geminiCfg.proactive_audio}
            disabled={patchConfig.isPending}
            onChange={(v) =>
              patchConfig.mutate({ provider: "gemini", proactive_audio: v })
            }
          />
        </ProviderBlock>
      </div>

      {patchConfig.isError && (
        <p className="mt-3 text-xs text-rose-700">
          Save failed: {(patchConfig.error as Error).message}
        </p>
      )}
      <p className="mt-4 text-[11px] text-neutral-500">
        Changes apply to the next call. Per-call overrides via{" "}
        <span className="font-mono">--voice=…</span> or{" "}
        <span className="font-mono">voice_provider</span> API body still win.
      </p>
    </section>
  );
}

function ProviderBlock({
  label,
  voices,
  voice,
  temperature,
  onVoice,
  onTemperature,
  pending,
  children,
}: {
  label: string;
  voices: readonly string[];
  voice?: string;
  temperature?: number;
  onVoice: (v: string) => void;
  onTemperature: (t: number) => void;
  pending: boolean;
  children?: React.ReactNode;
}) {
  const [tempDraft, setTempDraft] = useState<string>(
    temperature !== undefined ? String(temperature) : "",
  );
  // Keep the draft in sync when the remote value changes — avoids
  // stale UI after another client flips the setting.
  const synced = useMemo(() => tempDraft, [tempDraft]);
  if (temperature !== undefined && synced !== String(temperature) && !pending) {
    // One-shot reconciliation on remote change.
    setTempDraft(String(temperature));
  }

  return (
    <div className="rounded-md border border-neutral-200 p-4">
      <h3 className="mb-3 text-sm font-semibold text-neutral-900">{label}</h3>

      <label className="mb-3 block text-xs">
        <span className="text-neutral-600">Voice</span>
        <select
          value={voice || ""}
          disabled={pending}
          onChange={(e) => onVoice(e.target.value)}
          className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-1 text-sm"
        >
          <option value="">(backend default)</option>
          {voices.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>

      <label className="mb-3 block text-xs">
        <span className="text-neutral-600">
          Temperature ({temperature ?? "backend default"})
        </span>
        <div className="mt-1 flex items-center gap-2">
          <input
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={tempDraft === "" ? 0.8 : Number(tempDraft)}
            onChange={(e) => setTempDraft(e.target.value)}
            onMouseUp={(e) => onTemperature(Number((e.target as HTMLInputElement).value))}
            onTouchEnd={(e) => onTemperature(Number((e.target as HTMLInputElement).value))}
            disabled={pending}
            className="flex-1"
          />
          <span className="w-10 text-right font-mono text-xs text-neutral-700">
            {tempDraft === "" ? "—" : Number(tempDraft).toFixed(2)}
          </span>
        </div>
      </label>

      {children}
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  value,
  onChange,
  disabled,
}: {
  label: string;
  hint: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="mb-2 flex items-start justify-between gap-3 text-xs">
      <span>
        <span className="block font-medium text-neutral-900">{label}</span>
        <span className="block text-[11px] text-neutral-500">{hint}</span>
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        disabled={disabled}
        onClick={() => onChange(!value)}
        className={cn(
          "mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition",
          value
            ? "border-emerald-500 bg-emerald-500"
            : "border-neutral-300 bg-neutral-200",
        )}
      >
        <span
          className={cn(
            "inline-block h-4 w-4 transform rounded-full bg-white shadow transition",
            value ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </button>
    </label>
  );
}


function RangeSliderRow({
  label,
  hint,
  value,
  min,
  max,
  step,
  defaultDisplay,
  disabled,
  onCommit,
}: {
  label: string;
  hint: string;
  value?: number;
  min: number;
  max: number;
  step: number;
  defaultDisplay: number;
  disabled?: boolean;
  onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState<string>(
    value !== undefined ? String(value) : "",
  );
  if (value !== undefined && draft !== String(value) && !disabled) {
    // One-shot reconciliation when the remote value changes.
    setDraft(String(value));
  }
  const current = draft === "" ? defaultDisplay : Number(draft);
  return (
    <label className="mb-3 block text-xs">
      <span className="text-neutral-600">
        {label} ({value !== undefined ? Number(value).toFixed(2) : "backend default"})
      </span>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={current}
          onChange={(e) => setDraft(e.target.value)}
          onMouseUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
          onTouchEnd={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
          disabled={disabled}
          className="flex-1"
        />
        <span className="w-10 text-right font-mono text-xs text-neutral-700">
          {draft === "" ? "—" : Number(draft).toFixed(2)}
        </span>
      </div>
      <span className="mt-1 block text-[11px] text-neutral-500">{hint}</span>
    </label>
  );
}
