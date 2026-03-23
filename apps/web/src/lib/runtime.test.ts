import { getRedactionPollingTimeoutMs, getZkptRuntimeBanner, type RuntimeStatusResponse } from "./runtime";

function makeStatus(overrides?: Partial<RuntimeStatusResponse["zkpt_runtime"]>): RuntimeStatusResponse {
  return {
    proof_boundary: "canonical_segment_mask_v1",
    zkpt_ready: true,
    zkpt_runtime: {
      ready: true,
      proofBoundary: "canonical_segment_mask_v1",
      proverBackend: "snarkjs_fullprove",
      artifact: {
        selectedProfile: "v2",
        profileClass: "authoritative",
        artifactVersion: "v2",
        proofBoundary: "canonical_segment_mask_v1",
        artifactsDir: "circuits/zkpt/v2",
      },
      recentSingleProofBenchmark: null,
      preflightThresholds: {
        singleProofTargetSeconds: 90,
        singleProofTimeoutSeconds: 180,
        multiShardTimeoutSeconds: 900,
        maxParallelShards: 2,
        maxSupportedShards: 8,
        directOnchainMaxShards: 1,
      },
      onchain: {
        enabled: false,
        singleProofOnly: true,
        chainId: 11155111,
        selectedProfile: "v2",
        rpcUrlConfigured: false,
        registryAddress: null,
        relayerConfigured: false,
        contractSourcePath: null,
        deploymentReady: false,
      },
      warnings: [],
      errors: [],
      ...overrides,
    },
    redaction_runtime: {
      ready: true,
      effective_mode: "inline_fallback",
      preflight_thresholds: {
        singleProofTargetSeconds: 90,
      },
    },
  };
}

describe("getZkptRuntimeBanner", () => {
  it("returns a danger banner when zkpt is not ready", () => {
    const banner = getZkptRuntimeBanner({
      ...makeStatus({
        ready: false,
        errors: ["Selected profile is not authoritative"],
      }),
      zkpt_ready: false,
    });

    expect(banner?.tone).toBe("danger");
    expect(banner?.detail).toMatch(/not authoritative/i);
  });

  it("returns a warning banner when runtime has warnings", () => {
    const banner = getZkptRuntimeBanner(
      makeStatus({
        warnings: ["Configured proof timeout is aggressive for the selected profile"],
      }),
    );

    expect(banner?.tone).toBe("warning");
    expect(banner?.summary).toMatch(/profile v2/i);
  });

  it("returns a success banner when authoritative runtime is ready", () => {
    const banner = getZkptRuntimeBanner(makeStatus());

    expect(banner?.tone).toBe("success");
    expect(banner?.detail).toMatch(/authoritative/i);
  });

  it("derives a polling timeout that exceeds the backend proof limit", () => {
    const timeoutMs = getRedactionPollingTimeoutMs(makeStatus({
      limits: {
        proofTimeoutSeconds: 360,
        multiShardTimeoutSeconds: 900,
      },
    }));

    expect(timeoutMs).toBeGreaterThan(900_000);
  });
});
