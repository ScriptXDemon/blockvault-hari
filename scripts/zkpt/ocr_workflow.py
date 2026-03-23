from __future__ import annotations

import argparse
import base64
import io
import json
import time
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


REPO_ROOT = Path(__file__).resolve().parents[2]


def encrypt_payload(payload: bytes, passphrase: str) -> tuple[bytes, str, str]:
    salt = b"0123456789abcdef"
    iv = b"redact-dociv"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    key = kdf.derive(passphrase.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(iv, payload, None)
    return ciphertext, base64.b64encode(salt).decode("utf-8"), base64.b64encode(iv).decode("utf-8")


def request_json(session: requests.Session, method: str, url: str, **kwargs) -> dict[str, object]:
    attempts = 3
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.request(method, url, timeout=30, **kwargs)
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise RuntimeError(f"{method} {url} failed after {attempts} attempts: {exc}") from exc
            time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"{method} {url} failed unexpectedly: {last_error}")
    if not response.ok:
        raise RuntimeError(f"{method} {url} failed with {response.status_code}: {response.text}")
    return response.json()


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


def make_scanned_pdf(text: str) -> bytes:
    image = Image.new("RGB", (1800, 1200), color="white")
    draw = ImageDraw.Draw(image)
    font = None
    for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if candidate.exists():
            font = ImageFont.truetype(str(candidate), 52)
            break
    if font is None:
        font = ImageFont.load_default()

    wrapped = textwrap.fill(text, width=34)
    draw.multiline_text((100, 120), wrapped, fill="black", spacing=32, font=font)

    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    pdf_buffer = io.BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=letter)
    page_width, page_height = letter
    pdf.drawImage(ImageReader(image_buffer), 36, 72, width=page_width - 72, height=page_height - 144, preserveAspectRatio=True)
    pdf.save()
    pdf_buffer.seek(0)
    return pdf_buffer.read()


def default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "output" / "zkpt" / f"ocr-workflow-{timestamp}.json"


def run_ocr_workflow(
    *,
    api_base_url: str,
    wallet_address: str,
    display_name: str,
    passphrase: str,
    ocr_text: str,
    search_term: str,
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

    case_payload = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/cases",
        json={"title": f"OCR Validation {int(time.time())}", "description": "Live OCR workflow check"},
    )

    scanned_pdf_bytes = make_scanned_pdf(ocr_text)
    encrypted_bytes, salt_b64, iv_b64 = encrypt_payload(scanned_pdf_bytes, passphrase)

    init_payload = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/documents/init-upload",
        params={"caseId": case_payload["id"]},
        json={"originalName": "ocr-source.pdf", "contentType": "application/pdf", "size": len(scanned_pdf_bytes)},
    )

    upload_response = session.post(
        f"{api_base_url}/api/v1/documents/{init_payload['documentId']}/complete-upload",
        files={"encrypted_file": ("ocr-source.pdf.bv", encrypted_bytes, "application/octet-stream")},
        data={"algorithm": "AES-GCM/PBKDF2-SHA256", "salt_b64": salt_b64, "iv_b64": iv_b64},
    )
    if not upload_response.ok:
        raise RuntimeError(
            f"document complete-upload failed with {upload_response.status_code}: {upload_response.text}"
        )

    notarize_payload = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/documents/{init_payload['documentId']}/notarize",
        json={"passphrase": passphrase},
    )

    evidence_export = session.get(f"{api_base_url}/api/v1/evidence/{notarize_payload['evidenceBundleId']}/export")
    if not evidence_export.ok:
        raise RuntimeError(f"evidence export failed with {evidence_export.status_code}: {evidence_export.text}")
    with zipfile.ZipFile(io.BytesIO(evidence_export.content)) as archive:
        evidence_entries = sorted(archive.namelist())

    redaction_submit = request_json(
        session,
        "POST",
        f"{api_base_url}/api/v1/redactions/jobs",
        json={"documentId": init_payload["documentId"], "passphrase": passphrase, "searchTerms": [search_term]},
    )
    job_payload, result_payload = poll_redaction_result(
        session=session,
        api_base_url=api_base_url,
        job_id=str(redaction_submit["jobId"]),
        timeout_seconds=poll_timeout_seconds,
    )
    if not result_payload["verification_passed"]:
        raise RuntimeError(f"OCR redaction completed without verified proof: {json.dumps(result_payload['zkpt'])}")
    if result_payload.get("source_text_mode") != "ocr_assisted":
        raise RuntimeError(
            f"Expected inline OCR-assisted redaction but got {result_payload.get('source_text_mode')}: {json.dumps(result_payload)}"
        )

    zkpt_bundle_id = result_payload["zkpt"]["bundle_id"]
    zkpt_export = session.get(f"{api_base_url}/api/v1/zkpt/bundles/{zkpt_bundle_id}/export")
    if not zkpt_export.ok:
        raise RuntimeError(f"zkpt export failed with {zkpt_export.status_code}: {zkpt_export.text}")
    with zipfile.ZipFile(io.BytesIO(zkpt_export.content)) as archive:
        zkpt_entries = sorted(archive.namelist())

    total_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "apiBaseUrl": api_base_url,
        "user": login["user"],
        "case": case_payload,
        "sourceDocumentId": init_payload["documentId"],
        "evidenceBundleId": notarize_payload["evidenceBundleId"],
        "redactionJob": job_payload,
        "redactionResult": result_payload,
        "evidenceExportEntries": evidence_entries,
        "zkptExportEntries": zkpt_entries,
        "timings": {
            "totalMs": total_ms,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live scanned-PDF -> inline OCR redaction workflow against the BlockVault API.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--wallet-address", default="0x1000000000000000000000000000000000000001")
    parser.add_argument("--display-name", default="OCR Check")
    parser.add_argument("--passphrase", default="correct horse battery staple")
    parser.add_argument("--search-term", default="confidential")
    parser.add_argument(
        "--ocr-text",
        default="Confidential OCR memorandum for BlockVault.\nThis scanned exhibit should redact directly through inline OCR before authoritative proof generation.",
    )
    parser.add_argument("--poll-timeout-seconds", type=int, default=240)
    parser.add_argument("--output")
    parser.add_argument("--stdout-only", action="store_true")
    args = parser.parse_args()

    report = run_ocr_workflow(
        api_base_url=args.api_base_url.rstrip("/"),
        wallet_address=args.wallet_address,
        display_name=args.display_name,
        passphrase=args.passphrase,
        ocr_text=args.ocr_text,
        search_term=args.search_term,
        poll_timeout_seconds=args.poll_timeout_seconds,
    )
    payload = json.dumps(report, indent=2)
    if args.stdout_only:
        print(payload)
        return 0

    output_path = Path(args.output).resolve() if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload + "\n", encoding="utf-8")
    print(f"Wrote OCR workflow report to {output_path}")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
