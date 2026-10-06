"use client";

import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { BookmarkPlus, ExternalLink, Loader2, Save, Trash2 } from "lucide-react";

import {
  createQuickJobLink,
  deleteQuickJobLink,
  listQuickJobLinks,
} from "@/lib/api";

const fieldClass =
  "w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-400 focus:ring-2 focus:ring-neutral-100";

export default function QuickSavePage() {
  const queryClient = useQueryClient();
  const [companyName, setCompanyName] = useState("");
  const [jobUrl, setJobUrl] = useState("");
  const links = useQuery({
    queryKey: ["quick-job-links"],
    queryFn: () => listQuickJobLinks(),
  });
  const save = useMutation({
    mutationFn: createQuickJobLink,
    onSuccess: () => {
      setCompanyName("");
      setJobUrl("");
      queryClient.invalidateQueries({ queryKey: ["quick-job-links"] });
    },
  });
  const remove = useMutation({
    mutationFn: deleteQuickJobLink,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["quick-job-links"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({ company_name: companyName.trim(), job_url: jobUrl.trim() });
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header className="flex items-center gap-3 border-b border-neutral-200 pb-4">
        <BookmarkPlus className="h-5 w-5 text-emerald-700" />
        <div>
          <h1 className="text-lg font-semibold text-neutral-950">Quick Save</h1>
          <p className="text-xs text-neutral-500">Capture a company and job listing for later</p>
        </div>
        <span className="ml-auto text-xs tabular-nums text-neutral-400">
          {links.data?.count ?? 0} saved
        </span>
      </header>

      <form
        onSubmit={submit}
        className="grid gap-3 border-y border-neutral-200 bg-white py-4 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.5fr)_auto] sm:items-end"
      >
        <label className="block text-xs font-medium text-neutral-600">
          Company name
          <input
            required
            autoFocus
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            placeholder="Acme Legal"
            className={`${fieldClass} mt-1`}
          />
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          Job link
          <input
            required
            type="url"
            value={jobUrl}
            onChange={(event) => setJobUrl(event.target.value)}
            placeholder="https://company.com/careers/job"
            className={`${fieldClass} mt-1`}
          />
        </label>
        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save
        </button>
        {save.isError && (
          <p className="text-xs text-red-600 sm:col-span-3">
            {save.error.message.includes("job_link_already_saved")
              ? "That job link is already saved."
              : "Could not save this job link."}
          </p>
        )}
      </form>

      <section aria-label="Saved job links">
        <div className="divide-y divide-neutral-200 border-y border-neutral-200 bg-white">
          {links.isLoading && (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading saved links
            </div>
          )}
          {links.isError && (
            <div className="py-12 text-center text-sm text-red-600">Could not load saved links.</div>
          )}
          {links.data?.links.map((link) => {
            let host = link.job_url;
            try {
              host = new URL(link.job_url).hostname.replace(/^www\./, "");
            } catch {
              // The API validates URLs; retain the full value if legacy data is malformed.
            }
            return (
              <article key={link.id} className="flex min-w-0 items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <h2 className="truncate text-sm font-semibold text-neutral-900">{link.company_name}</h2>
                  <p className="mt-0.5 truncate text-xs text-neutral-500">
                    {host}
                    {link.created_at
                      ? ` · saved ${formatDistanceToNow(new Date(link.created_at), { addSuffix: true })}`
                      : ""}
                  </p>
                </div>
                <a
                  href={link.job_url}
                  target="_blank"
                  rel="noreferrer"
                  title="Open job listing"
                  aria-label={`Open job listing for ${link.company_name}`}
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-neutral-200 text-neutral-600 hover:bg-neutral-50 hover:text-neutral-950"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
                <button
                  type="button"
                  title="Delete saved link"
                  aria-label={`Delete saved link for ${link.company_name}`}
                  disabled={remove.isPending && remove.variables === link.id}
                  onClick={() => {
                    if (window.confirm(`Delete the saved job link for ${link.company_name}?`)) {
                      remove.mutate(link.id);
                    }
                  }}
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-neutral-200 text-neutral-500 hover:border-red-200 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </article>
            );
          })}
          {!links.isLoading && links.data?.links.length === 0 && (
            <div className="py-16 text-center text-sm text-neutral-500">
              No job links saved yet.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
