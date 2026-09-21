"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Download, FileText, FolderOpen, Loader2, Search } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { jobAgentRequest, type JobCv, type JobCvCatalog } from "@/lib/job-agent";

const input = "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-900";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium hover:bg-neutral-50";
const primary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800";

function cvUrl(path: string, download = false) {
  const query = new URLSearchParams({ path });
  if (download) query.set("download", "true");
  return apiUrl(`/api/job-agent/resume?${query.toString()}`);
}

function statusLabel(cv: JobCv) {
  if (cv.sent_verified) return "Verified in Zoho Sent";
  if (["sending", "delivery_unconfirmed"].includes(cv.application_status || "")) return "Send verification pending";
  if (["ready", "queued_send"].includes(cv.application_status || "")) return "Prepared for email";
  if (cv.kind === "application") return "Application CV";
  if (cv.kind === "category") return "Category CV";
  return "Saved PDF";
}

function formattedSize(bytes: number) {
  if (!bytes) return "PDF";
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function JobCvLibrary() {
  const catalog = useQuery({ queryKey: ["job-agent", "resumes"], queryFn: () => jobAgentRequest<JobCvCatalog>("/resumes"), staleTime: 30000 });
  const [kind, setKind] = useState<"application" | "category" | "library" | "all">("application");
  const [search, setSearch] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const items = useMemo(() => (catalog.data?.items || []).filter(cv => {
    if (kind !== "all" && cv.kind !== kind) return false;
    const haystack = [cv.filename, cv.firm_name, cv.role_title, ...(cv.category_names || [])].filter(Boolean).join(" ").toLocaleLowerCase();
    return haystack.includes(search.trim().toLocaleLowerCase());
  }), [catalog.data?.items, kind, search]);
  useEffect(() => {
    if (!items.some(cv => cv.path === selectedPath)) setSelectedPath(items[0]?.path || "");
  }, [items, selectedPath]);
  const selected = items.find(cv => cv.path === selectedPath) || items[0];

  if (catalog.isPending) return <div className="flex items-center gap-2 rounded-xl border border-neutral-200 bg-white p-5 text-sm text-neutral-500"><Loader2 className="h-4 w-4 animate-spin" />Loading CVs…</div>;
  if (catalog.error) return <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{catalog.error.message}</div>;

  return <section className="space-y-5" role="tabpanel" id="panel-cvs" aria-labelledby="tab-cvs">
    <div className="overflow-hidden rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 to-white shadow-sm">
      <div className="flex flex-col gap-4 border-b border-violet-100 p-5 sm:flex-row sm:items-start sm:justify-between">
        <div><div className="flex items-center gap-2"><span className="rounded-lg bg-violet-100 p-2 text-violet-700"><FileText className="h-5 w-5" /></span><div><h2 className="font-semibold text-neutral-950">CV library</h2><p className="mt-1 text-sm text-neutral-600">Select, preview and download the exact PDFs prepared for Job Agent emails.</p></div></div></div>
        <div className="flex gap-2 text-xs"><span className="rounded-full border border-violet-200 bg-white px-3 py-1.5 font-medium text-violet-800">{catalog.data?.application_count || 0} application CVs</span><span className="rounded-full border border-neutral-200 bg-white px-3 py-1.5 font-medium text-neutral-600">{catalog.data?.category_count || 0} category CVs</span></div>
      </div>
      <div className="grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_220px]">
        <label className="relative"><span className="sr-only">Search CVs</span><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-neutral-400" /><input className={`${input} pl-9`} value={search} onChange={event => setSearch(event.target.value)} placeholder="Search company, role or filename…" /></label>
        <select className={input} aria-label="Filter CVs" value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="application">Application CVs</option><option value="category">Category CVs</option><option value="library">Other saved PDFs</option><option value="all">All CVs</option></select>
      </div>
    </div>

    {!items.length ? <div className="rounded-xl border border-dashed border-neutral-300 bg-white px-6 py-14 text-center"><FolderOpen className="mx-auto h-7 w-7 text-neutral-400" /><h3 className="mt-3 font-medium">No CVs match this view</h3><p className="mt-1 text-sm text-neutral-500">Change the filter or search. Company-specific CVs appear after an application email is prepared.</p></div> : <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(280px,380px)_minmax(0,1fr)]">
      <div className="max-h-[720px] space-y-2 overflow-y-auto rounded-xl border border-neutral-200 bg-neutral-50 p-2" role="listbox" aria-label="Available CVs">{items.map(cv => <button key={cv.path} role="option" aria-selected={selected?.path === cv.path} onClick={() => setSelectedPath(cv.path)} className={`w-full rounded-lg border p-3 text-left transition ${selected?.path === cv.path ? "border-violet-300 bg-white shadow-sm ring-1 ring-violet-200" : "border-transparent hover:border-neutral-200 hover:bg-white"}`}>
        <div className="flex items-start gap-3"><FileText className={`mt-0.5 h-5 w-5 shrink-0 ${selected?.path === cv.path ? "text-violet-600" : "text-neutral-400"}`} /><div className="min-w-0"><p className="break-words text-sm font-medium text-neutral-900">{cv.firm_name || cv.category_names?.join(", ") || cv.filename}</p>{cv.role_title && <p className="mt-0.5 break-words text-xs text-neutral-600">{cv.role_title}</p>}<p className="mt-1 break-all text-[11px] text-neutral-400">{cv.filename}</p><span className={`mt-2 inline-flex rounded-full px-2 py-1 text-[10px] font-medium ${cv.sent_verified ? "bg-emerald-50 text-emerald-700" : "bg-neutral-100 text-neutral-600"}`}>{statusLabel(cv)}</span></div></div>
      </button>)}</div>

      {selected && <article className="min-w-0 overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
        <div className="border-b border-neutral-200 p-4"><div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div className="min-w-0"><p className="text-xs font-medium uppercase tracking-wide text-violet-700">{statusLabel(selected)}</p><h3 className="mt-1 break-words text-lg font-semibold">{selected.firm_name || selected.category_names?.join(", ") || "Saved CV"}</h3>{selected.role_title && <p className="mt-1 text-sm text-neutral-600">{selected.role_title}</p>}<p className="mt-2 break-all text-xs text-neutral-500">{selected.filename} · {formattedSize(selected.size_bytes)}</p>{selected.recipient && <p className="mt-1 break-all text-xs text-neutral-500">Email recipient: {selected.recipient}</p>}</div><div className="flex shrink-0 flex-wrap gap-2"><a className={button} href={cvUrl(selected.path)} target="_blank" rel="noopener noreferrer"><FileText className="h-4 w-4" />Open PDF</a><a className={primary} href={cvUrl(selected.path, true)} download={selected.filename}><Download className="h-4 w-4" />Download PDF</a></div></div>{selected.sent_verified && <p className="mt-3 flex items-center gap-2 text-xs text-emerald-700"><CheckCircle2 className="h-4 w-4" />This exact PDF was verified in the Zoho Sent copy.</p>}</div>
        <iframe title={`Preview ${selected.filename}`} src={cvUrl(selected.path)} className="h-[680px] w-full bg-neutral-100" />
      </article>}
    </div>}
  </section>;
}
