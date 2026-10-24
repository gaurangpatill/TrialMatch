import {afterEach, describe, expect, it, vi} from "vitest";

import {POST} from "../app/api/match/route";
import {GET} from "../app/api/trials/route";

describe("clinical API proxies", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("replaces malformed upstream errors with the shared sanitized envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("private backend diagnostic", {
        status: 500,
        headers: {"content-type": "text/plain"},
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://trialmatch.test/api/trials?query=cancer"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error.code).toBe("INVALID_UPSTREAM_RESPONSE");
    expect(body.error.retryable).toBe(true);
    expect(JSON.stringify(body)).not.toContain("private backend diagnostic");
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  it("preserves a valid shared upstream error envelope", async () => {
    const upstream = {
      error: {
        code: "VALIDATION_ERROR",
        message: "Request validation failed.",
        details: [{field: "page", reason: "must be at least 1"}],
        retryable: false,
        request_id: "request-1",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json(upstream, {status: 422})),
    );

    const response = await GET(new Request("http://trialmatch.test/api/trials?page=0"));

    expect(response.status).toBe(422);
    expect(await response.json()).toEqual(upstream);
  });

  it("sanitizes transport failures and forwards match requests", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("http://private-api:8000 failed")));
    const failed = await POST(
      new Request("http://trialmatch.test/api/match", {
        method: "POST",
        body: JSON.stringify({patient: {profile_id: "synthetic", synthetic: true}}),
      }),
    );
    const failedBody = await failed.json();
    expect(failed.status).toBe(503);
    expect(failedBody.error.retryable).toBe(true);
    expect(JSON.stringify(failedBody)).not.toContain("private-api");

    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        profile_id: "synthetic",
        results: [],
        disclaimer: "Preliminary screening only. Study staff must confirm eligibility.",
        generated_at: "2026-10-24T18:00:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const succeeded = await POST(
      new Request("http://trialmatch.test/api/match", {
        method: "POST",
        body: JSON.stringify({patient: {profile_id: "synthetic", synthetic: true}}),
      }),
    );
    expect(succeeded.status).toBe(200);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  it("rejects contract-invalid successful payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({diagnostic: "private success payload"})),
    );

    const response = await GET(new Request("http://trialmatch.test/api/trials"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error.code).toBe("INVALID_UPSTREAM_RESPONSE");
    expect(JSON.stringify(body)).not.toContain("private success payload");
  });

  it("rejects error envelopes carrying extra diagnostics", async () => {
    const upstream = {
      error: {
        code: "INTERNAL_ERROR",
        message: "Failed.",
        details: [],
        retryable: false,
        request_id: "request-2",
        stack: "private stack trace",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json(upstream, {status: 500})),
    );

    const response = await GET(new Request("http://trialmatch.test/api/trials"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body.error.code).toBe("INVALID_UPSTREAM_RESPONSE");
    expect(JSON.stringify(body)).not.toContain("private stack trace");
  });
});
