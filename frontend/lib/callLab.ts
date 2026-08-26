import { apiUrl } from "@/lib/api";
import type { CallLog } from "@/types";

export type CallLabContact = {
  id: string;
  pif_id: string;
  name: string;
  title: string;
  role_category: string;
  firm_name: string;
  phone: string;
  email: string | null;
  linkedin: string | null;
  source: string;
  is_decision_maker: boolean;
  website: string | null;
};

export type CallLabLeader = {
  name: string;
  title: string;
  email: string | null;
  phone: string | null;
  linkedin: string | null;
};

export type CallLabTechnology = {
  key: string;
  label: string;
  source: string;
  confidence: string | number | null;
};

export type CallLabFirm = {
  pif_id: string;
  firm_name: string;
  website: string | null;
  metro: string | null;
  team_size: number;
  team_size_label: string;
  team_size_basis: string;
  icp_score: number | null;
  icp_tier: string | null;
  summary: string | null;
  practice_areas: string[];
  conversation_count: number;
  monthly_email_volume: number | null;
  primary_pain_point: string | null;
  target_contact: CallLabContact;
  founders: CallLabLeader[];
  leadership: CallLabLeader[];
  technology: CallLabTechnology[];
};

export type CallLabFirmsResponse = {
  items: CallLabFirm[];
  total: number;
  curated_total: number;
  vendor: "filevine";
  size_min: number;
  size_max: number;
  limit: number;
};

async function responseError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {}
  return `${response.status} ${response.statusText}`.trim();
}

export async function getCallLabFirms(args: {
  query?: string;
  limit?: number;
} = {}): Promise<CallLabFirmsResponse> {
  const params = new URLSearchParams({
    q: args.query ?? "",
    limit: String(args.limit ?? 50),
  });
  const response = await fetch(apiUrl(`/api/call-lab/firms?${params}`), {
    credentials: "include",
  });
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
}

export async function startCallLabCall(contact: CallLabContact): Promise<{
  call: CallLog;
  contact: CallLabContact;
}> {
  const response = await fetch(apiUrl("/api/call-lab/calls"), {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ pif_id: contact.pif_id, contact_id: contact.id }),
  });
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
}
