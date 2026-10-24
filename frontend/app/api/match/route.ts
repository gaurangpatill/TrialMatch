import {
  backendUrl,
  isMatchResponse,
  unavailableResponse,
  upstreamResponse,
} from "../../../lib/server-api";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.text();
    const response = await fetch(backendUrl("api/match"), {
      method: "POST",
      headers: {"content-type": "application/json"},
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    return upstreamResponse(response, await response.text(), isMatchResponse);
  } catch (error) {
    console.error("Preliminary matching proxy failed", error);
    return unavailableResponse("Preliminary matching is temporarily unavailable.");
  }
}
