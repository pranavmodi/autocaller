"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { BellRing, ExternalLink, X } from "lucide-react";
import { getLatestEngagementCampaignActivity, type LatestEngagementCampaignActivity } from "@/lib/api";

export const ENGAGEMENT_DESKTOP_NOTIFICATIONS_KEY = "possibleos_engagement_desktop_notifications";
const SEEN_EVENTS_KEY = "possibleos_engagement_seen_events";

export function EngagementNotificationPopup() {
  const latest = useQuery({
    queryKey: ["engagement-campaign-activity-notifications"],
    queryFn: () => getLatestEngagementCampaignActivity({ sinceDays: 1, limit: 5, quality: "human" }),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });
  const [notification, setNotification] = useState<LatestEngagementCampaignActivity | null>(null);
  const initialized = useRef(false);

  useEffect(() => {
    const activities = latest.data?.activities ?? [];
    const saved = window.localStorage.getItem(SEEN_EVENTS_KEY);
    if (!initialized.current) {
      initialized.current = true;
      if (!saved) {
        window.localStorage.setItem(SEEN_EVENTS_KEY, JSON.stringify(activities.map((row) => row.id)));
        return;
      }
    }
    if (!activities.length) return;
    let seen: string[];
    try {
      seen = saved ? JSON.parse(saved) : [];
      if (!Array.isArray(seen)) seen = [];
    } catch {
      seen = [];
    }
    const seenSet = new Set(seen);
    const activity = activities.find((row) => !seenSet.has(row.id));
    window.localStorage.setItem(
      SEEN_EVENTS_KEY,
      JSON.stringify(Array.from(new Set([...activities.map((row) => row.id), ...seen])).slice(0, 100)),
    );
    if (!activity) return;
    const occurredAt = activity.occurred_at ? new Date(activity.occurred_at).getTime() : 0;
    if (!occurredAt || Date.now() - occurredAt > 10 * 60 * 1000) return;

    setNotification(activity);
    const desktopEnabled = window.localStorage.getItem(ENGAGEMENT_DESKTOP_NOTIFICATIONS_KEY) === "true";
    if (desktopEnabled && "Notification" in window && Notification.permission === "granted") {
      const desktop = new Notification(`${activity.contact_name} engaged`, {
        body: `${activity.campaign_name}: ${activity.label}`,
        tag: activity.id,
      });
      desktop.onclick = () => {
        window.focus();
        window.location.href = "/click-analytics";
        desktop.close();
      };
    }
  }, [latest.data]);

  if (!notification) return null;

  return (
    <div className="fixed right-3 top-3 z-[990] w-[calc(100vw_-_1.5rem)] max-w-sm rounded-lg border border-emerald-200 bg-white shadow-xl md:right-6 md:top-6">
      <div className="flex items-start gap-3 p-4">
        <span className="mt-0.5 rounded-full bg-emerald-100 p-2 text-emerald-700">
          <BellRing className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-neutral-950">{notification.contact_name} engaged</div>
          <div className="mt-1 text-xs leading-relaxed text-neutral-600">
            {notification.campaign_name} · {notification.label}
          </div>
          <div className="mt-3">
            <Link href="/click-analytics" onClick={() => setNotification(null)} className="inline-flex items-center gap-1.5 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-neutral-800">
              View engagement <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
        <button type="button" aria-label="Dismiss engagement notification" onClick={() => setNotification(null)} className="rounded-md p-1 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
