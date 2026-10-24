import {
  backendUrl,
  isStudyDetailResponse,
  unavailableResponse,
  upstreamResponse,
} from "../../../../lib/server-api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  {params}: {params: Promise<{nctId: string}>},
): Promise<Response> {
  try {
    const {nctId} = await params;
    const incoming = new URL(request.url);
    const upstream = backendUrl(`api/trials/${encodeURIComponent(nctId)}`);
    if (incoming.searchParams.get("refresh") === "true") {
      upstream.searchParams.set("refresh", "true");
    }
    const response = await fetch(upstream, {
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    return upstreamResponse(response, await response.text(), isStudyDetailResponse);
  } catch (error) {
    console.error("Clinical trial detail proxy failed", error);
    return unavailableResponse("Official study details are temporarily unavailable.");
  }
}
