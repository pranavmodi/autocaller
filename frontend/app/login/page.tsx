"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiUrl } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // If the user landed on /login while already authenticated, skip past.
    (async () => {
      try {
        const res = await fetch(apiUrl("/api/auth/me"), {
          credentials: "include",
        });
        if (res.ok) {
          const d = await res.json();
          if (d?.authenticated) router.replace(next);
        }
      } catch {
        /* network blip — leave the form up */
      }
    })();
  }, [router, next]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(apiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
        credentials: "include",
      });
      if (!res.ok) {
        if (res.status === 401) setError("Wrong password.");
        else setError(`Login failed (${res.status}).`);
        setLoading(false);
        return;
      }
      // Hard navigate so middleware re-runs with the new cookie.
      window.location.href = next;
    } catch {
      setError("Network error. Try again.");
      setLoading(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="w-full max-w-sm rounded-lg border border-neutral-200 bg-white p-6 shadow-sm"
    >
      <h1 className="text-lg font-semibold text-neutral-900">Autocaller</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Operator login required.
      </p>
      <label className="mt-5 block text-xs font-medium text-neutral-600">
        Password
      </label>
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoFocus
        autoComplete="current-password"
        className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm outline-none focus:border-neutral-500"
      />
      {error && (
        <p className="mt-2 text-xs text-rose-600">{error}</p>
      )}
      <button
        type="submit"
        disabled={loading || !password}
        className="mt-5 w-full rounded bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <Suspense fallback={<div className="text-sm text-neutral-500">Loading…</div>}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
