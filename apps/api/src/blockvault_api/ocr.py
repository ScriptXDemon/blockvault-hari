from __future__ import annotations

import io
import json
from importlib.metadata import version as package_version
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfReader

_OCR_IMPORT_ERROR: Exception | None = None
try:
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
except Exception as exc:  # pragma: no cover - exercised via runtime status if deps are missing
    np = None
    pdfium = None
    RapidOCR = None
    ImageReader = None
    canvas = None
    _OCR_IMPORT_ERROR = exc

from .config import get_settings
from .crypto import sha256_hex


class OcrProcessingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OcrPageImage:
    page_index: int
    image_bytes: bytes
    image_width: int
    image_height: int
    content_type: str = "image/png"


@dataclass(frozen=True)
class OcrConversionResult:
    searchable_pdf_bytes: bytes
    extracted_text: str
    page_count: int
    engine_name: str
    engine_version: str | None
    canonical_text: str | None = None
    working_searchable_pdf_sha256: str | None = None
    canonical_text_sha256: str | None = None
    layout_sha256: str | None = None
    layout: dict[str, Any] | None = None
    page_images: list[OcrPageImage] = field(default_factory=list)


@dataclass(frozen=True)
class SearchablePdfLayoutResult:
    canonical_text: str
    page_count: int
    engine_name: str
    engine_version: str | None
    layout_sha256: str
    layout: dict[str, Any]
    page_images: list[OcrPageImage] = field(default_factory=list)


def get_ocr_runtime_status() -> dict[str, object]:
    settings = get_settings()
    if not settings.ocr_enabled:
        return {
            "enabled": False,
            "ready": False,
            "engine": "rapidocr_onnxruntime",
            "version": None,
            "error": "OCR support is disabled",
        }
    if _OCR_IMPORT_ERROR is not None or RapidOCR is None:
        return {
            "enabled": True,
            "ready": False,
            "engine": "rapidocr_onnxruntime",
            "version": None,
            "error": str(_OCR_IMPORT_ERROR),
        }
    try:
        ocr = RapidOCR()
        return {
            "enabled": True,
            "ready": True,
            "engine": "rapidocr_onnxruntime",
            "version": package_version("rapidocr_onnxruntime"),
            "error": None,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "ready": False,
            "engine": "rapidocr_onnxruntime",
            "version": None,
            "error": str(exc),
        }


def _polygon_bounds(polygon: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _page_blocks_from_ocr(result: list[list[Any]], min_confidence: float) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for item in result:
        if len(item) != 3:
            continue
        polygon, text, confidence = item
        if not isinstance(text, str) or not text.strip():
            continue
        confidence_value = float(confidence)
        if confidence_value < min_confidence:
            continue
        bounds = _polygon_bounds(polygon)
        accepted.append(
            {
                "text": text.strip(),
                "confidence": confidence_value,
                "polygon": [[float(point[0]), float(point[1])] for point in polygon],
                "bounds": {
                    "x0": float(bounds[0]),
                    "y0": float(bounds[1]),
                    "x1": float(bounds[2]),
                    "y1": float(bounds[3]),
                },
            }
        )
    accepted.sort(key=lambda item: (item["bounds"]["y0"], item["bounds"]["x0"]))
    for index, item in enumerate(accepted):
        item["blockIndex"] = index
    return accepted


def _page_blocks_from_pdf_textpage(page: Any, image_width: int, image_height: int) -> list[dict[str, Any]]:
    text_page = page.get_textpage()
    page_width, page_height = page.get_size()
    x_scale = image_width / max(page_width, 1)
    y_scale = image_height / max(page_height, 1)
    blocks: list[dict[str, Any]] = []
    for rect_index in range(text_page.count_rects()):
        left, bottom, right, top = text_page.get_rect(rect_index)
        text = _normalize_text(
            text_page.get_text_bounded(left=left, bottom=bottom, right=right, top=top).strip()
        )
        if not text:
            continue
        blocks.append(
            {
                "text": text,
                "confidence": 1.0,
                "polygon": [],
                "bounds": {
                    "x0": float(left * x_scale),
                    "y0": float(image_height - (top * y_scale)),
                    "x1": float(right * x_scale),
                    "y1": float(image_height - (bottom * y_scale)),
                },
            }
        )
    blocks.sort(key=lambda item: (item["bounds"]["y0"], item["bounds"]["x0"]))
    for index, item in enumerate(blocks):
        item["blockIndex"] = index
    return blocks


def _draw_hidden_text(
    pdf: Any,
    text_blocks: list[dict[str, Any]],
    *,
    page_width: float,
    page_height: float,
    image_width: int,
    image_height: int,
) -> None:
    pdf.saveState()
    if hasattr(pdf, "setFillAlpha"):
        pdf.setFillAlpha(0)
    else:
        pdf.setFillColorRGB(1, 1, 1)

    x_scale = page_width / max(image_width, 1)
    y_scale = page_height / max(image_height, 1)
    for block in text_blocks:
        bounds = block["bounds"]
        text = str(block["text"])
        x0 = float(bounds["x0"])
        y0 = float(bounds["y0"])
        x1 = float(bounds["x1"])
        y1 = float(bounds["y1"])
        font_size = max((y1 - y0) * y_scale * 0.9, 6)
        pdf_x = x0 * x_scale
        pdf_y = max(page_height - (y1 * y_scale), 0)
        pdf.setFont("Helvetica", font_size)
        pdf.drawString(pdf_x, pdf_y, text)
    pdf.restoreState()


def _verify_searchable_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    extracted = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    if not extracted:
        raise OcrProcessingError("ocr-output-not-searchable", "OCR output PDF did not contain an extractable text layer")
    return extracted


def ocr_pdf_to_searchable(pdf_bytes: bytes) -> OcrConversionResult:
    settings = get_settings()
    runtime = get_ocr_runtime_status()
    if not runtime["enabled"]:
        raise OcrProcessingError("ocr-disabled", "OCR support is disabled")
    if not runtime["ready"]:
        raise OcrProcessingError("ocr-runtime-unavailable", "OCR runtime is unavailable")

    document = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    if len(document) == 0:
        raise OcrProcessingError("ocr-empty-document", "Document contained no pages")

    ocr = RapidOCR()
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    aggregated_page_text: list[str] = []
    total_matches = 0
    layout_pages: list[dict[str, Any]] = []
    page_images: list[OcrPageImage] = []

    for page_index in range(len(document)):
        page = document[page_index]
        page_width, page_height = page.get_size()
        bitmap = page.render(scale=settings.ocr_render_scale)
        image = bitmap.to_pil()
        image_width, image_height = image.size
        ocr_result, _ = ocr(np.array(image))
        text_blocks = _page_blocks_from_ocr(ocr_result or [], settings.ocr_min_confidence)
        page_text = _normalize_text("\n".join(str(block["text"]) for block in text_blocks).strip())
        if page_text:
            aggregated_page_text.append(page_text)
        total_matches += len(text_blocks)
        layout_pages.append(
            {
                "pageIndex": page_index,
                "pageWidth": float(page_width),
                "pageHeight": float(page_height),
                "imageWidth": int(image_width),
                "imageHeight": int(image_height),
                "blocks": text_blocks,
            }
        )
        image_buffer = io.BytesIO()
        image.save(image_buffer, format="PNG")
        page_images.append(
            OcrPageImage(
                page_index=page_index,
                image_bytes=image_buffer.getvalue(),
                image_width=image_width,
                image_height=image_height,
            )
        )

        pdf.setPageSize((page_width, page_height))
        pdf.drawImage(ImageReader(image), 0, 0, width=page_width, height=page_height)
        if text_blocks:
            _draw_hidden_text(
                pdf,
                text_blocks,
                page_width=page_width,
                page_height=page_height,
                image_width=image_width,
                image_height=image_height,
            )
        pdf.showPage()

    pdf.save()
    searchable_pdf_bytes = output.getvalue()
    extracted_text = _verify_searchable_text(searchable_pdf_bytes)
    canonical_text = _normalize_text("\n\n".join(page_text for page_text in aggregated_page_text if page_text).strip())

    if not extracted_text or not canonical_text or total_matches == 0:
        raise OcrProcessingError(
            "ocr-no-text-detected",
            "OCR could not detect sufficient text to create a searchable PDF",
        )

    layout = {
        "layoutVersion": 1,
        "engine": "rapidocr_onnxruntime",
        "engineVersion": runtime["version"],
        "pageCount": len(document),
        "pages": layout_pages,
    }
    working_searchable_pdf_sha256 = sha256_hex(searchable_pdf_bytes)
    canonical_text_sha256 = sha256_hex(canonical_text.encode("utf-8"))
    layout_sha256 = sha256_hex(_canonical_json_bytes(layout))

    return OcrConversionResult(
        searchable_pdf_bytes=searchable_pdf_bytes,
        extracted_text=extracted_text,
        page_count=len(document),
        engine_name="rapidocr_onnxruntime",
        engine_version=runtime["version"],
        canonical_text=canonical_text,
        working_searchable_pdf_sha256=working_searchable_pdf_sha256,
        canonical_text_sha256=canonical_text_sha256,
        layout_sha256=layout_sha256,
        layout=layout,
        page_images=page_images,
    )


def extract_searchable_pdf_layout(pdf_bytes: bytes) -> SearchablePdfLayoutResult:
    if _OCR_IMPORT_ERROR is not None or pdfium is None:
        raise OcrProcessingError("pdf-layout-runtime-unavailable", "PDF layout runtime is unavailable")

    document = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    if len(document) == 0:
        raise OcrProcessingError("pdf-layout-empty-document", "Document contained no pages")

    layout_pages: list[dict[str, Any]] = []
    page_images: list[OcrPageImage] = []
    aggregated_page_text: list[str] = []

    for page_index in range(len(document)):
        page = document[page_index]
        page_width, page_height = page.get_size()
        bitmap = page.render(scale=get_settings().ocr_render_scale)
        image = bitmap.to_pil()
        image_width, image_height = image.size
        text_blocks = _page_blocks_from_pdf_textpage(page, image_width, image_height)
        page_text = _normalize_text("\n".join(str(block["text"]) for block in text_blocks).strip())
        if page_text:
            aggregated_page_text.append(page_text)
        layout_pages.append(
            {
                "pageIndex": page_index,
                "pageWidth": float(page_width),
                "pageHeight": float(page_height),
                "imageWidth": int(image_width),
                "imageHeight": int(image_height),
                "blocks": text_blocks,
            }
        )
        image_buffer = io.BytesIO()
        image.save(image_buffer, format="PNG")
        page_images.append(
            OcrPageImage(
                page_index=page_index,
                image_bytes=image_buffer.getvalue(),
                image_width=image_width,
                image_height=image_height,
            )
        )

    canonical_text = _normalize_text("\n\n".join(page_text for page_text in aggregated_page_text if page_text).strip())
    if not canonical_text:
        raise OcrProcessingError(
            "pdf-layout-no-text-detected",
            "Could not extract positioned text blocks from the searchable PDF",
        )

    try:
        engine_version = package_version("pypdfium2")
    except Exception:
        engine_version = None

    layout = {
        "layoutVersion": 1,
        "engine": "pypdfium2_textpage",
        "engineVersion": engine_version,
        "pageCount": len(document),
        "pages": layout_pages,
    }
    layout_sha256 = sha256_hex(_canonical_json_bytes(layout))
    return SearchablePdfLayoutResult(
        canonical_text=canonical_text,
        page_count=len(document),
        engine_name="pypdfium2_textpage",
        engine_version=engine_version,
        layout_sha256=layout_sha256,
        layout=layout,
        page_images=page_images,
    )
