import { env } from "cloudflare:workers";

type MatchEnvironment = { SPECTER2_ENDPOINT_URL?: string; SPECTER2_API_TOKEN?: string };

async function callGradioSpace(baseUrl: string, abstract: string, headers: Record<string, string>) {
  const endpoint = `${baseUrl.replace(/\/$/, "")}/gradio_api/call/match`;
  const queued = await fetch(endpoint, { method: "POST", headers, body: JSON.stringify({ data: [abstract] }) });
  if (!queued.ok) throw new Error(`SPECTER2 Space returned ${queued.status}`);
  const { event_id: eventId } = await queued.json() as { event_id?: string };
  if (!eventId) throw new Error("SPECTER2 Space did not return an event ID");
  const completed = await fetch(`${endpoint}/${encodeURIComponent(eventId)}`, {
    headers: runtimeHeaders(headers.authorization),
  });
  if (!completed.ok) throw new Error(`SPECTER2 Space result returned ${completed.status}`);
  const stream = await completed.text();
  const dataLines = stream.split(/\r?\n/).filter(line => line.startsWith("data: "));
  const last = dataLines.at(-1)?.slice(6);
  if (!last) throw new Error("SPECTER2 Space returned no result");
  const payload = JSON.parse(last) as unknown[];
  if (!payload[0] || typeof payload[0] !== "object") throw new Error("SPECTER2 Space returned an invalid result");
  return payload[0];
}

function runtimeHeaders(authorization?: string) {
  return authorization ? { authorization } : {};
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as { abstract?: unknown };
    const abstract = typeof body.abstract === "string" ? body.abstract.trim().slice(0, 6000) : "";
    if (abstract.length < 80) return Response.json({ error: "Please enter a fuller abstract (at least 80 characters)." }, { status: 400 });
    const runtime = env as unknown as MatchEnvironment;
    if (!runtime.SPECTER2_ENDPOINT_URL) return Response.json({ error: "Abstract matching is not configured yet. Add the SPECTER2 service URL to enable it." }, { status: 503 });
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (runtime.SPECTER2_API_TOKEN) headers.authorization = `Bearer ${runtime.SPECTER2_API_TOKEN}`;
    const endpoint = runtime.SPECTER2_ENDPOINT_URL;
    const matches = endpoint.includes(".hf.space")
      ? await callGradioSpace(endpoint, abstract, headers)
      : await (async () => {
          const upstream = await fetch(endpoint, { method: "POST", headers, body: JSON.stringify({ abstract }) });
          if (!upstream.ok) throw new Error(`SPECTER2 service returned ${upstream.status}`);
          return upstream.json();
        })();
    return Response.json(matches, { headers: { "cache-control": "no-store" } });
  } catch (error) {
    console.error("Abstract matching failed", error);
    return Response.json({ error: "The matching service is temporarily unavailable. Please try again." }, { status: 502 });
  }
}
