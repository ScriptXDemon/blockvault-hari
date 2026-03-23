from __future__ import annotations

from blockvault_api.zkpt_benchmark import analyze_probe_report
from blockvault_api.zkpt_benchmark import run_zkpt_benchmark


def test_analyze_probe_report_flags_missing_circuit_source_as_gate():
    report = {
        "artifact": {"profileId": "v2"},
        "runtime": {
            "artifact": {
                "circuitSourcePresent": False,
                "zkeyGiB": 1.985,
            }
        },
        "probe": {
            "status": "verified",
            "timings": {
                "witness_ms": 163.0,
                "prove_ms": 274767.0,
                "verify_ms": 234.0,
                "total_ms": 275600.0,
            },
        },
    }

    analysis = analyze_probe_report(report, target_proof_seconds=120)

    assert analysis["overTarget"] is True
    assert analysis["bottleneck"] == "prove"
    assert analysis["nextStep"] == "recover-circuit-source"
    assert any("Recover the Circom source" in item for item in analysis["recommendations"])


def test_analyze_probe_report_points_to_smaller_profile_when_source_exists():
    report = {
        "artifact": {"profileId": "v2"},
        "runtime": {
            "artifact": {
                "circuitSourcePresent": True,
                "zkeyGiB": 1.985,
            }
        },
        "probe": {
            "status": "verified",
            "timings": {
                "witness_ms": 163.0,
                "prove_ms": 274767.0,
                "verify_ms": 234.0,
                "total_ms": 275600.0,
            },
        },
    }

    analysis = analyze_probe_report(report, target_proof_seconds=120)

    assert analysis["nextStep"] == "generate-smaller-authoritative-profile"
    assert any("smaller authoritative profile" in item.lower() for item in analysis["recommendations"])


def test_run_zkpt_benchmark_records_verified_probe(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "blockvault_api.zkpt_benchmark.run_zkpt_probe",
        lambda **_: {
            "artifact": {"profileId": "v3a", "artifactVersion": "v3a"},
            "runtime": {"artifact": {"circuitSourcePresent": True, "zkeyGiB": 0.494}},
            "probe": {
                "status": "verified",
                "totalShards": 1,
                "timings": {
                    "projection_ms": 10.0,
                    "witness_ms": 20.0,
                    "prove_ms": 40.0,
                    "verify_ms": 5.0,
                    "total_ms": 75.0,
                },
            },
        },
    )
    monkeypatch.setattr("blockvault_api.zkpt_benchmark.record_zkpt_benchmark", lambda **kwargs: captured.update(kwargs))

    report = run_zkpt_benchmark()

    assert report["benchmark"]["selectedProfile"] == "v3a"
    assert captured["profile_id"] == "v3a"
    assert captured["artifact_version"] == "v3a"
    assert captured["classification"] == "single_proof_ready"
    assert captured["onchain_eligible"] is True
