import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, request } from "../src/api/client.ts";

test("API client exposes the real HTTP status and backend detail", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    JSON.stringify({ detail: "Resume evidence is insufficient for review" }),
    {
      status: 422,
      headers: { "Content-Type": "application/json" },
    },
  );

  try {
    await assert.rejects(
      request("/resume-versions/1/review", { method: "POST" }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, 422);
        assert.equal(
          error.message,
          "Resume evidence is insufficient for review",
        );
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
