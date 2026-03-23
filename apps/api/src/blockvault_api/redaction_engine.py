from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .config import get_settings
from .crypto import sha256_hex
from .zkpt_artifacts import repo_root


class RedactionEngineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RustRedactionOutput:
    redacted_pdf_bytes: bytes
    canonical_original_text: str
    canonical_redacted_text: str
    manifest: dict[str, object]


def has_extractable_text(pdf_bytes: bytes) -> bool:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return False
    extracted = "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    return bool(extracted)


def _candidate_binaries() -> list[Path]:
    root = repo_root()
    configured = get_settings().redaction_engine_bin
    candidates: list[Path] = []
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        candidates.append(candidate)
    candidates.extend(
        [
            (root / "apps" / "redactor-rs" / "target" / "release" / "blockvault-redactor.exe").resolve(),
            (root / "apps" / "redactor-rs" / "target" / "release" / "blockvault-redactor").resolve(),
            (root / "apps" / "redactor-rs" / "target" / "debug" / "blockvault-redactor.exe").resolve(),
            (root / "apps" / "redactor-rs" / "target" / "debug" / "blockvault-redactor").resolve(),
        ]
    )
    return candidates


def resolve_redaction_engine_binary() -> Path:
    for candidate in _candidate_binaries():
        if candidate.exists():
            return candidate
    discovered = shutil.which("blockvault-redactor")
    if discovered:
        return Path(discovered).resolve()
    raise RedactionEngineError("redaction-engine-missing", "Rust redaction engine binary not found")


def _run_engine(command: list[str]) -> subprocess.CompletedProcess[str]:
    timeout_seconds = max(60, get_settings().redaction_timeout_seconds)
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RedactionEngineError("redaction-engine-timeout", "Rust redaction engine timed out") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "").strip() or "Rust redaction engine failed"
        code = "redaction-engine-error"
        if "extractable-text-required" in message:
            code = "extractable-text-required"
            message = "Authoritative ZKPT requires extractable document text"
        elif "no-redaction-matches" in message:
            code = "no-redaction-matches"
            message = "No canonical projection segments matched the requested redaction terms"
        elif "ocr-layout-required" in message:
            code = "ocr-layout-required"
            message = "OCR preprocessing artifacts were not provided to the Rust redaction engine"
        raise RedactionEngineError(code, message) from exc


def get_redaction_engine_status() -> dict[str, object]:
    settings = get_settings()
    try:
        binary = resolve_redaction_engine_binary()
    except RedactionEngineError as exc:
        return {
            "ready": False,
            "mode": settings.redaction_engine_mode,
            "path": None,
            "version": None,
            "engineName": None,
            "error": exc.message,
        }

    completed = _run_engine([str(binary), "version-json"])
    payload = json.loads(completed.stdout)
    version = str(payload.get("engine_version"))
    if settings.redaction_engine_expected_version and version != settings.redaction_engine_expected_version:
        return {
            "ready": False,
            "mode": settings.redaction_engine_mode,
            "path": str(binary),
            "version": version,
            "engineName": payload.get("engine_name"),
            "error": (
                f"Rust redaction engine version '{version}' does not match "
                f"'{settings.redaction_engine_expected_version}'"
            ),
        }
    return {
        "ready": True,
        "mode": settings.redaction_engine_mode,
        "path": str(binary),
        "version": version,
        "engineName": payload.get("engine_name"),
        "error": None,
    }


def run_rust_redaction_engine(
    *,
    pdf_bytes: bytes,
    normalized_terms: list[str],
    source_pdf_sha256: str,
    source_mode: str = "searchable_pdf",
    searchable_layout: dict[str, Any] | None = None,
    ocr_layout: dict[str, Any] | None = None,
    page_images: list[dict[str, Any]] | None = None,
    working_searchable_pdf_bytes: bytes | None = None,
) -> RustRedactionOutput:
    binary = resolve_redaction_engine_binary()
    cli_source_mode = "ocr-layout" if source_mode == "ocr_layout" else "searchable-pdf"
    manifest_source_mode = "ocr_assisted" if source_mode == "ocr_layout" else "direct_pdf"
    with tempfile.TemporaryDirectory(prefix="blockvault-redactor-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        input_path = tmp_dir / "input.pdf"
        output_dir = tmp_dir / "output"
        input_path.write_bytes(pdf_bytes)
        command = [
            str(binary),
            "run",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--terms-json",
            json.dumps(normalized_terms),
            "--source-mode",
            cli_source_mode,
        ]
        layout_sha256: str | None = None
        working_searchable_pdf_sha256: str | None = None
        images_dir: Path | None = None
        if page_images:
            images_dir = tmp_dir / "page-images"
            images_dir.mkdir(parents=True, exist_ok=True)
            for page in page_images:
                page_index = int(page["page_index"])
                suffix = ".png"
                content_type = str(page.get("content_type") or "image/png").lower()
                if content_type.endswith("jpeg") or content_type.endswith("jpg"):
                    suffix = ".jpg"
                (images_dir / f"page-{page_index:04d}{suffix}").write_bytes(bytes(page["image_bytes"]))
        if source_mode == "ocr_layout":
            if not ocr_layout or images_dir is None:
                raise RedactionEngineError("ocr-layout-required", "OCR preprocessing artifacts are required for OCR-assisted redaction")
            layout_path = tmp_dir / "ocr-layout.json"
            layout_payload = json.dumps(ocr_layout, sort_keys=True, separators=(",", ":")).encode("utf-8")
            layout_sha256 = sha256_hex(layout_payload)
            layout_path.write_bytes(layout_payload)
            command.extend(["--ocr-layout-json", str(layout_path), "--page-images-dir", str(images_dir)])
            if working_searchable_pdf_bytes is not None:
                working_searchable_path = tmp_dir / "ocr-working-searchable.pdf"
                working_searchable_path.write_bytes(working_searchable_pdf_bytes)
                working_searchable_pdf_sha256 = sha256_hex(working_searchable_pdf_bytes)
                command.extend(["--working-searchable-pdf", str(working_searchable_path)])
        elif searchable_layout is not None:
            if images_dir is None:
                raise RedactionEngineError(
                    "searchable-layout-required",
                    "Searchable PDF layout artifacts are required for structure-preserving direct redaction",
                )
            layout_path = tmp_dir / "searchable-layout.json"
            layout_payload = json.dumps(searchable_layout, sort_keys=True, separators=(",", ":")).encode("utf-8")
            layout_path.write_bytes(layout_payload)
            command.extend(["--searchable-layout-json", str(layout_path), "--page-images-dir", str(images_dir)])
        _run_engine(command)

        redacted_pdf_path = output_dir / "redacted.pdf"
        canonical_original_path = output_dir / "canonical_original.txt"
        canonical_redacted_path = output_dir / "canonical_redacted.txt"
        manifest_path = output_dir / "redaction_manifest.json"
        for required in (redacted_pdf_path, canonical_original_path, canonical_redacted_path, manifest_path):
            if not required.exists():
                raise RedactionEngineError("redaction-engine-output-missing", f"Rust redaction engine did not produce {required.name}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("source_pdf_sha256") != source_pdf_sha256:
            raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine source PDF hash mismatch")
        if manifest.get("source_text_mode") != manifest_source_mode:
            raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine source mode mismatch")

        redacted_pdf_bytes = redacted_pdf_path.read_bytes()
        canonical_original_text = canonical_original_path.read_text(encoding="utf-8")
        canonical_redacted_text = canonical_redacted_path.read_text(encoding="utf-8")
        if manifest.get("canonical_original_sha256") != sha256_hex(canonical_original_text.encode("utf-8")):
            raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine canonical original hash mismatch")
        if manifest.get("canonical_redacted_sha256") != sha256_hex(canonical_redacted_text.encode("utf-8")):
            raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine canonical redacted hash mismatch")
        if manifest.get("redacted_pdf_sha256") != sha256_hex(redacted_pdf_bytes):
            raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine redacted PDF hash mismatch")
        if not manifest.get("searchable_text_confirmed"):
            raise RedactionEngineError("extractable-text-required", "Authoritative ZKPT requires extractable document text")
        if source_mode == "ocr_layout":
            if not manifest.get("ocr_used"):
                raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine did not record OCR-assisted provenance")
            if layout_sha256 and manifest.get("ocr_layout_sha256") != layout_sha256:
                raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine OCR layout hash mismatch")
            if working_searchable_pdf_sha256 and manifest.get("working_searchable_pdf_sha256") != working_searchable_pdf_sha256:
                raise RedactionEngineError("redaction-manifest-mismatch", "Rust redaction engine working searchable PDF hash mismatch")

        return RustRedactionOutput(
            redacted_pdf_bytes=redacted_pdf_bytes,
            canonical_original_text=canonical_original_text,
            canonical_redacted_text=canonical_redacted_text,
            manifest=manifest,
        )
