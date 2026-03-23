from __future__ import annotations

import argparse
import base64
import io
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests import exceptions as requests_exceptions
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


REPO_ROOT = Path(__file__).resolve().parents[2]


def make_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.drawString(72, 720, text)
    pdf.save()
    buffer.seek(0)
    return buffer.read()


def encrypt_payload(payload: bytes, passphrase: str) -> tuple[bytes, str, str]:
    salt = b"0123456789abcdef"
    iv = b"redact-dociv"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    key = kdf.derive(passphrase.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(iv, payload, None)
    return ciphertext, base64.b64encode(salt).decode("utf-8"), base64.b64encode(iv).decode("utf-8")


def default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "output" / "zkpt" / f"live-workflow-{timestamp}.json"


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = 3,
    retry_delay_seconds: float = 1.5,
    **kwargs,
) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.request(method, url, **kwargs)
            if not response.ok:
                raise RuntimeError(f"{method} {url} failed with {response.status_code}: {response.text}")
            return response.json()
        except (requests_exceptions.ConnectionError, requests_exceptions.Timeout) as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(retry_delay_seconds)
    raise RuntimeError(f"{method} {url} failed after {retries} attempts: {last_error}")


def poll_redaction_result(
    *,
    session: requests.Session,
    api_base_url: str,
    job_id: str,
    timeout_seconds: int,
) -> tuple[dict[str, object], dict[str, object]]:
    deadline = time.monotonic() + timeout_seconds
    latest_job: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest_job = request_json(session, "GET", f"{api_base_url}/api/v1/redactions/jobs/{job_id}")
        if latest_job["status"] == "completed":
            result = request_json(session, "GET", f"{api_base_url}/api/v1/redactions/jobs/{job_id}/result")
            return latest_job, result
        if latest_job["status"] == "failed":
            raise RuntimeError(
                f"Redaction job failed: {latest_job.get('errorCode')} {latest_job.get('errorMessage')}"
            )
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for redaction job {job_id}; last status: {latest_job}")


def run_live_workflow(
    *,
    api_base_url: str,
    wallet_address: str,
    display_name: str,
    passphrase: str,
    search_term: str,
    document_text: str,
    poll_timeout_seconds: int,
) -> dict[str, object]:
    session = requests.Session()
    started = time.perf_counter()

    login = request_json(
        session,
        "POST",
        f"{api_base_url}/api/auth/test-login",
        json={"walletAddress": wallet_address, "displayName": display_name},
    )

    case_created_at = time.perf_counter()
    case_payload = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/cases",
        json={"title": f"Latency Validation {int(time.time())}", "description": "Live authoritative workflow check"},
    )
    case_ms = round((time.perf_counter() - case_created_at) * 1000, 3)

    pdf_bytes = make_pdf(document_text)
    encrypted_bytes, salt_b64, iv_b64 = encrypt_payload(pdf_bytes, passphrase)

    init_started = time.perf_counter()
    init_payload = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/documents/init-upload",
        params={"caseId": case_payload["id"]},
        json={"originalName": "latency-check.pdf", "contentType": "application/pdf", "size": len(pdf_bytes)},
    )
    init_ms = round((time.perf_counter() - init_started) * 1000, 3)

    upload_started = time.perf_counter()
    complete_response = session.post(
        f"{api_base_url}/api/v1/documents/{init_payload['documentId']}/complete-upload",
        files={"encrypted_file": ("latency-check.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={"algorithm": "AES-GCM/PBKDF2-SHA256", "salt_b64": salt_b64, "iv_b64": iv_b64},
    )
    if not complete_response.ok:
        raise RuntimeError(
            f"document complete-upload failed with {complete_response.status_code}: {complete_response.text}"
        )
    upload_ms = round((time.perf_counter() - upload_started) * 1000, 3)

    notarize_started = time.perf_counter()
    notarize_payload = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/documents/{init_payload['documentId']}/notarize",
        json={"passphrase": passphrase},
    )
    notarize_ms = round((time.perf_counter() - notarize_started) * 1000, 3)

    evidence_export_started = time.perf_counter()
    evidence_export = session.get(f"{api_base_url}/api/v1/evidence/{notarize_payload['evidenceBundleId']}/export")
    if not evidence_export.ok:
        raise RuntimeError(
            f"evidence export failed with {evidence_export.status_code}: {evidence_export.text}"
        )
    evidence_export_ms = round((time.perf_counter() - evidence_export_started) * 1000, 3)
    with zipfile.ZipFile(io.BytesIO(evidence_export.content)) as archive:
        evidence_entries = sorted(archive.namelist())

    redact_submit_started = time.perf_counter()
    redaction_submit = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/redactions/jobs",
        json={"documentId": init_payload["documentId"], "passphrase": passphrase, "searchTerms": [search_term]},
    )
    redact_submit_ms = round((time.perf_counter() - redact_submit_started) * 1000, 3)

    poll_started = time.perf_counter()
    job_payload, result_payload = poll_redaction_result(
        session=session,
        api_base_url=api_base_url,
        job_id=str(redaction_submit["jobId"]),
        timeout_seconds=poll_timeout_seconds,
    )
    poll_ms = round((time.perf_counter() - poll_started) * 1000, 3)

    if not result_payload["verification_passed"]:
        raise RuntimeError(f"Redaction completed without verified proof: {json.dumps(result_payload['zkpt'])}")

    zkpt_bundle_id = result_payload["zkpt"]["bundle_id"]
    export_started = time.perf_counter()
    zkpt_export = session.get(f"{api_base_url}/api/v1/zkpt/bundles/{zkpt_bundle_id}/export")
    if not zkpt_export.ok:
        raise RuntimeError(f"zkpt export failed with {zkpt_export.status_code}: {zkpt_export.text}")
    zkpt_export_ms = round((time.perf_counter() - export_started) * 1000, 3)
    with zipfile.ZipFile(io.BytesIO(zkpt_export.content)) as archive:
        zkpt_entries = sorted(archive.namelist())

    total_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "apiBaseUrl": api_base_url,
        "user": login["user"],
        "case": case_payload,
        "documentId": init_payload["documentId"],
        "evidenceBundleId": notarize_payload["evidenceBundleId"],
        "redactionJob": job_payload,
        "redactionResult": result_payload,
        "evidenceExportEntries": evidence_entries,
        "zkptExportEntries": zkpt_entries,
        "timings": {
            "caseMs": case_ms,
            "initUploadMs": init_ms,
            "completeUploadMs": upload_ms,
            "notarizeMs": notarize_ms,
            "evidenceExportMs": evidence_export_ms,
            "submitRedactionMs": redact_submit_ms,
            "pollToResultMs": poll_ms,
            "zkptExportMs": zkpt_export_ms,
            "totalMs": total_ms,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live BlockVault packaged-stack workflow against the public API.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--wallet-address", default="0x1000000000000000000000000000000000000001")
    parser.add_argument("--display-name", default="Latency Check")
    parser.add_argument("--passphrase", default="correct horse battery staple")
    parser.add_argument("--search-term", default="privileged")
    parser.add_argument(
        "--document-text",
        default="BlockVault privileged legal memorandum for authoritative latency validation.",
    )
    parser.add_argument("--poll-timeout-seconds", type=int, default=240)
    parser.add_argument("--output")
    parser.add_argument("--stdout-only", action="store_true")
    args = parser.parse_args()

    report = run_live_workflow(
        api_base_url=args.api_base_url.rstrip("/"),
        wallet_address=args.wallet_address,
        display_name=args.display_name,
        passphrase=args.passphrase,
        search_term=args.search_term,
        document_text=args.document_text,
        poll_timeout_seconds=args.poll_timeout_seconds,
    )
    payload = json.dumps(report, indent=2)
    if args.stdout_only:
        print(payload)
        return 0

    output_path = Path(args.output).resolve() if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload + "\n", encoding="utf-8")
    print(f"Wrote live workflow report to {output_path}")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
