from __future__ import annotations

import io

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from blockvault_api.crypto import sha256_hex
from blockvault_api.ocr import extract_searchable_pdf_layout
from blockvault_api.redaction_engine import run_rust_redaction_engine


def _make_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.drawString(72, 720, text)
    pdf.save()
    buffer.seek(0)
    return buffer.read()


def test_direct_searchable_pdf_redaction_preserves_layout_via_overlay():
    pdf_bytes = _make_pdf("Privileged contract material for BlockVault.")
    layout = extract_searchable_pdf_layout(pdf_bytes)

    result = run_rust_redaction_engine(
        pdf_bytes=pdf_bytes,
        normalized_terms=["privileged"],
        source_pdf_sha256=sha256_hex(pdf_bytes),
        searchable_layout=layout.layout,
        page_images=[
            {
                "page_index": page.page_index,
                "image_bytes": page.image_bytes,
                "image_width": page.image_width,
                "image_height": page.image_height,
                "content_type": page.content_type,
            }
            for page in layout.page_images
        ],
    )

    assert result.redacted_pdf_bytes.startswith(b"%PDF")
    assert result.manifest["source_text_mode"] == "direct_pdf"
    assert result.manifest["ocr_used"] is False
    assert result.manifest["render_mode"] == "raster_overlay"
    assert result.manifest["matched_regions"]
