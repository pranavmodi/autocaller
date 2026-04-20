import { apiUrl } from "./api";

export interface CadenceEntry {
  id: string;
  pif_id: string;
  firm_name: string;
  cadence_stage: string;
  stage_entered_at: string | null;
  next_action: string | null;
  next_action_due: string | null;
  owner: string | null;
  outcome: string;
  call_ids: string[];
  contacts_tried: Array<{ name: string; phone: string; title?: string }>;
  available_contacts: Array<{
    name: string;
    title: string;
    phone: string;
    email: string | null;
    source: string;
  }>;
  intel: Record<string, unknown>;
  icp_tier: string | null;
  icp_score: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CadenceStats {
  by_stage: Record<string, number>;
  by_outcome: Record<string, number>;
  actions_due_today: number;
  overdue: number;
  total_active: number;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), { credentials: "include" });
  if (!res.ok) throw new Error(`GET ${path} ${res.status}`);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (!res.ok) throw new Error(`PUT ${path} ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  if (!res.ok) throw new Error(`POST ${path} ${res.status}`);
  return res.json();
}

export const listCadence = (params?: {
  stage?: string;
  owner?: string;
  outcome?: string;
  due_today?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.stage) qs.set("stage", params.stage);
  if (params?.owner) qs.set("owner", params.owner);
  if (params?.outcome) qs.set("outcome", params.outcome);
  if (params?.due_today) qs.set("due_today", "true");
  if (params?.search) qs.set("search", params.search);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  return get<{ items: CadenceEntry[]; total: number }>(
    `/api/cadence?${qs}`
  );
};

export const getCadenceStats = () => get<CadenceStats>("/api/cadence/stats");

export const updateCadence = (id: string, action: string, note?: string) =>
  put<CadenceEntry>(`/api/cadence/${id}`, { action, note });

export const refreshCadence = () =>
  post<{ status: string; new: number; advanced: number }>("/api/cadence/refresh");

export const cadenceCall = (entryId: string, contact: {
  name: string;
  phone: string;
  title?: string;
  email?: string | null;
  persona?: string;
}) =>
  post<{ call_id: string; patient_id: string }>(`/api/cadence/${entryId}/call`, contact);
