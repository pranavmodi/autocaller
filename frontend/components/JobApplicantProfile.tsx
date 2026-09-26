"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Save, Trash2, UserRound, X } from "lucide-react";
import { jobAgentRequest } from "@/lib/job-agent";

type Scope = "contextual" | "global" | "country" | "company" | "role" | "application";
type SavedAnswer = { id: string; revision: number; question: string; answer: string; scope: Scope; scope_value: string; updated_at: string; context: { firm_name?: string; title?: string; answered_at?: string } };
type Edit = { id?: string; revision: number; question: string; answer: string; scope: Scope; scope_value: string };
const empty: Edit = { revision: 0, question: "", answer: "", scope: "contextual", scope_value: "" };
const scopes: Record<Scope,string> = { contextual: "When the context fits", global: "All applications", country: "One country", company: "One company", role: "One role or role family", application: "This application only" };
const input = "mt-2 w-full rounded-lg border border-violet-200 bg-white p-3 text-sm";
const button = "inline-flex items-center justify-center gap-2 rounded-lg border border-violet-200 bg-white px-3 py-2 text-sm font-medium text-violet-900 disabled:opacity-50";

export function JobApplicantProfile({ compact = false }: { compact?: boolean }) {
  const client=useQueryClient();
  const [edit,setEdit]=useState<Edit|null>(null);
  const [search,setSearch]=useState("");
  const query=useQuery({queryKey:["job-agent","profile"],queryFn:()=>jobAgentRequest<{items:SavedAnswer[]}>("/profile")});
  const save=useMutation({mutationFn:(body:Edit)=>jobAgentRequest("/profile",body),onSuccess:()=>{setEdit(null);client.invalidateQueries({queryKey:["job-agent"]});}});
  const remove=useMutation({mutationFn:(item:SavedAnswer)=>jobAgentRequest(`/profile/${item.id}/remove`,{revision:item.revision}),onSuccess:()=>client.invalidateQueries({queryKey:["job-agent"]})});
  const error=query.error || save.error || remove.error;
  const items=query.data?.items.filter(item=>`${item.question} ${item.answer} ${item.scope_value}`.toLowerCase().includes(search.toLowerCase())) || [];
  return <section aria-label="Applicant profile" className={`overflow-hidden rounded-2xl border border-violet-200 bg-violet-50/40 ${compact ? "" : "max-w-5xl shadow-sm"}`}>
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-violet-200 bg-violet-100/70 p-5"><div className="min-w-0 basis-full sm:flex-1 sm:basis-0"><h2 className="flex items-center gap-2 font-semibold text-violet-950"><UserRound className="h-5 w-5 shrink-0" />Applicant profile</h2><p className="mt-2 text-sm leading-relaxed text-neutral-600">Answer once. The agent reuses saved information when it applies and asks only for missing or conflicting details.</p></div><button type="button" className={button} onClick={()=>{save.reset();setEdit({...empty});}}><Plus className="h-4 w-4" />Add information</button></header>
    <div className="space-y-4 p-5">
      <p className="text-xs leading-relaxed text-neutral-500">Current residence, relocation plans and work authorization stay separate. Salary answers retain their original role and country context. Removing an answer stops future reuse; past application records retain their history.</p>
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">{error.message}</div>}
      {edit && <form aria-label="Edit applicant information" onSubmit={e=>{e.preventDefault();save.mutate(edit);}} className="space-y-4 rounded-xl border border-violet-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between gap-2"><h3 className="font-semibold">{edit.id ? "Edit saved answer" : "Add reusable information"}</h3><button type="button" aria-label="Cancel profile edit" className="p-2" onClick={()=>setEdit(null)}><X className="h-4 w-4" /></button></div>
        <label className="block text-sm font-medium">Question or fact label<input aria-label="Profile question" className={input} required maxLength={8000} value={edit.question} onChange={e=>setEdit({...edit,question:e.target.value})} placeholder="Current home address, planned relocation, US sponsorship…" /></label>
        <label className="block text-sm font-medium">Your answer<textarea aria-label="Profile answer" className={`${input} min-h-28`} required maxLength={8000} value={edit.answer} onChange={e=>setEdit({...edit,answer:e.target.value})} placeholder="Include dates, currency and annual/hourly basis when relevant." /></label>
        <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm font-medium">Reuse scope<select aria-label="Profile reuse scope" className={input} value={edit.scope} onChange={e=>setEdit({...edit,scope:e.target.value as Scope,scope_value:""})}>{Object.entries(scopes).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>{!["global","contextual"].includes(edit.scope) && <label className="block text-sm font-medium">Applies to<input aria-label="Profile scope value" className={input} required maxLength={1000} value={edit.scope_value} onChange={e=>setEdit({...edit,scope_value:e.target.value})} placeholder={edit.scope==="country" ? "United States" : edit.scope==="role" ? "Senior AI engineering roles in the US" : "Company name or application ID"} /></label>}</div>
        <button type="submit" className="inline-flex items-center gap-2 rounded-lg bg-violet-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={save.isPending}><Save className="h-4 w-4" />{save.isPending ? "Saving…" : "Save to profile"}</button>
      </form>}
      {!!query.data?.items.length && <input aria-label="Search applicant profile" className={input} value={search} onChange={e=>setSearch(e.target.value)} placeholder="Find a saved answer…" />}
      {query.isPending && <p className="text-sm text-neutral-500">Loading saved answers…</p>}
      {!query.isPending && !items.length && <p className="rounded-xl border border-dashed border-violet-200 bg-white p-5 text-sm text-neutral-600">{search ? "No matching answers." : "Answers you give the application agent appear here automatically. You can also add your address, relocation plans and other facts now."}</p>}
      <div className="space-y-3">{items.map(item=><article key={item.id} className="rounded-xl border border-violet-100 bg-white p-4"><div className="flex items-start justify-between gap-3"><h3 className="min-w-0 break-words text-sm font-semibold text-neutral-900">{item.question}</h3><div className="flex shrink-0 gap-1"><button aria-label="Edit saved answer" type="button" className="rounded-lg p-2 text-violet-700 hover:bg-violet-50" onClick={()=>{save.reset();setEdit({id:item.id,revision:item.revision,question:item.question,answer:item.answer,scope:item.scope,scope_value:item.scope_value});}}><Pencil className="h-4 w-4" /></button><button aria-label="Remove saved answer" type="button" className="rounded-lg p-2 text-neutral-500 hover:bg-red-50 hover:text-red-700" disabled={remove.isPending} onClick={()=>remove.mutate(item)}><Trash2 className="h-4 w-4" /></button></div></div><p className="mt-2 whitespace-pre-wrap break-words text-sm text-neutral-700">{item.answer}</p><div className="mt-3 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-violet-50 px-2.5 py-1 text-violet-800">{scopes[item.scope]}{item.scope_value ? ` · ${item.scope_value}` : ""}</span><span className="py-1 text-neutral-400">Updated {new Date(item.updated_at).toLocaleDateString()}</span></div>{item.context.firm_name && <p className="mt-2 text-xs text-neutral-500">Originally answered for {item.context.firm_name}{item.context.title ? ` · ${item.context.title}` : ""}</p>}</article>)}</div>
    </div>
  </section>;
}
