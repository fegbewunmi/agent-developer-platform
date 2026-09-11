import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { TOKEN_COOKIE } from "@/lib/api";

const BACKEND_URL = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

/**
 * A same-origin proxy so client components (evaluation-status polling, the
 * approve/reject/revoke buttons) can call the real backend without ever
 * holding the JWT in browser JS - the token lives only in the httpOnly
 * cookie, read here, server-side, and attached as the real Authorization
 * header. This is what lets the backend skip CORS entirely (every request
 * it sees is same-origin, from this Next.js server) while the frontend
 * still gets full interactivity.
 */
async function handle(request: NextRequest, path: string[]) {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  const search = request.nextUrl.search;
  const url = `${BACKEND_URL}/${path.join("/")}${search}`;

  const method = request.method;
  const hasBody = method !== "GET" && method !== "HEAD";
  const bodyText = hasBody ? await request.text() : undefined;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(hasBody ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: bodyText,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "The Orion API is unreachable." }, { status: 502 });
  }

  const text = await response.text();
  return new NextResponse(text, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function GET(request: NextRequest, ctx: RouteContext<"/api/proxy/[...path]">) {
  const { path } = await ctx.params;
  return handle(request, path);
}
export async function POST(request: NextRequest, ctx: RouteContext<"/api/proxy/[...path]">) {
  const { path } = await ctx.params;
  return handle(request, path);
}
