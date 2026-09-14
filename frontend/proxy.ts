import { NextRequest, NextResponse } from "next/server";

const TOKEN_COOKIE = "orion_token";
// /api/auth/quick-switch is safe to leave unauthenticated here - the route
// itself 404s unless QUICK_SWITCH_ENABLED is set (see that route's own
// docstring), and it needs to be reachable from the login page itself so a
// tester isn't locked out with no session and no known password.
const PUBLIC_PATHS = ["/login", "/api/auth/login", "/api/auth/quick-switch"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p)) || pathname.startsWith("/_next")) {
    return NextResponse.next();
  }

  const token = request.cookies.get(TOKEN_COOKIE)?.value;
  if (!token) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
