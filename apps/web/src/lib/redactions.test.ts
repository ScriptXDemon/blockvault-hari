import { beforeEach, describe, expect, it, vi } from "vitest";

const apiRequestMock = vi.fn();

vi.mock("./api", () => ({
  apiRequest: (...args: unknown[]) => apiRequestMock(...args),
}));

import { waitForRedactionResult } from "./redactions";

describe("waitForRedactionResult", () => {
  beforeEach(() => {
    apiRequestMock.mockReset();
  });

  it("returns the terminal redaction result when the job completes", async () => {
    apiRequestMock
      .mockResolvedValueOnce({ jobId: "redact_123", status: "completed", stage: "result_ready" })
      .mockResolvedValueOnce({
        documentId: "docr_123",
        verification_passed: true,
        zkpt: { status: "verified", error: null },
      });

    await expect(waitForRedactionResult("redact_123", { timeoutMs: 1_000 })).resolves.toMatchObject({
      documentId: "docr_123",
      verification_passed: true,
    });
  });

  it("surfaces a session-expired message when polling loses authentication", async () => {
    apiRequestMock
      .mockRejectedValueOnce(new Error("Authentication required"))
      .mockRejectedValueOnce(new Error("Session expired"));

    await expect(waitForRedactionResult("redact_123", { timeoutMs: 1_000 })).rejects.toThrow(
      /session expired while the redaction job was running/i,
    );
  });

  it("recovers from a transient polling failure and still returns the result", async () => {
    apiRequestMock
      .mockRejectedValueOnce(new Error("Network glitch"))
      .mockResolvedValueOnce({ jobId: "redact_123", status: "processing", stage: "proving" })
      .mockResolvedValueOnce({ jobId: "redact_123", status: "completed", stage: "result_ready" })
      .mockResolvedValueOnce({
        documentId: "docr_123",
        verification_passed: true,
        zkpt: { status: "verified", error: null },
      });

    await expect(waitForRedactionResult("redact_123", { timeoutMs: 4_000 })).resolves.toMatchObject({
      documentId: "docr_123",
      verification_passed: true,
    });
  });

  it("does not treat a transient auth error as expired when auth revalidation succeeds", async () => {
    apiRequestMock
      .mockRejectedValueOnce(new Error("Authentication required"))
      .mockResolvedValueOnce({ user: { walletAddress: "0x100" } })
      .mockResolvedValueOnce({ jobId: "redact_123", status: "processing", stage: "proving" })
      .mockResolvedValueOnce({ jobId: "redact_123", status: "completed", stage: "result_ready" })
      .mockResolvedValueOnce({
        documentId: "docr_123",
        verification_passed: true,
        zkpt: { status: "verified", error: null },
      });

    await expect(waitForRedactionResult("redact_123", { timeoutMs: 4_000 })).resolves.toMatchObject({
      documentId: "docr_123",
      verification_passed: true,
    });
  });
});
