"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCode2, FlaskConical, Loader2, Pencil, RefreshCw, Save, UploadCloud, X } from "lucide-react";
import {
  getComposerAbReport,
  getComposerVariantStats,
  updateComposerVariant,
  uploadComposerVariant,
  type ComposerSkillVariantStats,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const WINDOWS = [1, 7, 30, 90];

function formatRate(value: number | null) {
  if (value === null || Number.isNaN(value)) return "n/a";
  return `${Math.round(value * 1000) / 10}%`;
}

function shortHash(value: string | null) {
  return value ? value.slice(0, 10) : "-";
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
      <div className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold text-neutral-900">{value}</div>
    </div>
  );
}

function inferLabelFromFile(file: File | null) {
  if (!file) return "";
  return file.name
    .replace(/\.md$/i, "")
    .replace(/^skill$/i, "")
    .replace(/[-_]+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase()) || "New Composer Variant";
}

function UploadVariantPanel() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [allocationWeight, setAllocationWeight] = useState(100);
  const [isDragging, setIsDragging] = useState(false);
  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a SKILL.md file first.");
      return uploadComposerVariant({
        file,
        label,
        description,
        allocationWeight,
        active: true,
      });
    },
    onSuccess: () => {
      setFile(null);
      setLabel("");
      setDescription("");
      setAllocationWeight(100);
      qc.invalidateQueries({ queryKey: ["composer-variant-stats"] });
      qc.invalidateQueries({ queryKey: ["composer-variants"] });
    },
  });
  const selectFile = (nextFile: File | null) => {
    setFile(nextFile);
    if (nextFile && !label.trim()) {
      setLabel(inferLabelFromFile(nextFile));
    }
  };

  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="rounded-lg bg-neutral-900 p-2 text-white">
          <UploadCloud className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-neutral-950">Upload skill variant</h2>
          <p className="mt-1 text-sm text-neutral-600">
            Drop a raw `SKILL.md` file here, name the variant, then use it from Lead Gen.
          </p>
        </div>
      </div>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          selectFile(event.dataTransfer.files?.[0] ?? null);
        }}
        className={cn(
          "mt-4 flex min-h-28 flex-col items-center justify-center rounded-lg border border-dashed px-4 py-5 text-center",
          isDragging
            ? "border-neutral-900 bg-neutral-50"
            : "border-neutral-300 bg-white",
        )}
      >
        <UploadCloud className="h-5 w-5 text-neutral-400" />
        <div className="mt-2 text-sm font-medium text-neutral-800">
          {file ? file.name : "Drop SKILL.md here"}
        </div>
        <label className="mt-2 inline-flex cursor-pointer items-center rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50">
          Browse file
          <input
            type="file"
            accept=".md,text/markdown,text/plain"
            className="sr-only"
            onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
          />
        </label>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_140px]">
        <label className="block text-xs font-medium text-neutral-600">
          Variant name
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-2 text-sm text-neutral-900"
            placeholder="Reply-first precise proof"
          />
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          Allocation
          <input
            type="number"
            min={0}
            max={1000}
            value={allocationWeight}
            onChange={(event) => setAllocationWeight(Number(event.target.value || 0))}
            className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-2 text-sm text-neutral-900"
          />
        </label>
        <label className="block text-xs font-medium text-neutral-600 md:col-span-2">
          Description
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-2 text-sm text-neutral-900"
            placeholder="What this variant is testing"
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => upload.mutate()}
          disabled={upload.isPending || !file || !label.trim()}
          className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
        >
          {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
          Upload variant
        </button>
        {upload.isSuccess && (
          <span className="text-xs text-emerald-700">Variant uploaded.</span>
        )}
        {upload.isError && (
          <span className="text-xs text-red-600">
            {upload.error instanceof Error ? upload.error.message : "Upload failed."}
          </span>
        )}
      </div>
    </section>
  );
}

function VariantCard({ variant }: { variant: ComposerSkillVariantStats }) {
  const qc = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [label, setLabel] = useState(variant.label);
  const [description, setDescription] = useState(variant.description || "");
  const rename = useMutation({
    mutationFn: () =>
      updateComposerVariant(variant.key, {
        label,
        description,
      }),
    onSuccess: () => {
      setIsEditing(false);
      qc.invalidateQueries({ queryKey: ["composer-variant-stats"] });
      qc.invalidateQueries({ queryKey: ["composer-variants"] });
    },
  });
  const resetEdit = () => {
    setLabel(variant.label);
    setDescription(variant.description || "");
    setIsEditing(false);
  };

  return (
    <article className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-start gap-3 border-b border-neutral-100 px-4 py-3">
        <div className="rounded-lg bg-neutral-900 p-2 text-white">
          <FileCode2 className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          {isEditing ? (
            <div className="space-y-2">
              <input
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                className="w-full max-w-md rounded-md border border-neutral-200 px-2 py-1.5 text-sm font-semibold text-neutral-950"
                placeholder="Variant name"
              />
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={2}
                className="w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm text-neutral-700"
                placeholder="Short description"
              />
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => rename.mutate()}
                  disabled={rename.isPending || !label.trim()}
                  className="inline-flex items-center gap-1 rounded-md bg-neutral-900 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
                >
                  {rename.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                  Save name
                </button>
                <button
                  type="button"
                  onClick={resetEdit}
                  disabled={rename.isPending}
                  className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
                >
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </button>
                {rename.isError && (
                  <span className="text-xs text-red-600">Could not save variant name.</span>
                )}
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-neutral-950">{variant.label}</h2>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[11px] font-medium",
                    variant.active
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-neutral-100 text-neutral-500",
                  )}
                >
                  {variant.active ? "active" : "inactive"}
                </span>
                {variant.is_baseline && (
                  <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                    baseline
                  </span>
                )}
                {!variant.is_baseline && (
                  <button
                    type="button"
                    onClick={() => setIsEditing(true)}
                    className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
                  >
                    <Pencil className="h-3 w-3" />
                    Rename
                  </button>
                )}
              </div>
              <p className="mt-1 text-xs text-neutral-500">
                {variant.description || "No description."}
              </p>
            </>
          )}
          <div className="mt-2 text-[11px] text-neutral-400">
            key {variant.key}
          </div>
          <div className="mt-2 break-all text-[11px] text-neutral-400">
            {variant.skill_path}
          </div>
          <div className="mt-1 text-[11px] text-neutral-400">
            hash {shortHash(variant.skill_sha256)} - allocation {variant.allocation_weight}
          </div>
        </div>
      </div>
      <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Composed" value={variant.compose_count} />
        <Metric label="Sent" value={variant.send_count} />
        <Metric label="Manual edit" value={formatRate(variant.manual_edit_rate)} />
        <Metric label="Regenerated" value={variant.regenerate_count} />
        <Metric label="Replies" value={`${variant.reply_count} (${formatRate(variant.reply_rate)})`} />
        <Metric label="Bounces" value={`${variant.bounce_count} (${formatRate(variant.bounce_rate)})`} />
        <Metric
          label="Booked qual."
          value={`${variant.booked_qualified_conversation_count} (${formatRate(variant.booked_qualified_conversation_rate)})`}
        />
        <Metric label="Send rate" value={formatRate(variant.send_rate)} />
      </div>
    </article>
  );
}
export default function ComposerAbPage() {
  const [days, setDays] = useState(30);
  const stats = useQuery({
    queryKey: ["composer-variant-stats", days],
    queryFn: () => getComposerVariantStats(days),
    refetchInterval: 60_000,
  });
  const report = useQuery({
    queryKey: ["composer-ab-report", days],
    queryFn: () => getComposerAbReport(days),
    refetchInterval: 60_000,
  });

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-lg bg-neutral-900 p-2 text-white">
          <FlaskConical className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-lg font-semibold text-neutral-900">Composer A/B</h1>
          <p className="text-xs text-neutral-500">
            skill variant assignment and outcome stats
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {WINDOWS.map((windowDays) => (
            <button
              key={windowDays}
              type="button"
              onClick={() => setDays(windowDays)}
              className={cn(
                "rounded-md border px-3 py-1.5 text-xs font-medium",
                days === windowDays
                  ? "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-200 text-neutral-600 hover:bg-neutral-50",
              )}
            >
              {windowDays}d
            </button>
          ))}
          <button
            type="button"
            onClick={() => stats.refetch()}
            disabled={stats.isFetching}
            className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {stats.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh
          </button>
        </div>
      </div>


      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-neutral-950">
          Experiment verdicts — {report.data?.axis ?? "subject_line"}
        </h2>
        <p className="mt-1 text-xs text-neutral-500">
          Persona-blocked. A verdict needs ≥{report.data?.min_sends_per_arm ?? 40} sends per arm and{" "}
          {Math.round(((report.data?.decision_probability ?? 0.9) * 100))}% probability of beating baseline.
        </p>
        {(report.data?.warnings ?? []).map((w) => (
          <p key={w} className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">{w}</p>
        ))}
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-neutral-500">
              <tr>
                {["variant", "sent", "opened", "replied", "declined", "open rate", "reply rate", "P>base (opens)", "P>base (replies)", "verdict"].map((h) => (
                  <th key={h} className="px-2 py-1.5 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(report.data?.arms ?? []).map((arm) => (
                <tr key={arm.variant} className="border-t border-neutral-100">
                  <td className="px-2 py-1.5 font-medium text-neutral-900">{arm.variant}{arm.is_baseline ? " (baseline)" : ""}</td>
                  <td className="px-2 py-1.5">{arm.sent}</td>
                  <td className="px-2 py-1.5">{arm.opened}</td>
                  <td className="px-2 py-1.5">{arm.replied}</td>
                  <td className="px-2 py-1.5">{arm.declined}</td>
                  <td className="px-2 py-1.5">{arm.open_rate == null ? "—" : arm.open_rate.toFixed(2)}</td>
                  <td className="px-2 py-1.5">{arm.reply_rate == null ? "—" : arm.reply_rate.toFixed(2)}</td>
                  <td className="px-2 py-1.5">{arm.p_beats_baseline_opens == null ? "—" : arm.p_beats_baseline_opens.toFixed(2)}</td>
                  <td className="px-2 py-1.5">{arm.p_beats_baseline_replies == null ? "—" : arm.p_beats_baseline_replies.toFixed(2)}</td>
                  <td className="px-2 py-1.5">
                    <span className={
                      arm.verdict === "winner" ? "rounded bg-emerald-100 px-1.5 py-0.5 font-medium text-emerald-700"
                      : arm.verdict === "loser" ? "rounded bg-rose-100 px-1.5 py-0.5 font-medium text-rose-700"
                      : "rounded bg-neutral-100 px-1.5 py-0.5 text-neutral-600"
                    }>{arm.verdict}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-neutral-950">Variant drop folder</h2>
        <p className="mt-1 text-sm text-neutral-600">
          Add a new folder with `SKILL.md`. Optional `variant.json` controls label,
          allocation weight, and active state.
        </p>
        <div className="mt-3 break-all rounded-md bg-neutral-50 px-3 py-2 text-xs text-neutral-600">
          {stats.data?.variants_dir || "app/skills/possible-minds-lead-email-composer/variants"}
        </div>
      </section>

      <UploadVariantPanel />

      {stats.isLoading ? (
        <div className="flex items-center gap-2 rounded-xl border border-neutral-200 bg-white px-6 py-10 text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading composer variants...
        </div>
      ) : stats.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-6 py-10 text-sm text-red-700">
          Could not load composer variant stats.
        </div>
      ) : (
        <div className="space-y-3">
          {(stats.data?.variants ?? []).map((variant) => (
            <VariantCard key={variant.key} variant={variant} />
          ))}
        </div>
      )}
    </div>
  );
}
