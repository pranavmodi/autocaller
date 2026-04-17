import { NextRequest, NextResponse } from "next/server";

/**
 * Redirect unauthenticated page requests to /login.
 *
 * Cookie presence is a loose check — the real validation lives on the
 * backend and API calls will 401 if the cookie is invalid or expired.
 * This middleware just prevents showing the dashboard shell to someone
 * who hasn't logged in yet.
 *
 * /api routes are proxied to the backend (with cookies), so we don't
 * gate them here — the backend's AuthMiddleware handles them.
 */

const SESSION_COOKIE = "ac_sess";

export function middleware(req: NextRequest) {
  const { pathname, searchParams } = req.nextUrl;

  // Public paths — no auth needed.
  if (
    pathname === "/login" ||
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/audio/") ||
    pathname === "/favicon.ico" ||
    pathname === "/robots.txt"
  ) {
    return NextResponse.next();
  }

  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    return NextResponse.next();
  }

  // Build the redirect URL from forwarded headers so we honor the public
  // hostname/scheme (nginx sets Host + X-Forwarded-Proto). `req.nextUrl`
  // uses the internal bind address (127.0.0.1:3099) when Next is behind
  // a proxy, which would leak `localhost:3099` into the Location header.
  const host = req.headers.get("host") ?? req.nextUrl.host;
  const proto = req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol.replace(":", "");
  const next = pathname + (searchParams.toString() ? `?${searchParams}` : "");
  const url = new URL(`${proto}://${host}/login`);
  if (next && next !== "/") {
    url.searchParams.set("next", next);
  }
  return NextResponse.redirect(url, 307);
}

export const config = {
  // Gate everything except static + the Next.js internals. API paths are
  // handled by the backend's own auth middleware.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
