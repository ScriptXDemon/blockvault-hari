from __future__ import annotations

import base64
import io
import threading
import time
import zipfile
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from blockvault_api.crypto import decrypt_bytes, utcnow
from blockvault_api.database import get_database
from blockvault_api.config import reset_settings_cache
from blockvault_api.ocr import OcrConversionResult, OcrPageImage
from blockvault_api.redaction_jobs import (
    attempt_authoritative_proof,
    attempt_authoritative_proof_with_deadline,
    select_authoritative_plan,
)
from blockvault_api.redaction_engine import RedactionEngineError, RustRedactionOutput
from blockvault_api.zkpt_bundle import build_bundle_export
from blockvault_api.zkpt_artifacts import ZKPTArtifactVersion
from blockvault_api.zkpt_prover import ProofExecutionResult, ZKPTProverError


def _make_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.drawString(72, 720, text)
    pdf.save()
    buffer.seek(0)
    return buffer.read()


def _encrypt_payload(payload: bytes, passphrase: str) -> tuple[bytes, str, str]:
    salt = b"0123456789abcdef"
    iv = b"redact-dociv"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    key = kdf.derive(passphrase.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(iv, payload, None)
    return (
        ciphertext,
        base64.b64encode(salt).decode("utf-8"),
        base64.b64encode(iv).decode("utf-8"),
    )


def _make_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0XQAAAAASUVORK5CYII="
    )


def _wait_for_redaction_result(client, job_id: str, timeout_seconds: float = 5.0):
    deadline = time.time() + timeout_seconds
    latest_response = None
    while time.time() < deadline:
        latest_response = client.get(f"/api/v1/redactions/jobs/{job_id}/result")
        if latest_response.status_code == 200:
            return latest_response

        job_response = client.get(f"/api/v1/redactions/jobs/{job_id}")
        if job_response.status_code == 200 and job_response.json()["status"] == "failed":
            return latest_response
        time.sleep(0.05)
    return latest_response


@pytest.fixture
def authenticated_client(client):
    wallet = "0x1000000000000000000000000000000000000001"
    db = get_database()
    db.users.insert_one(
        {
            "wallet_address": wallet.lower(),
            "display_name": "0x1000...0001",
            "created_at": utcnow(),
            "last_login_at": utcnow(),
        }
    )
    db.sessions.insert_one(
        {
            "session_id": "sess_test_workflow",
            "wallet_address": wallet.lower(),
            "created_at": utcnow(),
            "expires_at": utcnow() + timedelta(hours=1),
        }
    )
    client.cookies.set("bv_session", "sess_test_workflow")
    return client


@pytest.fixture(autouse=True)
def mock_rust_redaction_engine(monkeypatch):
    def fake_run_rust_redaction_engine(**kwargs):
        source_mode = kwargs.get("source_mode", "searchable_pdf")
        is_ocr = source_mode == "ocr_layout"
        preserves_layout = is_ocr or kwargs.get("searchable_layout") is not None
        return RustRedactionOutput(
            redacted_pdf_bytes=_make_pdf("Rust redacted output"),
            canonical_original_text="Privileged contract material for BlockVault.",
            canonical_redacted_text="[REDACTED] contract material for BlockVault.",
            manifest={
                "engine_name": "blockvault-redactor",
                "engine_version": "0.1.0",
                "searchable_text_confirmed": True,
                "canonical_original_sha256": "orig-hash",
                "canonical_redacted_sha256": "red-hash",
                "source_text_mode": "ocr_assisted" if is_ocr else "direct_pdf",
                "ocr_used": is_ocr,
                "ocr_engine": "rapidocr_onnxruntime" if is_ocr else None,
                "ocr_engine_version": "1.4.4" if is_ocr else None,
                "ocr_layout_sha256": "layout-hash" if is_ocr else None,
                "working_searchable_pdf_sha256": "working-hash" if is_ocr else None,
                "render_mode": "raster_overlay" if preserves_layout else "text_reflow",
            },
        )

    monkeypatch.setattr("blockvault_api.redaction_jobs.run_rust_redaction_engine", fake_run_rust_redaction_engine)


@pytest.fixture(autouse=True)
def default_onchain_safe_profile(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_SAFE_PROFILE", "v4_sparse")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture(autouse=True)
def fast_fail_proof_for_route_workflows(monkeypatch, request):
    real_proof_tests = {
        "test_document_redaction_can_persist_verified_zkpt_bundle",
        "test_attempt_authoritative_proof_timeout_fails_closed",
        "test_attempt_authoritative_proof_deadline_fails_closed",
        "test_attempt_authoritative_proof_marks_non_authoritative_profile_as_unsupported",
        "test_attempt_authoritative_proof_sparse_profile_batches_by_modified_segments",
        "test_select_authoritative_plan_prefers_onchain_safe_profile_for_sparse_runtime",
        "test_select_authoritative_plan_keeps_sparse_profile_when_onchain_safe_profile_cannot_fit",
    }
    if request.node.name in real_proof_tests:
        yield
        return

    def fake_proof(**kwargs):
        artifact_profile_id = kwargs.get("artifact_profile_id") or "v4_sparse"
        return (
            {
                "mode": "authoritative",
                "status": "failed",
                "bundle_id": None,
                "artifact_version": artifact_profile_id,
                "profile_id": artifact_profile_id,
                "profile_class": "authoritative",
                "proof_boundary": "canonical_segment_mask_v1",
                "verified_shards": 0,
                "total_shards": 0,
                "estimated_shards": 1,
                "predicted_proof_ms": 0.0,
                "classification": "verified_bundle_only",
                "onchain_eligible": False,
                "onchain_status": "unsupported",
                "document_binding_commitment": None,
                "fallback_mode": False,
                "prover_backend": None,
                "error": {"code": "prover-timeout", "message": "timeout"},
            },
            None,
        )

    monkeypatch.setattr("blockvault_api.redaction_jobs.attempt_authoritative_proof_with_deadline", fake_proof)
    yield


def test_document_upload_notarize_redact_and_export_flow(authenticated_client):
    client = authenticated_client
    passphrase = "correct horse battery staple"
    pdf_bytes = _make_pdf("Privileged contract material for BlockVault.")
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(pdf_bytes, passphrase)

    case_response = client.post("/api/v1/cases", json={"title": "Matter A", "description": "Workflow test"})
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "matter-a.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    assert init_response.status_code == 200
    document_id = init_response.json()["documentId"]

    complete_response = client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("matter-a.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    assert complete_response.status_code == 200

    original_download = client.get(f"/api/v1/documents/{document_id}/download")
    assert original_download.status_code == 200
    assert original_download.headers["x-blockvault-original-name"] == "matter-a.pdf"
    assert original_download.content == encrypted_bytes

    notarize_response = client.post(f"/api/v1/documents/{document_id}/notarize", json={"passphrase": passphrase})
    assert notarize_response.status_code == 200
    evidence_bundle_id = notarize_response.json()["evidenceBundleId"]

    document_response = client.get(f"/api/v1/documents/{document_id}")
    assert document_response.status_code == 200
    document_payload = document_response.json()
    assert document_payload["evidenceBundleId"] == evidence_bundle_id
    assert document_payload["originalSha256"]

    evidence_response = client.get(f"/api/v1/evidence/{evidence_bundle_id}")
    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()
    assert evidence_payload["documentId"] == document_id
    assert evidence_payload["documentOriginalName"] == "matter-a.pdf"
    assert any(event["eventType"] == "document.notarized" for event in evidence_payload["chainOfCustody"])

    evidence_export = client.get(f"/api/v1/evidence/{evidence_bundle_id}/export")
    assert evidence_export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(evidence_export.content)) as archive:
        assert sorted(archive.namelist()) == [
            "anchor_receipt.json",
            "bundle_manifest.json",
            "chain_of_custody.json",
            "document_summary.json",
        ]

    redaction_response = client.post(
        "/api/v1/redactions/jobs",
        json={
            "documentId": document_id,
            "passphrase": passphrase,
            "searchTerms": ["Privileged"],
        },
    )
    assert redaction_response.status_code == 200
    job_id = redaction_response.json()["jobId"]

    result_response = _wait_for_redaction_result(client, job_id)
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["verification_passed"] is False
    assert result_payload["zkpt"]["status"] == "failed"
    assert result_payload["source_text_mode"] == "direct_pdf"
    assert result_payload["ocr_used"] is False
    assert result_payload["ocr_engine"] is None
    assert result_payload["render_mode"] == "raster_overlay"

    refreshed_document = client.get(f"/api/v1/documents/{document_id}").json()
    assert refreshed_document["redactionResultId"] == result_payload["documentId"]
    assert refreshed_document["redactedSha256"] == result_payload["redactedSha256"]

    redacted_download = client.get(f"/api/v1/documents/{result_payload['documentId']}/download")
    assert redacted_download.status_code == 200
    assert redacted_download.headers["content-type"] == "application/pdf"
    assert redacted_download.content.startswith(b"%PDF")


def test_document_ocr_creates_searchable_copy(authenticated_client, monkeypatch):
    client = authenticated_client
    passphrase = "correct horse battery staple"
    pdf_bytes = _make_pdf("Scanned contract image placeholder")
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(pdf_bytes, passphrase)

    monkeypatch.setattr(
        "blockvault_api.routes.documents.ocr_pdf_to_searchable",
        lambda _: OcrConversionResult(
            searchable_pdf_bytes=_make_pdf("OCR searchable text for BlockVault"),
            extracted_text="OCR searchable text for BlockVault",
            page_count=1,
            engine_name="rapidocr_onnxruntime",
            engine_version="1.4.4",
        ),
    )

    case_response = client.post("/api/v1/cases", json={"title": "Matter OCR", "description": "OCR workflow"})
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "matter-ocr.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    document_id = init_response.json()["documentId"]
    complete_response = client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("matter-ocr.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    assert complete_response.status_code == 200

    ocr_response = client.post(f"/api/v1/documents/{document_id}/ocr", json={"passphrase": passphrase})
    assert ocr_response.status_code == 200
    ocr_document_id = ocr_response.json()["documentId"]
    assert ocr_document_id != document_id
    assert ocr_response.json()["originalName"] == "matter-ocr-ocr.pdf"

    ocr_document = client.get(f"/api/v1/documents/{ocr_document_id}")
    assert ocr_document.status_code == 200
    ocr_payload = ocr_document.json()
    assert ocr_payload["caseId"] == case_id
    assert ocr_payload["searchableTextConfirmed"] is True

    encrypted_download = client.get(f"/api/v1/documents/{ocr_document_id}/download")
    assert encrypted_download.status_code == 200
    decrypted_ocr_pdf = decrypt_bytes(
        encrypted_download.content,
        passphrase,
        salt_b64=encrypted_download.headers["x-blockvault-salt"],
        iv_b64=encrypted_download.headers["x-blockvault-iv"],
    )
    assert decrypted_ocr_pdf.startswith(b"%PDF")


def test_document_redaction_uses_inline_ocr_without_creating_visible_copy(authenticated_client, monkeypatch):
    client = authenticated_client
    passphrase = "correct horse battery staple"
    pdf_bytes = _make_pdf("Raster placeholder for scanned contract")
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(pdf_bytes, passphrase)

    monkeypatch.setattr("blockvault_api.redaction_jobs.has_extractable_text", lambda _: False)
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.ocr_pdf_to_searchable",
        lambda _: OcrConversionResult(
            searchable_pdf_bytes=_make_pdf("Privileged OCR contract material for BlockVault."),
            extracted_text="Privileged OCR contract material for BlockVault.",
            page_count=1,
            engine_name="rapidocr_onnxruntime",
            engine_version="1.4.4",
            canonical_text="Privileged OCR contract material for BlockVault.",
            working_searchable_pdf_sha256="working-hash",
            canonical_text_sha256="ocr-canonical-hash",
            layout_sha256="layout-hash",
            layout={
                "layoutVersion": 1,
                "engine": "rapidocr_onnxruntime",
                "engineVersion": "1.4.4",
                "pageCount": 1,
                "pages": [
                    {
                        "pageIndex": 0,
                        "pageWidth": 612.0,
                        "pageHeight": 792.0,
                        "imageWidth": 10,
                        "imageHeight": 10,
                        "blocks": [
                            {
                                "blockIndex": 0,
                                "text": "Privileged OCR contract material for BlockVault.",
                                "confidence": 0.99,
                                "polygon": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
                                "bounds": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
                            }
                        ],
                    }
                ],
            },
            page_images=[OcrPageImage(page_index=0, image_bytes=_make_png(), image_width=10, image_height=10)],
        ),
    )

    case_response = client.post("/api/v1/cases", json={"title": "Matter OCR Inline", "description": "Inline OCR workflow"})
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "matter-inline-scan.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    assert init_response.status_code == 200
    document_id = init_response.json()["documentId"]

    complete_response = client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("matter-inline-scan.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    assert complete_response.status_code == 200

    redaction_response = client.post(
        "/api/v1/redactions/jobs",
        json={
            "documentId": document_id,
            "passphrase": passphrase,
            "searchTerms": ["Privileged"],
        },
    )
    assert redaction_response.status_code == 200

    result_response = _wait_for_redaction_result(client, redaction_response.json()["jobId"])
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["source_text_mode"] == "ocr_assisted"
    assert result_payload["ocr_used"] is True
    assert result_payload["ocr_engine"] == "rapidocr_onnxruntime"
    assert result_payload["ocr_layout_sha256"] == "layout-hash"
    assert result_payload["render_mode"] == "raster_overlay"

    db = get_database()
    documents = list(db.documents.find({"owner_wallet": "0x1000000000000000000000000000000000000001"}))
    assert len(documents) == 2
    assert not any(item["original_name"].endswith("-ocr.pdf") for item in documents)

    job_record = db.redaction_jobs.find_one({"job_id": redaction_response.json()["jobId"]})
    assert job_record is not None
    assert job_record["source_text_mode"] == "ocr_assisted"
    assert job_record["ocr_used"] is True
    assert job_record["ocr_artifacts"]["working_searchable_pdf_storage_key"].startswith("redaction-artifacts/")


def test_document_redaction_can_persist_verified_zkpt_bundle(authenticated_client, monkeypatch, tmp_path):
    client = authenticated_client
    passphrase = "correct horse battery staple"
    pdf_bytes = _make_pdf("Privileged contract material for BlockVault.")
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(pdf_bytes, passphrase)

    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.get_active_artifact_version",
        lambda: ZKPTArtifactVersion(
            profile_id="test-v2",
            profile_class="authoritative",
            proof_boundary="canonical_segment_mask_v1",
            proof_model="full_segment_windows",
            binding_input_name="transformationId",
            artifact_version_id="test-v2",
            circuit_id="zkpt_redaction_v2",
            protocol="plonk",
            artifacts_dir=artifacts_dir,
            wasm_path=wasm_path,
            zkey_path=zkey_path,
            verification_key_path=verification_key_path,
            verification_key_hash="verification-key-hash",
            zkey_hash="zkey-hash",
            toolchain={"snarkjs": "0.7.6"},
            segment_size=1024,
            max_segments=16,
            tree_depth=8,
            max_policy_rules=8,
            snarkjs_bin=snarkjs_path,
        ),
    )
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.generate_circuit_witness",
        lambda **_: {
            "witness": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            },
            "metadata": {
                "selected_indices": [0],
                "padded_indices": [0],
                "modified_indices": [0],
                "policy_terms_normalized": ["privileged"],
            },
            "verification_data": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            },
        },
    )
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.SnarkjsPlonkProver.prove",
        lambda self, witness: ProofExecutionResult(
            proof_json={"pi_a": ["1", "2"], "protocol": "plonk"},
            public_signals=[
                witness["originalRoot"],
                witness["redactedRoot"],
                witness["policyCommitment"],
                witness["transformationId"],
            ],
            verified=True,
            witness_hash="witness-hash",
            proof_hash="proof-hash",
            public_signals_hash="public-signals-hash",
            timings={"prove_ms": 12.5, "verify_ms": 3.2},
            backend="test-mock",
            stdout="ok",
            stderr="",
        ),
    )

    case_response = client.post("/api/v1/cases", json={"title": "Matter B", "description": "Verified zkpt workflow"})
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "matter-b.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    assert init_response.status_code == 200
    document_id = init_response.json()["documentId"]

    complete_response = client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("matter-b.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    assert complete_response.status_code == 200

    notarize_response = client.post(f"/api/v1/documents/{document_id}/notarize", json={"passphrase": passphrase})
    assert notarize_response.status_code == 200

    redaction_response = client.post(
        "/api/v1/redactions/jobs",
        json={
            "documentId": document_id,
            "passphrase": passphrase,
            "searchTerms": ["Privileged"],
        },
    )
    assert redaction_response.status_code == 200
    job_id = redaction_response.json()["jobId"]

    result_response = _wait_for_redaction_result(client, job_id)
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["verification_passed"] is True
    assert result_payload["zkpt"]["status"] == "verified"
    assert result_payload["zkpt"]["profile_id"] == "test-v2"
    assert result_payload["zkpt"]["profile_class"] == "authoritative"
    assert result_payload["zkpt"]["prover_backend"] == "test-mock"
    assert result_payload["zkpt"]["classification"] == "verified_bundle_only"
    assert result_payload["zkpt"]["onchain_eligible"] is False
    assert result_payload["zkpt"]["estimated_shards"] == 1
    assert result_payload["zkpt"]["onchain_status"] == "unsupported"
    assert result_payload["zkpt"]["document_binding_commitment"]
    bundle_id = result_payload["zkpt"]["bundle_id"]
    assert bundle_id

    db = get_database()
    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id})
    assert bundle is not None
    assert bundle["status"] == "verified"
    assert bundle["artifact_version"] == "test-v2"
    assert bundle["manifest"]["documentId"] == result_payload["documentId"]
    assert bundle["summary"]["classification"] == "verified_bundle_only"
    assert bundle["summary"]["onchainEligible"] is False
    assert bundle["onchain"]["status"] == "unsupported"

    export_response = client.get(f"/api/v1/zkpt/bundles/{bundle_id}/export")
    assert export_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export_response.content)) as archive:
        assert sorted(archive.namelist()) == [
            "bundle_manifest.json",
            "bundle_summary.json",
            "hashes.json",
            "projection_metadata.json",
            "proof.json",
            "public_signals.json",
            "verification_key.json",
        ]

    onchain_status_response = client.get(f"/api/v1/zkpt/bundles/{bundle_id}/onchain-status")
    assert onchain_status_response.status_code == 200
    assert onchain_status_response.json()["status"] == "unsupported"


def test_verified_bundle_can_be_submitted_onchain(authenticated_client, monkeypatch):
    client = authenticated_client
    db = get_database()
    wallet = "0x1000000000000000000000000000000000000001"
    document_id = "docr_onchain"
    bundle_id = "zkptbundle_onchain"
    db.documents.insert_one(
        {
            "document_id": document_id,
            "case_id": "case_demo",
            "file_id": "file_demo",
            "owner_wallet": wallet,
            "original_name": "redacted-proof.pdf",
            "status": "redacted_unverified",
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "anchor_receipt": None,
            "original_sha256": "a" * 64,
            "redacted_sha256": "b" * 64,
            "canonical_original_sha256": "c" * 64,
            "canonical_redacted_sha256": "d" * 64,
            "searchable_text_confirmed": True,
            "source_text_mode": "direct_pdf",
            "ocr_used": False,
            "ocr_engine": None,
            "ocr_engine_version": None,
            "ocr_layout_sha256": None,
            "working_searchable_pdf_sha256": None,
            "render_mode": "raster_overlay",
            "redaction_engine": "blockvault-redactor",
            "redaction_engine_version": "0.1.0",
            "evidence_bundle_id": "evidence_demo",
            "source_document_id": "doc_source",
            "latest_redaction_result_id": None,
            "zkpt": {
                "mode": "authoritative",
                "status": "verified",
                "bundle_id": bundle_id,
                "artifact_version": "v3a",
                "profile_id": "v3a",
                "profile_class": "authoritative",
                "proof_boundary": "canonical_segment_mask_v1",
                "verified_shards": 1,
                "total_shards": 1,
                "estimated_shards": 1,
                "predicted_proof_ms": 80000.0,
                "classification": "single_proof_ready",
                "onchain_eligible": True,
                "onchain_status": "not_submitted",
                "document_binding_commitment": "123456789",
                "fallback_mode": False,
                "prover_backend": "snarkjs_wtns_plonk_prove",
                "error": None,
            },
        }
    )
    db.zkpt_bundles.insert_one(
        {
            "bundle_id": bundle_id,
            "document_id": document_id,
            "owner_wallet": wallet,
            "artifact_version": "v3a",
            "status": "verified",
            "total_shards": 1,
            "summary": {
                "onchainEligible": True,
                "profileId": "v3a",
                "artifactVersion": "v3a",
                "documentBindingCommitment": "123456789",
                "originalSha256": "a" * 64,
                "redactedSha256": "b" * 64,
                "canonicalOriginalSha256": "c" * 64,
                "canonicalRedactedSha256": "d" * 64,
                "sourceTextMode": "direct_pdf",
            },
            "manifest_hash": "e" * 64,
            "onchain": {
                "status": "not_submitted",
                "chainId": 11155111,
                "registryAddress": None,
                "txHash": None,
                "receiptId": None,
                "submittedAt": None,
                "confirmedAt": None,
                "error": None,
            },
        }
    )

    def fake_submit(bundle):
        payload = {
            "status": "confirmed",
            "chainId": 11155111,
            "registryAddress": "0x0000000000000000000000000000000000000001",
            "txHash": "0xabc123",
            "receiptId": "0xreceipt",
            "submittedAt": utcnow().isoformat(),
            "confirmedAt": utcnow().isoformat(),
            "error": None,
        }
        db.zkpt_bundles.update_one({"bundle_id": bundle["bundle_id"]}, {"$set": {"onchain": payload}})
        db.documents.update_one({"document_id": bundle["document_id"]}, {"$set": {"zkpt.onchain_status": "confirmed"}})
        return payload

    monkeypatch.setattr("blockvault_api.routes.redactions.submit_verified_bundle_onchain", fake_submit)

    response = client.post(f"/api/v1/zkpt/bundles/{bundle_id}/submit-onchain")
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert response.json()["onchain"]["txHash"] == "0xabc123"

    onchain_status = client.get(f"/api/v1/zkpt/bundles/{bundle_id}/onchain-status")
    assert onchain_status.status_code == 200
    assert onchain_status.json()["status"] == "confirmed"

    document_payload = client.get(f"/api/v1/documents/{document_id}")
    assert document_payload.status_code == 200
    assert document_payload.json()["zkpt"]["onchain_status"] == "confirmed"


def test_attempt_authoritative_proof_supports_multi_shard_verified_bundle(monkeypatch, tmp_path):
    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.get_active_artifact_version",
        lambda: ZKPTArtifactVersion(
            profile_id="v3a",
            profile_class="authoritative",
            proof_boundary="canonical_segment_mask_v1",
            proof_model="full_segment_windows",
            binding_input_name="transformationId",
            artifact_version_id="v3a",
            circuit_id="zkpt_redaction_v2",
            protocol="plonk",
            artifacts_dir=artifacts_dir,
            wasm_path=wasm_path,
            zkey_path=zkey_path,
            verification_key_path=verification_key_path,
            verification_key_hash="verification-key-hash",
            zkey_hash="zkey-hash",
            toolchain={"snarkjs": "0.7.6"},
            segment_size=16,
            max_segments=1,
            tree_depth=2,
            max_policy_rules=4,
            snarkjs_bin=snarkjs_path,
        ),
    )

    def fake_prove(self, witness):
        suffix = witness["originalRoot"]
        return ProofExecutionResult(
            proof_json={"protocol": "plonk", "root": suffix},
            public_signals=[
                witness["originalRoot"],
                witness["redactedRoot"],
                witness["policyCommitment"],
                witness["transformationId"],
            ],
            verified=True,
            witness_hash=f"witness-{suffix}",
            proof_hash=f"proof-{suffix}",
            public_signals_hash=f"public-{suffix}",
            timings={"prove_ms": 10.0, "verify_ms": 2.0},
            backend="test-mock",
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr("blockvault_api.redaction_jobs.SnarkjsPlonkProver.prove", fake_prove)

    payload, bundle_id = attempt_authoritative_proof(
        original_text="secret alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
        masked_text="[REDACTED] alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
        original_sha256="orig-sha",
        redacted_sha256="red-sha",
        redacted_document_id="doc_test_redacted",
        redaction_job_id="redact_test_job",
        owner_wallet="0x1000000000000000000000000000000000000001",
        search_terms=["secret"],
        redaction_manifest={
            "engine_name": "blockvault-redactor",
            "engine_version": "0.1.0",
            "canonical_original_sha256": "canon-orig",
            "canonical_redacted_sha256": "canon-red",
        },
    )

    assert payload["status"] == "verified"
    assert payload["verified_shards"] > 1
    assert payload["verified_shards"] == payload["total_shards"]
    assert bundle_id

    db = get_database()
    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id})
    assert bundle is not None
    assert bundle["verified_shards"] > 1
    assert len(bundle["proof_shards"]) == bundle["verified_shards"]

    export_bytes = build_bundle_export(bundle)
    with zipfile.ZipFile(io.BytesIO(export_bytes)) as archive:
        names = set(archive.namelist())
        assert "bundle_manifest.json" in names
        assert "bundle_summary.json" in names
        assert "proofs/shards.json" in names
        assert any(name.startswith("proofs/shard-000-proof.json") for name in names)


def test_attempt_authoritative_proof_parallelizes_multi_shard_proving_and_preserves_order(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_MAX_PARALLEL_SHARDS", "2")
    reset_settings_cache()

    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.get_active_artifact_version",
        lambda: ZKPTArtifactVersion(
            profile_id="v3a",
            profile_class="authoritative",
            proof_boundary="canonical_segment_mask_v1",
            proof_model="full_segment_windows",
            binding_input_name="transformationId",
            artifact_version_id="v3a",
            circuit_id="zkpt_redaction_v2",
            protocol="plonk",
            artifacts_dir=artifacts_dir,
            wasm_path=wasm_path,
            zkey_path=zkey_path,
            verification_key_path=verification_key_path,
            verification_key_hash="verification-key-hash",
            zkey_hash="zkey-hash",
            toolchain={"snarkjs": "0.7.6"},
            segment_size=8,
            max_segments=1,
            tree_depth=4,
            max_policy_rules=4,
            snarkjs_bin=snarkjs_path,
        ),
    )

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.generate_circuit_witness",
        lambda **kwargs: {
            "witness": {
                "originalRoot": base64.b16encode(kwargs["original_bytes"]).decode("ascii"),
                "redactedRoot": base64.b16encode(kwargs["redacted_bytes"]).decode("ascii"),
                "policyCommitment": "33",
                "transformationId": "44",
            },
            "metadata": {
                "selected_indices": [0],
                "padded_indices": [0],
                "modified_indices": [0],
                "policy_terms_normalized": ["secret"],
            },
            "verification_data": {
                "originalRoot": base64.b16encode(kwargs["original_bytes"]).decode("ascii"),
                "redactedRoot": base64.b16encode(kwargs["redacted_bytes"]).decode("ascii"),
                "policyCommitment": "33",
                "transformationId": "44",
            },
        },
    )

    lock = threading.Lock()
    active = {"count": 0, "peak": 0}

    def fake_prove(self, witness):
        with lock:
            active["count"] += 1
            active["peak"] = max(active["peak"], active["count"])
        try:
            time.sleep(0.05)
            return ProofExecutionResult(
                proof_json={"protocol": "plonk", "root": witness["originalRoot"]},
                public_signals=[
                    witness["originalRoot"],
                    witness["redactedRoot"],
                    witness["policyCommitment"],
                    witness["transformationId"],
                ],
                verified=True,
                witness_hash=f"witness-{witness['originalRoot']}",
                proof_hash=f"proof-{witness['originalRoot']}",
                public_signals_hash=f"public-{witness['originalRoot']}",
                timings={"prove_ms": 50.0, "verify_ms": 2.0},
                backend="test-parallel",
                stdout="ok",
                stderr="",
            )
        finally:
            with lock:
                active["count"] -= 1

    monkeypatch.setattr("blockvault_api.redaction_jobs.SnarkjsPlonkProver.prove", fake_prove)

    try:
        payload, bundle_id = attempt_authoritative_proof(
            original_text="secret alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron",
            masked_text="[REDACTED] alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron",
            original_sha256="orig-sha",
            redacted_sha256="red-sha",
            redacted_document_id="doc_test_parallel",
            redaction_job_id="redact_parallel_job",
            owner_wallet="0x1000000000000000000000000000000000000001",
            search_terms=["secret"],
            redaction_manifest={
                "engine_name": "blockvault-redactor",
                "engine_version": "0.1.0",
                "canonical_original_sha256": "canon-orig",
                "canonical_redacted_sha256": "canon-red",
            },
        )
    finally:
        reset_settings_cache()

    assert payload["status"] == "verified"
    assert payload["classification"] == "verified_bundle_only"
    assert payload["onchain_eligible"] is False
    assert payload["verified_shards"] > 1
    assert payload["prover_backend"] == "test-parallel"
    assert active["peak"] == 2
    assert bundle_id

    db = get_database()
    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id})
    assert bundle is not None
    assert bundle["projection_metadata"]["maxParallelShards"] == 2
    assert bundle["projection_metadata"]["shardExecutionMode"] == "parallel"
    assert bundle["summary"]["onchainEligible"] is False
    assert [item["shard_index"] for item in bundle["proof_shards"]] == list(range(bundle["verified_shards"]))


def test_redaction_job_uses_rust_engine_output_for_proof(authenticated_client, monkeypatch):
    client = authenticated_client
    passphrase = "correct horse battery staple"
    pdf_bytes = _make_pdf("Privileged contract material for BlockVault.")
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(pdf_bytes, passphrase)

    case_response = client.post("/api/v1/cases", json={"title": "Matter Rust", "description": "Rust engine workflow"})
    case_id = case_response.json()["id"]
    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "matter-rust.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    document_id = init_response.json()["documentId"]
    client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("matter-rust.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )

    client.post(f"/api/v1/documents/{document_id}/notarize", json={"passphrase": passphrase})

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.run_rust_redaction_engine",
        lambda **_: RustRedactionOutput(
            redacted_pdf_bytes=_make_pdf("Rust redacted output"),
            canonical_original_text="Canonical original from rust",
            canonical_redacted_text="Canonical [REDACTED] from rust",
            manifest={
                "engine_name": "blockvault-redactor",
                "engine_version": "0.1.0",
                "searchable_text_confirmed": True,
                "canonical_original_sha256": "orig-hash",
                "canonical_redacted_sha256": "red-hash",
            },
        ),
    )

    captured: dict[str, object] = {}

    def fake_proof(**kwargs):
        captured.update(kwargs)
        return (
            {
                "mode": "authoritative",
                "status": "failed",
                "bundle_id": None,
                "artifact_version": "v2",
                "profile_id": "v2",
                "profile_class": "authoritative",
                "proof_boundary": "canonical_segment_mask_v1",
                "verified_shards": 0,
                "total_shards": 0,
                "fallback_mode": False,
                "prover_backend": None,
                "error": {"code": "prover-timeout", "message": "timeout"},
            },
            None,
        )

    monkeypatch.setattr("blockvault_api.redaction_jobs.attempt_authoritative_proof_with_deadline", fake_proof)

    redaction_response = client.post(
        "/api/v1/redactions/jobs",
        json={"documentId": document_id, "passphrase": passphrase, "searchTerms": ["Privileged"]},
    )
    job_id = redaction_response.json()["jobId"]
    result_response = _wait_for_redaction_result(client, job_id)
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert captured["original_text"] == "Canonical original from rust"
    assert captured["masked_text"] == "Canonical [REDACTED] from rust"
    assert result_payload["redaction_engine"] == "blockvault-redactor"
    assert result_payload["redaction_engine_version"] == "0.1.0"
    assert result_payload["canonical_original_sha256"] == "orig-hash"
    assert result_payload["canonical_redacted_sha256"] == "red-hash"


def test_redaction_job_fails_closed_when_rust_engine_manifest_mismatches(authenticated_client, monkeypatch):
    client = authenticated_client
    passphrase = "correct horse battery staple"
    pdf_bytes = _make_pdf("Privileged contract material for BlockVault.")
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(pdf_bytes, passphrase)

    case_response = client.post("/api/v1/cases", json={"title": "Matter Rust Fail", "description": "Rust engine fail closed"})
    case_id = case_response.json()["id"]
    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "matter-rust-fail.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    document_id = init_response.json()["documentId"]
    client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("matter-rust-fail.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    client.post(f"/api/v1/documents/{document_id}/notarize", json={"passphrase": passphrase})

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.run_rust_redaction_engine",
        lambda **_: (_ for _ in ()).throw(RedactionEngineError("redaction-manifest-mismatch", "manifest mismatch")),
    )

    redaction_response = client.post(
        "/api/v1/redactions/jobs",
        json={"documentId": document_id, "passphrase": passphrase, "searchTerms": ["Privileged"]},
    )
    job_id = redaction_response.json()["jobId"]
    job_snapshot = client.get(f"/api/v1/redactions/jobs/{job_id}").json()
    deadline = time.time() + 2
    while job_snapshot["status"] != "failed" and time.time() < deadline:
        time.sleep(0.05)
        job_snapshot = client.get(f"/api/v1/redactions/jobs/{job_id}").json()

    assert job_snapshot["status"] == "failed"
    assert job_snapshot["errorCode"] == "redaction-manifest-mismatch"


def test_document_delete_soft_deletes_lineage_and_preserves_evidence(authenticated_client):
    client = authenticated_client
    passphrase = "correct horse battery staple"
    pdf_bytes = _make_pdf("Privileged contract material for BlockVault.")
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(pdf_bytes, passphrase)

    case_response = client.post("/api/v1/cases", json={"title": "Matter Delete", "description": "Delete workflow"})
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "matter-delete.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    assert init_response.status_code == 200
    document_id = init_response.json()["documentId"]

    complete_response = client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("matter-delete.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    assert complete_response.status_code == 200

    notarize_response = client.post(f"/api/v1/documents/{document_id}/notarize", json={"passphrase": passphrase})
    assert notarize_response.status_code == 200
    evidence_bundle_id = notarize_response.json()["evidenceBundleId"]

    redaction_response = client.post(
        "/api/v1/redactions/jobs",
        json={
            "documentId": document_id,
            "passphrase": passphrase,
            "searchTerms": ["Privileged"],
        },
    )
    assert redaction_response.status_code == 200
    result_response = _wait_for_redaction_result(client, redaction_response.json()["jobId"])
    assert result_response.status_code == 200
    redaction_document_id = result_response.json()["documentId"]

    delete_response = client.delete(f"/api/v1/documents/{document_id}")
    assert delete_response.status_code == 200
    assert set(delete_response.json()["deletedDocumentIds"]) == {document_id, redaction_document_id}

    listed_documents = client.get("/api/v1/documents")
    assert listed_documents.status_code == 200
    listed_ids = {item["id"] for item in listed_documents.json()["items"]}
    assert document_id not in listed_ids
    assert redaction_document_id not in listed_ids

    original_detail = client.get(f"/api/v1/documents/{document_id}")
    assert original_detail.status_code == 404
    redaction_detail = client.get(f"/api/v1/documents/{redaction_document_id}")
    assert redaction_detail.status_code == 404

    evidence_response = client.get(f"/api/v1/evidence/{evidence_bundle_id}")
    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()
    assert evidence_payload["bundleId"] == evidence_bundle_id
    assert evidence_payload["documentId"] == document_id
    assert any(event["eventType"] == "document.deleted" for event in evidence_payload["chainOfCustody"])

    evidence_export = client.get(f"/api/v1/evidence/{evidence_bundle_id}/export")
    assert evidence_export.status_code == 200

    db = get_database()
    original_record = db.documents.find_one({"document_id": document_id})
    redaction_record = db.documents.find_one({"document_id": redaction_document_id})
    assert original_record is not None
    assert redaction_record is not None
    assert original_record["status"] == "deleted"
    assert redaction_record["status"] == "deleted"


def test_attempt_authoritative_proof_timeout_fails_closed(monkeypatch, tmp_path):
    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.get_active_artifact_version",
        lambda: ZKPTArtifactVersion(
            profile_id="test-v2",
            profile_class="authoritative",
            proof_boundary="canonical_segment_mask_v1",
            proof_model="full_segment_windows",
            binding_input_name="transformationId",
            artifact_version_id="test-v2",
            circuit_id="zkpt_redaction_v2",
            protocol="plonk",
            artifacts_dir=artifacts_dir,
            wasm_path=wasm_path,
            zkey_path=zkey_path,
            verification_key_path=verification_key_path,
            verification_key_hash="verification-key-hash",
            zkey_hash="zkey-hash",
            toolchain={"snarkjs": "0.7.6"},
            segment_size=1024,
            max_segments=16,
            tree_depth=8,
            max_policy_rules=8,
            snarkjs_bin=snarkjs_path,
        ),
    )
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.build_text_redaction_projection",
        lambda **_: type(
            "Projection",
            (),
            {
                "representation": "canonical_segment_mask_v1",
                "original_bytes": b"original",
                "redacted_bytes": b"redacted",
                "segment_to_term": {0: "privileged"},
                "modified_indices": [0],
            },
        )(),
    )
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.generate_circuit_witness",
        lambda **_: {
            "witness": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            },
            "metadata": {
                "selected_indices": [0],
                "padded_indices": [0],
                "modified_indices": [0],
                "policy_terms_normalized": ["privileged"],
            },
            "verification_data": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            },
        },
    )
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.SnarkjsPlonkProver.prove",
        lambda self, witness: (_ for _ in ()).throw(ZKPTProverError("prover-timeout", "snarkjs command timed out")),
    )

    zkpt_payload, bundle_id = attempt_authoritative_proof(
        original_text="Privileged contract material",
        masked_text="[REDACTED] contract material",
        original_sha256="orig-hash",
        redacted_sha256="redacted-hash",
        redacted_document_id="docr_timeout",
        redaction_job_id="redact_timeout",
        owner_wallet="0x1000000000000000000000000000000000000001",
        search_terms=["Privileged"],
    )

    assert bundle_id is None
    assert zkpt_payload["status"] == "failed"
    assert zkpt_payload["error"]["code"] == "prover-timeout"


def test_attempt_authoritative_proof_deadline_fails_closed(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_PROOF_TIMEOUT_SECONDS", "1")
    reset_settings_cache()

    def slow_attempt(**_: object):
        time.sleep(1.2)
        return {"status": "verified"}, "bundle_id"

    monkeypatch.setattr("blockvault_api.redaction_jobs.attempt_authoritative_proof", slow_attempt)

    zkpt_payload, bundle_id = attempt_authoritative_proof_with_deadline(
        original_text="Privileged material",
        masked_text="[REDACTED] material",
        original_sha256="orig",
        redacted_sha256="redacted",
        redacted_document_id="doc_timeout",
        redaction_job_id="redact_timeout_deadline",
        owner_wallet="0x1000000000000000000000000000000000000001",
        search_terms=["Privileged"],
    )

    assert bundle_id is None
    assert zkpt_payload["status"] == "failed"
    assert zkpt_payload["error"]["code"] == "prover-timeout"
    reset_settings_cache()


def test_attempt_authoritative_proof_marks_non_authoritative_profile_as_unsupported(monkeypatch, tmp_path):
    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.get_active_artifact_version",
        lambda: ZKPTArtifactVersion(
            profile_id="fast-local",
            profile_class="local_smoke",
            proof_boundary="canonical_segment_mask_v1",
            proof_model="full_segment_windows",
            binding_input_name="transformationId",
            artifact_version_id="fast-local",
            circuit_id="zkpt_redaction_v2",
            protocol="plonk",
            artifacts_dir=artifacts_dir,
            wasm_path=wasm_path,
            zkey_path=zkey_path,
            verification_key_path=verification_key_path,
            verification_key_hash="verification-key-hash",
            zkey_hash="zkey-hash",
            toolchain={"snarkjs": "0.7.6"},
            segment_size=1024,
            max_segments=16,
            tree_depth=8,
            max_policy_rules=8,
            snarkjs_bin=snarkjs_path,
        ),
    )

    zkpt_payload, bundle_id = attempt_authoritative_proof(
        original_text="Privileged contract material",
        masked_text="[REDACTED] contract material",
        original_sha256="orig-hash",
        redacted_sha256="redacted-hash",
        redacted_document_id="docr_profile",
        redaction_job_id="redact_profile",
        owner_wallet="0x1000000000000000000000000000000000000001",
        search_terms=["Privileged"],
    )

    assert bundle_id is None
    assert zkpt_payload["status"] == "unsupported"
    assert zkpt_payload["error"]["code"] == "unsupported-profile"
    assert zkpt_payload["profile_id"] == "fast-local"
    assert zkpt_payload["profile_class"] == "local_smoke"
    assert zkpt_payload["prover_backend"] is None




def test_attempt_authoritative_proof_sparse_profile_batches_by_modified_segments(monkeypatch, tmp_path):
    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    artifact = ZKPTArtifactVersion(
        profile_id="v4_sparse",
        profile_class="authoritative",
        proof_boundary="canonical_segment_mask_v1",
        proof_model="sparse_update",
        binding_input_name="documentBindingCommitment",
        artifact_version_id="v4_sparse",
        circuit_id="zkpt_redaction_sparse_v4",
        protocol="plonk",
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash="verification-key-hash",
        zkey_hash="zkey-hash",
        toolchain={"snarkjs": "0.7.6"},
        segment_size=4,
        max_segments=2,
        tree_depth=4,
        max_policy_rules=4,
        snarkjs_bin=snarkjs_path,
    )
    monkeypatch.setattr("blockvault_api.redaction_jobs.get_active_artifact_version", lambda: artifact)

    captured: dict[str, object] = {}

    def fake_generate_circuit_witness(**kwargs):
        captured["proof_model"] = kwargs["proof_model"]
        captured["binding_input_name"] = kwargs["binding_input_name"]
        captured["selected_indices"] = kwargs["selected_indices"]
        return {
            "witness": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "documentBindingCommitment": "44",
            },
            "verification_data": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "documentBindingCommitment": "44",
            },
            "metadata": {
                "proof_model": "sparse_update",
                "selected_indices": kwargs["selected_indices"],
            },
        }

    monkeypatch.setattr("blockvault_api.redaction_jobs.generate_circuit_witness", fake_generate_circuit_witness)
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.SnarkjsPlonkProver.prove",
        lambda self, witness: ProofExecutionResult(
            proof_json={"protocol": "plonk"},
            public_signals=[
                witness["originalRoot"],
                witness["redactedRoot"],
                witness["policyCommitment"],
                witness["documentBindingCommitment"],
            ],
            verified=True,
            witness_hash="witness-hash",
            proof_hash="proof-hash",
            public_signals_hash="public-signals-hash",
            timings={"witness_ms": 5.0, "prove_ms": 50.0, "verify_ms": 2.0},
            backend="test-sparse",
            stdout="ok",
            stderr="",
        ),
    )

    payload, bundle_id = attempt_authoritative_proof(
        original_text="secraaaabbbbsecrccccdddd",
        masked_text="[REDACTED]aaaabbbb[REDACTED]ccccdddd",
        original_sha256="orig-sha",
        redacted_sha256="red-sha",
        redacted_document_id="docr_sparse",
        redaction_job_id="job_sparse",
        owner_wallet="0x1000000000000000000000000000000000000001",
        search_terms=["secr"],
        redaction_manifest={
            "canonical_original_sha256": "canon-orig",
            "canonical_redacted_sha256": "canon-red",
            "source_text_mode": "direct_pdf",
            "engine_name": "blockvault-redactor",
            "engine_version": "0.1.0",
            "render_mode": "raster_overlay",
        },
    )

    assert bundle_id is not None
    assert payload["status"] == "verified"
    assert payload["classification"] == "single_proof_ready"
    assert payload["estimated_shards"] == 1
    assert payload["verified_shards"] == 1
    assert payload["onchain_eligible"] is True
    assert payload["proof_model"] == "sparse_update"
    assert payload["binding_input_name"] == "documentBindingCommitment"
    assert captured == {
        "proof_model": "sparse_update",
        "binding_input_name": "documentBindingCommitment",
        "selected_indices": [0, 3],
    }

    bundle = get_database().zkpt_bundles.find_one({"bundle_id": bundle_id})
    assert bundle is not None
    assert bundle["manifest"]["proofModel"] == "sparse_update"
    assert bundle["manifest"]["bindingInputName"] == "documentBindingCommitment"
    assert bundle["summary"]["proofModel"] == "sparse_update"
    assert bundle["summary"]["bindingInputName"] == "documentBindingCommitment"


def test_select_authoritative_plan_prefers_onchain_safe_profile_for_sparse_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_SAFE_PROFILE", "v3a")
    reset_settings_cache()

    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    active_artifact = ZKPTArtifactVersion(
        profile_id="v4_sparse",
        profile_class="authoritative",
        proof_boundary="canonical_segment_mask_v1",
        proof_model="sparse_update",
        binding_input_name="documentBindingCommitment",
        artifact_version_id="v4_sparse",
        circuit_id="zkpt_redaction_sparse_v4",
        protocol="plonk",
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash="verification-key-hash",
        zkey_hash="zkey-hash",
        toolchain={"snarkjs": "0.7.6"},
        segment_size=256,
        max_segments=4,
        tree_depth=8,
        max_policy_rules=8,
        snarkjs_bin=snarkjs_path,
    )
    onchain_artifact = ZKPTArtifactVersion(
        profile_id="v3a",
        profile_class="authoritative",
        proof_boundary="canonical_segment_mask_v1",
        proof_model="full_segment_windows",
        binding_input_name="transformationId",
        artifact_version_id="v3a",
        circuit_id="zkpt_redaction_v3a",
        protocol="plonk",
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash="verification-key-hash",
        zkey_hash="zkey-hash",
        toolchain={"snarkjs": "0.7.6"},
        segment_size=256,
        max_segments=4,
        tree_depth=8,
        max_policy_rules=8,
        snarkjs_bin=snarkjs_path,
    )

    monkeypatch.setattr("blockvault_api.redaction_jobs.get_active_artifact_version", lambda: active_artifact)
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.get_artifact_version",
        lambda profile_id: onchain_artifact if profile_id == "v3a" else active_artifact,
    )

    plan = select_authoritative_plan(
        original_text="Privileged contract material for BlockVault.",
        search_terms=["Privileged"],
        document_binding={"field": "44"},
        redaction_manifest={"source_text_mode": "direct_pdf"},
    )

    assert plan["artifact"].profile_id == "v3a"
    assert plan["preflight"]["classification"] == "single_proof_ready"
    assert plan["preflight"]["onchainEligible"] is True
    reset_settings_cache()


def test_select_authoritative_plan_keeps_sparse_profile_when_onchain_safe_profile_cannot_fit(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_SAFE_PROFILE", "v3a")
    reset_settings_cache()

    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")

    active_artifact = ZKPTArtifactVersion(
        profile_id="v4_sparse",
        profile_class="authoritative",
        proof_boundary="canonical_segment_mask_v1",
        proof_model="sparse_update",
        binding_input_name="documentBindingCommitment",
        artifact_version_id="v4_sparse",
        circuit_id="zkpt_redaction_sparse_v4",
        protocol="plonk",
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash="verification-key-hash",
        zkey_hash="zkey-hash",
        toolchain={"snarkjs": "0.7.6"},
        segment_size=256,
        max_segments=4,
        tree_depth=8,
        max_policy_rules=8,
        snarkjs_bin=snarkjs_path,
    )
    onchain_artifact = ZKPTArtifactVersion(
        profile_id="v3a",
        profile_class="authoritative",
        proof_boundary="canonical_segment_mask_v1",
        proof_model="full_segment_windows",
        binding_input_name="transformationId",
        artifact_version_id="v3a",
        circuit_id="zkpt_redaction_v3a",
        protocol="plonk",
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash="verification-key-hash",
        zkey_hash="zkey-hash",
        toolchain={"snarkjs": "0.7.6"},
        segment_size=8,
        max_segments=1,
        tree_depth=8,
        max_policy_rules=8,
        snarkjs_bin=snarkjs_path,
    )

    monkeypatch.setattr("blockvault_api.redaction_jobs.get_active_artifact_version", lambda: active_artifact)
    monkeypatch.setattr(
        "blockvault_api.redaction_jobs.get_artifact_version",
        lambda profile_id: onchain_artifact if profile_id == "v3a" else active_artifact,
    )

    plan = select_authoritative_plan(
        original_text="Privileged contract material for BlockVault.",
        search_terms=["Privileged"],
        document_binding={"field": "44"},
        redaction_manifest={"source_text_mode": "direct_pdf"},
    )

    assert plan["artifact"].profile_id == "v4_sparse"
    assert plan["preflight"]["classification"] == "verified_bundle_only"
    assert plan["preflight"]["onchainEligible"] is False
    reset_settings_cache()
