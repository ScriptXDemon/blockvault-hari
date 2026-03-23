from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import get_settings
from .zkpt_artifacts import ZKPTArtifactVersion, repo_root


class ZKPTProverError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProofExecutionResult:
    proof_json: dict[str, Any]
    public_signals: list[str]
    verified: bool
    witness_hash: str
    proof_hash: str
    public_signals_hash: str
    timings: dict[str, float]
    backend: str
    stdout: str
    stderr: str


class SnarkjsPlonkProver:
    def __init__(self, artifact_version: ZKPTArtifactVersion, timeout_seconds: int) -> None:
        self.artifact_version = artifact_version
        self.timeout_seconds = timeout_seconds
        self.node_bin = self._resolve_node_bin()
        self.snarkjs_bin = self._resolve_snarkjs_bin()
        self.rapidsnark_bin = self._resolve_rapidsnark_bin()

    @staticmethod
    def _resolve_configured_binary(configured: str | None) -> Path | None:
        if not configured:
            return None
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = (repo_root() / candidate).resolve()
        return candidate.resolve() if candidate.exists() else None

    def _resolve_snarkjs_bin(self) -> Path:
        if self.artifact_version.snarkjs_bin.exists():
            return self.artifact_version.snarkjs_bin
        discovered = shutil.which("snarkjs")
        if discovered:
            return Path(discovered).resolve()
        raise ZKPTProverError("artifact-missing", "snarkjs executable not found")

    @classmethod
    def _resolve_node_bin(cls) -> Path | None:
        configured = cls._resolve_configured_binary(get_settings().zkpt_node_bin)
        if configured:
            return configured
        discovered = shutil.which("node")
        return Path(discovered).resolve() if discovered else None

    @classmethod
    def _resolve_rapidsnark_bin(cls) -> Path | None:
        configured = cls._resolve_configured_binary(get_settings().zkpt_rapidsnark_bin)
        if configured:
            return configured
        discovered = shutil.which("rapidsnark")
        return Path(discovered).resolve() if discovered else None

    @staticmethod
    def _requires_node_wrapper(binary_path: Path) -> bool:
        return binary_path.suffix.lower() in {".js", ".cjs", ".mjs"}

    @staticmethod
    def _canonical_json_bytes(payload: Any) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _protocol_command(self) -> str:
        protocol = (self.artifact_version.protocol or "plonk").lower()
        if protocol == "plonk":
            return "plonk"
        if protocol == "groth16":
            return "groth16"
        if protocol == "fflonk":
            return "fflonk"
        raise ZKPTProverError("unsupported-protocol", f"Unsupported proof protocol '{self.artifact_version.protocol}'")

    def _run(self, args: list[str], *, timeout_seconds: int | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
                env=dict(os.environ),
            )
        except subprocess.TimeoutExpired as exc:
            raise ZKPTProverError("prover-timeout", "proof command timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise ZKPTProverError(
                "prover-exit-nonzero",
                exc.stderr.strip() or exc.stdout.strip() or f"proof tooling exited with {exc.returncode}",
            ) from exc

    def _run_snarkjs(self, args: list[str], *, timeout_seconds: int | None = None) -> subprocess.CompletedProcess[str]:
        command = [str(self.snarkjs_bin), *args]
        if self._requires_node_wrapper(self.snarkjs_bin):
            if not self.node_bin:
                raise ZKPTProverError("artifact-missing", "Node.js executable not found for snarkjs")
            command = [str(self.node_bin), *command]
        return self._run(command, timeout_seconds=timeout_seconds)

    def _run_native(self, args: list[str], *, timeout_seconds: int | None = None) -> subprocess.CompletedProcess[str]:
        return self._run(args, timeout_seconds=timeout_seconds)

    def _calculate_witness(self, witness_path: Path, wtns_path: Path) -> tuple[subprocess.CompletedProcess[str], float]:
        witness_started = time.perf_counter()
        witness_run = self._run_snarkjs(
            [
                "wtns",
                "calculate",
                str(self.artifact_version.wasm_path),
                str(witness_path),
                str(wtns_path),
            ]
        )
        witness_ms = round((time.perf_counter() - witness_started) * 1000, 3)
        return witness_run, witness_ms

    def _prove_with_plonk(
        self,
        witness_path: Path,
        proof_path: Path,
        public_path: Path,
    ) -> tuple[list[subprocess.CompletedProcess[str]], dict[str, float], str]:
        wtns_path = witness_path.with_suffix(".wtns")
        witness_run, witness_ms = self._calculate_witness(witness_path, wtns_path)

        prove_started = time.perf_counter()
        prove_run = self._run_snarkjs(
            [
                self._protocol_command(),
                "prove",
                str(self.artifact_version.zkey_path),
                str(wtns_path),
                str(proof_path),
                str(public_path),
            ]
        )
        prove_ms = round((time.perf_counter() - prove_started) * 1000, 3)
        return [witness_run, prove_run], {"witness_ms": witness_ms, "prove_ms": prove_ms}, "snarkjs_wtns_plonk_prove"

    def _prove_with_snarkjs_fullprove(self, witness_path: Path, proof_path: Path, public_path: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, float], str]:
        prove_started = time.perf_counter()
        prove_run = self._run_snarkjs(
            [
                self._protocol_command(),
                "fullprove",
                str(witness_path),
                str(self.artifact_version.wasm_path),
                str(self.artifact_version.zkey_path),
                str(proof_path),
                str(public_path),
            ]
        )
        prove_ms = round((time.perf_counter() - prove_started) * 1000, 3)
        return prove_run, {"prove_ms": prove_ms}, "snarkjs_fullprove"

    def _prove_with_rapidsnark(
        self,
        witness_path: Path,
        proof_path: Path,
        public_path: Path,
    ) -> tuple[list[subprocess.CompletedProcess[str]], dict[str, float], str]:
        assert self.rapidsnark_bin is not None
        wtns_path = witness_path.with_suffix(".wtns")

        witness_started = time.perf_counter()
        witness_run = self._run_snarkjs(
            [
                "wtns",
                "calculate",
                str(self.artifact_version.wasm_path),
                str(witness_path),
                str(wtns_path),
            ]
        )
        witness_ms = round((time.perf_counter() - witness_started) * 1000, 3)

        prove_started = time.perf_counter()
        prove_run = self._run_native(
            [
                str(self.rapidsnark_bin),
                str(self.artifact_version.zkey_path),
                str(wtns_path),
                str(proof_path),
                str(public_path),
            ]
        )
        prove_ms = round((time.perf_counter() - prove_started) * 1000, 3)
        return [witness_run, prove_run], {"witness_ms": witness_ms, "prove_ms": prove_ms}, "snarkjs_wtns_rapidsnark"

    def prove(self, witness: dict[str, Any]) -> ProofExecutionResult:
        binding_input_name = self.artifact_version.binding_input_name
        if binding_input_name not in witness:
            raise ZKPTProverError(
                "witness-binding-missing",
                f"witness is missing required binding input '{binding_input_name}'",
            )
        expected_public = [
            str(witness["originalRoot"]),
            str(witness["redactedRoot"]),
            str(witness["policyCommitment"]),
            str(witness[binding_input_name]),
        ]

        with tempfile.TemporaryDirectory(prefix="blockvault-zkpt-") as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            witness_path = tmp_dir / "witness.json"
            proof_path = tmp_dir / "proof.json"
            public_path = tmp_dir / "public.json"

            witness_bytes = self._canonical_json_bytes(witness)
            witness_hash = hashlib.sha256(witness_bytes).hexdigest()
            witness_path.write_bytes(witness_bytes)

            phase_runs: list[subprocess.CompletedProcess[str]] = []
            protocol = (self.artifact_version.protocol or "plonk").lower()
            if protocol == "plonk":
                prove_runs, timings, backend = self._prove_with_plonk(witness_path, proof_path, public_path)
                phase_runs.extend(prove_runs)
            elif protocol == "groth16" and self.rapidsnark_bin:
                prove_runs, timings, backend = self._prove_with_rapidsnark(witness_path, proof_path, public_path)
                phase_runs.extend(prove_runs)
            elif protocol in {"groth16", "fflonk"}:
                prove_run, timings, backend = self._prove_with_snarkjs_fullprove(witness_path, proof_path, public_path)
                phase_runs.append(prove_run)
            else:
                raise ZKPTProverError("unsupported-protocol", f"Unsupported proof protocol '{self.artifact_version.protocol}'")

            proof_json = json.loads(proof_path.read_text(encoding="utf-8"))
            public_signals = [str(item) for item in json.loads(public_path.read_text(encoding="utf-8"))]
            if public_signals[:4] != expected_public:
                raise ZKPTProverError("public-signal-mismatch", "public signals do not match witness public inputs")

            verify_started = time.perf_counter()
            verify_run = self._run_snarkjs(
                [
                    self._protocol_command(),
                    "verify",
                    str(self.artifact_version.verification_key_path),
                    str(public_path),
                    str(proof_path),
                ]
            )
            timings["verify_ms"] = round((time.perf_counter() - verify_started) * 1000, 3)
            phase_runs.append(verify_run)

            proof_hash = hashlib.sha256(self._canonical_json_bytes(proof_json)).hexdigest()
            public_hash = hashlib.sha256(self._canonical_json_bytes(public_signals)).hexdigest()
            verify_stdout = (verify_run.stdout or "").lower()
            if "ok" not in verify_stdout and "verified" not in verify_stdout:
                raise ZKPTProverError("verify-failed", verify_run.stdout.strip() or "plonk verification failed")

            return ProofExecutionResult(
                proof_json=proof_json,
                public_signals=public_signals,
                verified=True,
                witness_hash=witness_hash,
                proof_hash=proof_hash,
                public_signals_hash=public_hash,
                timings=timings,
                backend=backend,
                stdout="".join(run.stdout or "" for run in phase_runs),
                stderr="".join(run.stderr or "" for run in phase_runs),
            )

