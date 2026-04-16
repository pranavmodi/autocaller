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

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  // Remember where the user wanted to go, so we can bounce back after login.
  const next = pathname + (searchParams.toString() ? `?${searchParams}` : "");
  if (next && next !== "/") url.searchParams.set("next", next);
  return NextResponse.redirect(url);
}

export const config = {
  // Gate everything except static + the Next.js internals. API paths are
  // handled by the backend's own auth middleware.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
