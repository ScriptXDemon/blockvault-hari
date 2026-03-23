import { apiRequest } from "@/lib/api";

export type RuntimeStatusResponse = {
  proof_boundary: string;
  zkpt_ready: boolean;
  zkpt_runtime: {
    ready: boolean;
    proofBoundary: string;
    proverBackend: string;
    artifact: {
      selectedProfile: string | null;
      profileClass: string | null;
      artifactVersion: string | null;
      proofBoundary: string | null;
      artifactsDir: string | null;
    };
    recentSingleProofBenchmark?: {
      sampleCount: number;
      medianProveMs: number;
      medianTotalMs: number;
      latestAt: string;
    } | null;
    preflightThresholds?: {
      singleProofTargetSeconds?: number;
      singleProofTimeoutSeconds?: number;
      multiShardTimeoutSeconds?: number;
      maxParallelShards?: number;
      maxSupportedShards?: number;
      directOnchainMaxShards?: number;
    };
    onchain?: {
      enabled: boolean;
      singleProofOnly: boolean;
      chainId: number;
      selectedProfile: string | null;
      rpcUrlConfigured: boolean;
      registryAddress: string | null;
      relayerConfigured: boolean;
      contractSourcePath: string | null;
      deploymentReady: boolean;
    };
    limits?: {
      proofTimeoutSeconds?: number;
      targetProofSeconds?: number;
      maxParallelShards?: number;
      singleProofTimeoutSeconds?: number;
      singleProofTargetSeconds?: number;
      multiShardTimeoutSeconds?: number;
    };
    warnings: string[];
    errors: string[];
  };
  redaction_runtime: {
    ready: boolean;
    effective_mode: string;
    preflight_thresholds?: {
      singleProofTargetSeconds?: number;
      singleProofTimeoutSeconds?: number;
      multiShardTimeoutSeconds?: number;
      maxParallelShards?: number;
      maxSupportedShards?: number;
      directOnchainMaxShards?: number;
    };
  };
};

export type RuntimeBanner = {
  tone: "warning" | "danger" | "success";
  summary: string;
  detail: string;
};

export async function fetchRuntimeStatus() {
  return apiRequest<RuntimeStatusResponse>("/status");
}

export function getRedactionPollingTimeoutMs(status?: RuntimeStatusResponse | null): number {
  const multiShardTimeoutSeconds =
    status?.zkpt_runtime.preflightThresholds?.multiShardTimeoutSeconds
    ?? status?.zkpt_runtime.limits?.multiShardTimeoutSeconds
    ?? status?.zkpt_runtime.limits?.proofTimeoutSeconds
    ?? 360;
  return Math.max((multiShardTimeoutSeconds + 120) * 1000, 8 * 60 * 1000);
}

export function getZkptRuntimeBanner(status: RuntimeStatusResponse): RuntimeBanner | null {
  const profile = status.zkpt_runtime.artifact.selectedProfile ?? "unknown";
  const profileClass = status.zkpt_runtime.artifact.profileClass ?? "unknown";
  const backend = status.zkpt_runtime.proverBackend;

  if (!status.zkpt_ready) {
    return {
      tone: "danger",
      summary: `ZKPT runtime is not authoritative-ready on profile ${profile}.`,
      detail: status.zkpt_runtime.errors[0] ?? "The active artifact profile cannot satisfy authoritative verification.",
    };
  }

  if (status.zkpt_runtime.warnings.length > 0) {
    return {
      tone: "warning",
      summary: `ZKPT profile ${profile} is active via ${backend}.`,
      detail: status.zkpt_runtime.warnings[0],
    };
  }

  const benchmarkMs = status.zkpt_runtime.recentSingleProofBenchmark?.medianTotalMs;
  const onchainReady = status.zkpt_runtime.onchain?.deploymentReady;
  return {
    tone: "success",
    summary: `Authoritative ZKPT is ready on profile ${profile}.`,
    detail: `Profile class ${profileClass}; backend ${backend}; boundary ${status.zkpt_runtime.artifact.proofBoundary ?? status.proof_boundary}; single-proof median ${benchmarkMs ? `${Math.round(benchmarkMs / 1000)}s` : "n/a"}; on-chain ${onchainReady ? "configured" : "not configured"}.`,
  };
}
