from __future__ import annotations

from typing import Any

from .config import get_settings
from .zkpt_policy import record_zkpt_benchmark
from .zkpt_probe import run_zkpt_probe
from .zkpt_runtime import reset_zkpt_runtime_cache


def analyze_probe_report(
    report: dict[str, Any],
    *,
    target_proof_seconds: int,
) -> dict[str, Any]:
    probe = report.get("probe") or {}
    timings = probe.get("timings") or {}
    runtime = report.get("runtime") or {}
    artifact = report.get("artifact") or {}

    prove_ms = float(timings.get("prove_ms") or 0.0)
    witness_ms = float(timings.get("witness_ms") or 0.0)
    verify_ms = float(timings.get("verify_ms") or 0.0)
    total_ms = float(timings.get("total_ms") or 0.0)
    target_ms = float(target_proof_seconds * 1000)
    selected_profile = str((artifact or {}).get("profileId") or "unknown")
    source_present = bool((runtime.get("artifact") or {}).get("circuitSourcePresent"))

    if prove_ms >= max(witness_ms, verify_ms):
        bottleneck = "prove"
    elif witness_ms >= verify_ms:
        bottleneck = "witness"
    else:
        bottleneck = "verify"

    over_target = total_ms > target_ms if total_ms > 0 else False
    next_step = None
    if not source_present:
        next_step = "recover-circuit-source"
    elif bottleneck == "prove" and over_target:
        next_step = "generate-smaller-authoritative-profile"
    elif bottleneck == "witness" and over_target:
        next_step = "optimize-witness-runtime"
    else:
        next_step = "keep-current-profile"

    return {
        "targetProofSeconds": target_proof_seconds,
        "selectedProfile": selected_profile,
        "status": probe.get("status"),
        "overTarget": over_target,
        "bottleneck": bottleneck,
        "circuitSourcePresent": source_present,
        "timings": {
            "projectionMs": float(timings.get("projection_ms") or 0.0),
            "witnessMs": witness_ms,
            "proveMs": prove_ms,
            "verifyMs": verify_ms,
            "totalMs": total_ms,
        },
        "nextStep": next_step,
        "recommendations": _build_benchmark_recommendations(
            probe=probe,
            runtime=runtime,
            artifact=artifact,
            over_target=over_target,
            bottleneck=bottleneck,
            source_present=source_present,
            target_proof_seconds=target_proof_seconds,
        ),
    }


def _build_benchmark_recommendations(
    *,
    probe: dict[str, Any],
    runtime: dict[str, Any],
    artifact: dict[str, Any],
    over_target: bool,
    bottleneck: str,
    source_present: bool,
    target_proof_seconds: int,
) -> list[str]:
    recommendations: list[str] = []
    prove_ms = float((probe.get("timings") or {}).get("prove_ms") or 0.0)
    total_ms = float((probe.get("timings") or {}).get("total_ms") or 0.0)
    zkey_gib = (runtime.get("artifact") or {}).get("zkeyGiB")

    if not source_present:
        recommendations.append(
            "Recover the Circom source and ceremony scripts for this profile before attempting any smaller authoritative PLONK artifact."
        )
    if over_target and bottleneck == "prove":
        recommendations.append(
            f"Current total runtime is {round(total_ms / 1000, 3)}s against a {target_proof_seconds}s target; proving dominates the budget."
        )
        if zkey_gib:
            recommendations.append(
                f"The active PLONK zkey is {zkey_gib} GiB; keep it as the baseline profile and generate a smaller authoritative profile for the same proof boundary."
            )
        recommendations.append(
            "Do not spend more time on witness-path tuning first; the benchmark shows witness generation is not the bottleneck."
        )
    if probe.get("status") == "verified" and not over_target:
        recommendations.append("The current authoritative profile already fits the target budget.")
    if probe.get("status") != "verified":
        recommendations.append("Keep fail-closed semantics while benchmarking; never treat a timeout or runtime error as verified proof success.")
    if artifact:
        recommendations.append(
            f"Benchmark future candidate profiles against the same proof boundary using the current '{artifact.get('profileId')}' profile as the baseline."
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for item in recommendations:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def run_zkpt_benchmark(
    *,
    source_text: str | None = None,
    search_terms: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    probe_report = run_zkpt_probe(source_text=source_text, search_terms=search_terms)
    benchmark = analyze_probe_report(
        probe_report,
        target_proof_seconds=settings.zkpt_target_proof_seconds,
    )
    _record_probe_benchmark(probe_report, benchmark)
    return {
        **probe_report,
        "benchmark": benchmark,
    }


def _record_probe_benchmark(report: dict[str, Any], benchmark: dict[str, Any]) -> None:
    probe = report.get("probe") or {}
    artifact = report.get("artifact") or {}
    timings = probe.get("timings") or {}
    total_shards = int(probe.get("totalShards") or 0)
    if str(probe.get("status")) != "verified" or total_shards <= 0:
        return

    record_zkpt_benchmark(
        profile_id=str(artifact.get("profileId") or "unknown"),
        artifact_version=str(artifact.get("artifactVersion") or artifact.get("profileId") or "unknown"),
        total_shards=total_shards,
        classification="single_proof_ready" if total_shards == 1 else "verified_bundle_only",
        status=str(probe.get("status")),
        source_text_mode="direct_pdf",
        onchain_eligible=bool(total_shards == 1 and not benchmark.get("overTarget")),
        predicted_proof_ms=float((benchmark.get("timings") or {}).get("totalMs") or timings.get("total_ms") or 0.0),
        prove_ms=float(timings.get("prove_ms") or 0.0),
        total_ms=float(timings.get("total_ms") or 0.0),
    )
    reset_zkpt_runtime_cache()
