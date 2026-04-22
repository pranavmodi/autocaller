"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { CalendarCheck, Clock, Mail, Phone } from "lucide-react";

import { getConsultBookings, type ConsultBooking } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Admin view for free consult bookings submitted via
 * getpossibleminds.com/consult. Populated by the public booking
 * endpoint; notifies the operator via Telnyx SMS on create.
 */
export default function ConsultsPage() {
  const q = useQuery({
    queryKey: ["consults"],
    queryFn: getConsultBookings,
    refetchInterval: 30_000,
  });

  const bookings = q.data?.bookings ?? [];
  const [upcoming, past] = useMemo(() => {
    const now = Date.now();
    const up: ConsultBooking[] = [];
    const ps: ConsultBooking[] = [];
    for (const b of bookings) {
      if (new Date(b.slot_start).getTime() >= now) up.push(b);
      else ps.push(b);
    }
    // Upcoming sorted ascending by slot; past already in created_at desc.
    up.sort(
      (a, b) =>
        new Date(a.slot_start).getTime() - new Date(b.slot_start).getTime(),
    );
    return [up, ps];
  }, [bookings]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <h1 className="text-xl font-semibold">Consult bookings</h1>
        <span className="text-xs text-neutral-500">
          {bookings.length} total · {upcoming.length} upcoming
        </span>
      </div>

      {q.isLoading && <p className="text-sm text-neutral-500">Loading…</p>}
      {q.isError && (
        <p className="text-sm text-rose-700">
          Couldn&apos;t load bookings: {(q.error as Error).message}
        </p>
      )}

      {!q.isLoading && bookings.length === 0 && (
        <div className="rounded-lg border border-dashed border-neutral-300 bg-white p-10 text-center">
          <CalendarCheck className="mx-auto h-8 w-8 text-neutral-400" />
          <p className="mt-2 text-sm text-neutral-600">
            No consult bookings yet. They&apos;ll appear here when someone books at{" "}
            <span className="font-mono">getpossibleminds.com/consult</span>.
          </p>
        </div>
      )}

      {upcoming.length > 0 && (
        <BookingList
          title="Upcoming"
          bookings={upcoming}
          emptyLabel="No upcoming slots."
          variant="upcoming"
        />
      )}
      {past.length > 0 && (
        <BookingList
          title="Past"
          bookings={past}
          emptyLabel="No past bookings."
          variant="past"
        />
      )}
    </div>
  );
}

function BookingList({
  title,
  bookings,
  variant,
}: {
  title: string;
  bookings: ConsultBooking[];
  emptyLabel: string;
  variant: "upcoming" | "past";
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
        {title}
      </h2>
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-xs uppercase text-neutral-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">When</th>
              <th className="px-4 py-2 text-left font-medium">Contact</th>
              <th className="px-4 py-2 text-left font-medium">Firm</th>
              <th className="px-4 py-2 text-left font-medium">Notes</th>
              <th className="px-4 py-2 text-left font-medium">Booked</th>
            </tr>
          </thead>
          <tbody>
            {bookings.map((b) => (
              <BookingRow key={b.id} b={b} variant={variant} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function BookingRow({
  b,
  variant,
}: {
  b: ConsultBooking;
  variant: "upcoming" | "past";
}) {
  const slot = new Date(b.slot_start);
  const dateFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const timeFmt = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <tr
      className={cn(
        "border-t border-neutral-100 align-top",
        variant === "upcoming" ? "bg-white" : "bg-neutral-50/50",
      )}
    >
      <td className="whitespace-nowrap px-4 py-3">
        <div className="font-medium text-neutral-900">
          {dateFmt.format(slot)}
        </div>
        <div className="mt-0.5 flex items-center gap-1 text-xs text-neutral-600">
          <Clock className="h-3 w-3" />
          {timeFmt.format(slot)}
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="font-medium text-neutral-900">{b.name}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-neutral-600">
          <Mail className="h-3 w-3" />
          <a
            href={`mailto:${b.email}`}
            className="text-neutral-700 underline-offset-2 hover:underline"
          >
            {b.email}
          </a>
        </div>
        {b.phone && (
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-neutral-600">
            <Phone className="h-3 w-3" />
            <a
              href={`tel:${b.phone}`}
              className="text-neutral-700 underline-offset-2 hover:underline"
            >
              {b.phone}
            </a>
          </div>
        )}
      </td>
      <td className="px-4 py-3 text-neutral-700">{b.firm_name || "—"}</td>
      <td className="max-w-xs px-4 py-3 text-neutral-700">
        {b.notes ? (
          <span className="line-clamp-3 whitespace-pre-wrap">{b.notes}</span>
        ) : (
          <span className="text-neutral-400">—</span>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-xs text-neutral-500">
        {formatDistanceToNow(new Date(b.created_at), { addSuffix: true })}
      </td>
    </tr>
  );
}
