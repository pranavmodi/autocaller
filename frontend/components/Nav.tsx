"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, PhoneCall, Users, Stethoscope, Building2, CalendarClock, CalendarCheck, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { apiUrl } from "@/lib/api";

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
  { href: "/calls", label: "Calls", icon: PhoneCall },
  { href: "/pipeline", label: "Pipeline", icon: Users },
  { href: "/cadence", label: "Cadence", icon: CalendarClock },
  { href: "/consults", label: "Consults", icon: CalendarCheck },
  { href: "/firms", label: "Firms", icon: Building2 },
  { href: "/system", label: "Health", icon: Stethoscope },
];

export function Nav() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:fixed md:inset-y-0 md:left-0 md:flex md:w-56 md:flex-col md:border-r md:border-neutral-200 md:bg-white">
        <div className="flex h-14 items-center gap-2 border-b border-neutral-200 px-5">
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-sm font-semibold">Autocaller</span>
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
      <header className="sticky top-0 z-20 flex h-12 items-center justify-between border-b border-neutral-200 bg-white px-4 md:hidden">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-sm font-semibold">Autocaller</span>
        </div>
        <ConnectionBadge />
      </header>

      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 right-0 z-20 flex h-16 items-center justify-around border-t border-neutral-200 bg-white md:hidden">
        {items.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium",
              isActive(href) ? "text-neutral-900" : "text-neutral-500",
            )}
          >
            <Icon className="h-5 w-5" />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
