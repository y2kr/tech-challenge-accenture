import { NextRequest, NextResponse } from "next/server";
import { sessionCookieName, verifySession } from "@/lib/auth";

const methodsWithBody = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const apiTimeoutMs = 120_000;

function allowedApiRequest(method: string, path: string[]) {
  const [resource, id, action, decision, extra] = path;
  if (extra !== undefined) return false;
  if (method === "GET" && resource === "studies" && id === undefined)
    return true;
  if (method === "POST" && resource === "sync" && id === undefined) return true;
  if (method === "GET" && resource === "changes" && id === undefined)
    return true;
  if (method === "GET" && resource === "changes" && /^\d+$/.test(id ?? "")) {
    return action === undefined;
  }
  if (resource === "changes" && /^\d+$/.test(id ?? "") && action === "draft") {
    return (
      ((method === "POST" || method === "PATCH") && decision === undefined) ||
      (method === "POST" && decision === "decision")
    );
  }
  return (
    method === "PATCH" &&
    resource === "actions" &&
    /^\d+$/.test(id ?? "") &&
    action === undefined
  );
}

function apiBaseUrl() {
  const value = process.env.API_BASE_URL;
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

function sameOrigin(request: NextRequest) {
  const origin = request.headers.get("origin");
  const host =
    request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

async function proxyApi(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  if (!verifySession(request.cookies.get(sessionCookieName)?.value)) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  if (methodsWithBody.has(request.method) && !sameOrigin(request)) {
    return NextResponse.json({ detail: "Forbidden" }, { status: 403 });
  }

  const base = apiBaseUrl();
  const token = process.env.API_ACCESS_TOKEN;
  if (!base || !token) {
    return NextResponse.json(
      { detail: "API proxy is not configured." },
      { status: 503 },
    );
  }

  const { path } = await context.params;
  if (!allowedApiRequest(request.method, path)) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  const target = new URL(
    `/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`,
    base,
  );
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("authorization", `Bearer ${token}`);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? null
          : request.body,
      duplex: "half",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(apiTimeoutMs),
    } as RequestInit & { duplex: "half" });
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          error instanceof DOMException && error.name === "TimeoutError"
            ? "API request timed out."
            : "The monitoring API could not be reached.",
      },
      {
        status:
          error instanceof DOMException && error.name === "TimeoutError"
            ? 504
            : 502,
      },
    );
  }

  const responseHeaders = new Headers();
  const upstreamContentType = upstream.headers.get("content-type");
  if (upstreamContentType)
    responseHeaders.set("content-type", upstreamContentType);
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyApi(request, context);
}

export function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyApi(request, context);
}

export function PATCH(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxyApi(request, context);
}

export function OPTIONS() {
  return new Response(null, {
    status: 204,
    headers: { Allow: "GET, POST, PATCH, OPTIONS" },
  });
}
