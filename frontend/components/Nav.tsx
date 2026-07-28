"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  BrainCircuit,
  Bot,
  Building2,
  CalendarCheck,
  Database,
  FlaskConical,
  GitBranch,
  Grid3x3,
  Inbox,
  ListChecks,
  Lightbulb,
  LogOut,
  Mail,
  Menu,
  MessageSquare,
  PhoneCall,
  Radar,
  SearchCheck,
  Send,
  Stethoscope,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { apiUrl } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

async function signOut() {
  try {
    await fetch(apiUrl("/api/auth/logout"), {
      method: "POST",
      credentials: "include",
    });
  } catch {
    /* ignore — we'll bounce to /login anyway */
  }
  window.location.href = "/login";
}

const items = [
  { href: "/", label: "Now", icon: Activity },
  { href: "/actions", label: "Actions", icon: Inbox },
  { href: "/todos", label: "Todos", icon: ListChecks },
  { href: "/ideas", label: "Ideas", icon: Lightbulb },
  { href: "/cadence", label: "Queue", icon: ListChecks },
  { href: "/calls", label: "Calls", icon: PhoneCall },
  { href: "/comms", label: "Comms", icon: MessageSquare },
  { href: "/sequences", label: "Sequences", icon: Mail },
  { href: "/lead-gen", label: "Lead Gen", icon: BrainCircuit },
  { href: "/click-analytics", label: "Workflow Clicks", icon: BarChart3 },
  { href: "/data-returned", label: "Data Returned", icon: Database },
  { href: "/front", label: "Front", icon: Radar },
  { href: "/frontUI", label: "frontUI", icon: Inbox },
  { href: "/composer-ab", label: "Composer A/B", icon: FlaskConical },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/traces", label: "Traces", icon: GitBranch },
  { href: "/seo", label: "SEO", icon: SearchCheck },
  { href: "/outreach", label: "Outreach", icon: Send },
  { href: "/calllists", label: "Call lists", icon: ListChecks },
  { href: "/consults", label: "Consults", icon: CalendarCheck },
  { href: "/leads", label: "Leads", icon: Building2 },
  { href: "/system", label: "Health", icon: Stethoscope },
];

const mobilePrimaryHrefs = ["/", "/actions", "/todos", "/calls"];

export function Nav() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);
  const mobilePrimaryItems = useMemo(
    () => items.filter((item) => mobilePrimaryHrefs.includes(item.href)),
    [],
  );
  const mobileMoreItems = useMemo(
    () => items.filter((item) => !mobilePrimaryHrefs.includes(item.href)),
    [],
  );
  const moreActive = mobileMoreItems.some((item) => isActive(item.href));

  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:fixed md:inset-y-0 md:left-0 md:flex md:w-56 md:flex-col md:border-r md:border-neutral-200 md:bg-white">
        <div className="flex h-14 items-center gap-2 border-b border-neutral-200 px-5">
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-sm font-semibold">Possible OS</span>
          <span className="ml-auto">
            <ConnectionBadge />
          </span>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {items.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive(href)
                  ? "bg-neutral-900 text-white"
                  : "text-neutral-600 hover:bg-neutral-100",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>
        <button
          type="button"
          onClick={signOut}
          className="mx-3 mb-2 flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-neutral-600 hover:bg-neutral-100"
        >
          <LogOut className="h-3.5 w-3.5" />
          Sign out
        </button>
        <div className="border-t border-neutral-200 px-5 py-3 text-xs text-neutral-500">
          Possible Minds
        </div>
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-20 flex h-12 items-center justify-between border-b border-neutral-200 bg-white/95 px-3 backdrop-blur md:hidden">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-sm font-semibold">Possible OS</span>
        </div>
        <div className="flex items-center gap-2">
          <ConnectionBadge />
          <Dialog open={moreOpen} onOpenChange={setMoreOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-neutral-200 bg-white text-neutral-700 shadow-sm"
                aria-label="Open navigation"
              >
                <Menu className="h-4 w-4" />
              </button>
            </DialogTrigger>
            <DialogContent className="bottom-0 left-0 top-auto max-h-[88dvh] w-full max-w-none translate-x-0 translate-y-0 rounded-t-2xl border-x-0 border-b-0 p-0 sm:left-[50%] sm:max-w-lg sm:translate-x-[-50%] sm:rounded-2xl">
              <div className="border-b border-neutral-200 px-4 py-3 pr-12">
                <div>
                  <DialogTitle className="text-base">Possible OS</DialogTitle>
                  <DialogDescription className="mt-0.5 text-xs">
                    Navigation
                  </DialogDescription>
                </div>
              </div>
              <nav className="grid max-h-[calc(88dvh_-_8.5rem)] grid-cols-2 gap-2 overflow-y-auto px-3 py-3">
                {mobileMoreItems.map(({ href, label, icon: Icon }) => (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      "flex min-h-12 items-center gap-3 rounded-lg border px-3 py-2 text-sm font-medium",
                      isActive(href)
                        ? "border-neutral-900 bg-neutral-900 text-white"
                        : "border-neutral-200 bg-white text-neutral-700",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{label}</span>
                  </Link>
                ))}
              </nav>
              <div className="border-t border-neutral-200 px-3 pb-[calc(0.75rem_+_env(safe-area-inset-bottom))] pt-3">
                <button
                  type="button"
                  onClick={signOut}
                  className="flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-neutral-200 bg-white text-sm font-medium text-neutral-700"
                >
                  <LogOut className="h-4 w-4" />
                  Sign out
                </button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </header>

      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 right-0 z-20 grid grid-cols-5 border-t border-neutral-200 bg-white/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-10px_30px_rgba(15,23,42,0.08)] backdrop-blur md:hidden">
        {mobilePrimaryItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex h-16 flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
              isActive(href) ? "text-neutral-900" : "text-neutral-500",
            )}
          >
            <Icon className="h-5 w-5" />
            <span className="max-w-full truncate px-1">{label}</span>
          </Link>
        ))}
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          className={cn(
            "flex h-16 flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
            moreActive ? "text-neutral-900" : "text-neutral-500",
          )}
          aria-label="Open more navigation"
        >
          <Grid3x3 className="h-5 w-5" />
          <span>More</span>
        </button>
      </nav>
    </>
  );
}
