"use client";

import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  BookmarkPlus,
  BriefcaseBusiness,
  ExternalLink,
  Globe2,
  Loader2,
  Save,
  Trash2,
} from "lucide-react";

import {
  createQuickJobLink,
  deleteQuickJobLink,
  listQuickJobLinks,
  type QuickJobLink,
} from "@/lib/api";

type LinkType = "job" | "portal";

const fieldClass =
  "w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-400 focus:ring-2 focus:ring-neutral-100";

const sectionCopy = {
  job: {
    title: "Job links",
    description: "Individual roles to review or apply for later",
    nameLabel: "Company name",
    namePlaceholder: "Acme Legal",
    urlLabel: "Job link",
    urlPlaceholder: "https://company.com/careers/job",
    empty: "No job links saved yet.",
    icon: BriefcaseBusiness,
  },
  portal: {
    title: "Job portals",
    description: "Career pages and search portals worth checking again",
    nameLabel: "Portal name",
    namePlaceholder: "Company careers or job board",
    urlLabel: "Portal link",
    urlPlaceholder: "https://company.com/careers",
    empty: "No job portals saved yet.",
    icon: Globe2,
  },
} as const;

export default function QuickSavePage() {
  const jobs = useQuery({
    queryKey: ["quick-job-links", "job"],
    queryFn: () => listQuickJobLinks("job"),
  });
  const portals = useQuery({
    queryKey: ["quick-job-links", "portal"],
    queryFn: () => listQuickJobLinks("portal"),
  });

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="flex items-center gap-3 border-b border-neutral-200 pb-4">
        <BookmarkPlus className="h-5 w-5 text-emerald-700" />
        <div>
          <h1 className="text-lg font-semibold text-neutral-950">Quick Save</h1>
          <p className="text-xs text-neutral-500">Keep job opportunities and useful portals in one place</p>
        </div>
        <span className="ml-auto text-xs tabular-nums text-neutral-400">
          {(jobs.data?.count ?? 0) + (portals.data?.count ?? 0)} saved
        </span>
      </header>

      <SaveSection linkType="job" links={jobs.data?.links} loading={jobs.isLoading} failed={jobs.isError} />
      <SaveSection linkType="portal" links={portals.data?.links} loading={portals.isLoading} failed={portals.isError} />
    </div>
  );
}

function SaveSection({
  linkType,
  links,
  loading,
  failed,
}: {
  linkType: LinkType;
  links?: QuickJobLink[];
  loading: boolean;
  failed: boolean;
}) {
  const copy = sectionCopy[linkType];
  const Icon = copy.icon;
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const save = useMutation({
    mutationFn: createQuickJobLink,
    onSuccess: () => {
      setName("");
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["quick-job-links"] });
    },
  });
  const remove = useMutation({
    mutationFn: deleteQuickJobLink,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["quick-job-links"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({ company_name: name.trim(), job_url: url.trim(), link_type: linkType });
  }

  return (
    <section aria-labelledby={`${linkType}-links-heading`}>
      <div className="mb-3 flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-neutral-100 text-neutral-700">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <h2 id={`${linkType}-links-heading`} className="text-sm font-semibold text-neutral-950">
            {copy.title}
          </h2>
          <p className="text-xs text-neutral-500">{copy.description}</p>
        </div>
        <span className="ml-auto text-xs tabular-nums text-neutral-400">{links?.length ?? 0}</span>
      </div>

      <form
        onSubmit={submit}
        className="grid gap-3 border-y border-neutral-200 bg-white py-4 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.5fr)_auto] sm:items-end"
      >
        <label className="block text-xs font-medium text-neutral-600">
          {copy.nameLabel}
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={copy.namePlaceholder}
            className={`${fieldClass} mt-1`}
          />
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          {copy.urlLabel}
          <input
            required
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder={copy.urlPlaceholder}
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
              ? "That link is already saved."
              : "Could not save this link."}
          </p>
        )}
      </form>

      <div className="divide-y divide-neutral-200 border-b border-neutral-200 bg-white">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading saved links
          </div>
        )}
        {failed && <div className="py-10 text-center text-sm text-red-600">Could not load saved links.</div>}
        {links?.map((link) => (
          <SavedLinkRow
            key={link.id}
            link={link}
            deleting={remove.isPending && remove.variables === link.id}
            onDelete={() => {
              if (window.confirm(`Delete the saved link for ${link.company_name}?`)) {
                remove.mutate(link.id);
              }
            }}
          />
        ))}
        {!loading && !failed && links?.length === 0 && (
          <div className="py-12 text-center text-sm text-neutral-500">{copy.empty}</div>
        )}
      </div>
    </section>
  );
}

function SavedLinkRow({
  link,
  deleting,
  onDelete,
}: {
  link: QuickJobLink;
  deleting: boolean;
  onDelete: () => void;
}) {
  let host = link.job_url;
  try {
    host = new URL(link.job_url).hostname.replace(/^www\./, "");
  } catch {
    // The API validates URLs; retain the full value if legacy data is malformed.
  }

  return (
    <article className="flex min-w-0 items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-semibold text-neutral-900">{link.company_name}</h3>
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
        title="Open saved link"
        aria-label={`Open saved link for ${link.company_name}`}
        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-neutral-200 text-neutral-600 hover:bg-neutral-50 hover:text-neutral-950"
      >
        <ExternalLink className="h-4 w-4" />
      </a>
      <button
        type="button"
        title="Delete saved link"
        aria-label={`Delete saved link for ${link.company_name}`}
        disabled={deleting}
        onClick={onDelete}
        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-neutral-200 text-neutral-500 hover:border-red-200 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </article>
  );
}
