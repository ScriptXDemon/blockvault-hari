use std::fs;
use std::fs::File;
use std::io::{BufReader, BufWriter};
use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand, ValueEnum};
use printpdf::image_crate::codecs::png::PngDecoder;
use printpdf::path::{PaintMode, WindingOrder};
use printpdf::{
    BuiltinFont, Color, Greyscale, Image, ImageTransform, Mm, PdfDocument, Point, Polygon,
};
use regex::RegexBuilder;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const REDACTION_TOKEN: &str = "[REDACTED]";
const ENGINE_NAME: &str = "blockvault-redactor";
const ENGINE_MODE: &str = "rust_cli";
const POINTS_TO_MM: f32 = 25.4 / 72.0;
const IMAGE_DPI: f32 = 300.0;

#[derive(Parser)]
#[command(name = "blockvault-redactor")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Run {
        #[arg(long)]
        input: PathBuf,
        #[arg(long = "output-dir")]
        output_dir: PathBuf,
        #[arg(long = "terms-json")]
        terms_json: String,
        #[arg(long = "source-mode", default_value = "searchable-pdf")]
        source_mode: SourceMode,
        #[arg(long = "searchable-layout-json")]
        searchable_layout_json: Option<PathBuf>,
        #[arg(long = "ocr-layout-json")]
        ocr_layout_json: Option<PathBuf>,
        #[arg(long = "page-images-dir")]
        page_images_dir: Option<PathBuf>,
        #[arg(long = "working-searchable-pdf")]
        working_searchable_pdf: Option<PathBuf>,
    },
    VersionJson,
}

#[derive(Debug, Clone, Serialize, Deserialize, ValueEnum, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum SourceMode {
    SearchablePdf,
    OcrLayout,
}

impl SourceMode {
    fn as_manifest_value(&self) -> &'static str {
        match self {
            Self::SearchablePdf => "direct_pdf",
            Self::OcrLayout => "ocr_assisted",
        }
    }

    fn render_mode(&self) -> &'static str {
        match self {
            Self::SearchablePdf => "text_reflow",
            Self::OcrLayout => "raster_overlay",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct MatchSpan {
    term: String,
    start: usize,
    end: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Bounds {
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct OcrBlock {
    #[serde(rename = "blockIndex")]
    block_index: usize,
    text: String,
    confidence: f64,
    polygon: Vec<Vec<f64>>,
    bounds: Bounds,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct OcrPageLayout {
    #[serde(rename = "pageIndex")]
    page_index: usize,
    #[serde(rename = "pageWidth")]
    page_width: f64,
    #[serde(rename = "pageHeight")]
    page_height: f64,
    #[serde(rename = "imageWidth")]
    image_width: usize,
    #[serde(rename = "imageHeight")]
    image_height: usize,
    blocks: Vec<OcrBlock>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct OcrLayout {
    #[serde(rename = "layoutVersion")]
    layout_version: u32,
    engine: String,
    #[serde(rename = "engineVersion")]
    engine_version: Option<String>,
    #[serde(rename = "pageCount")]
    page_count: usize,
    pages: Vec<OcrPageLayout>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct MatchedRegion {
    #[serde(rename = "pageIndex")]
    page_index: usize,
    #[serde(rename = "blockIndex")]
    block_index: usize,
    term: String,
    text: String,
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Manifest {
    engine_name: String,
    engine_version: String,
    engine_mode: String,
    searchable_text_confirmed: bool,
    source_pdf_sha256: String,
    canonical_original_sha256: String,
    canonical_redacted_sha256: String,
    redacted_pdf_sha256: String,
    matched_terms: Vec<String>,
    matched_spans: Vec<MatchSpan>,
    source_text_mode: String,
    ocr_used: bool,
    ocr_engine: Option<String>,
    ocr_engine_version: Option<String>,
    ocr_layout_sha256: Option<String>,
    working_searchable_pdf_sha256: Option<String>,
    render_mode: String,
    matched_regions: Vec<MatchedRegion>,
}

#[derive(Debug, Clone, Serialize)]
struct VersionInfo {
    engine_name: String,
    engine_version: String,
    engine_mode: String,
}

#[derive(Debug, Clone)]
struct RedactionArtifacts {
    canonical_original: String,
    canonical_redacted: String,
    matched_spans: Vec<MatchSpan>,
    matched_regions: Vec<MatchedRegion>,
    ocr_engine: Option<String>,
    ocr_engine_version: Option<String>,
    ocr_layout_sha256: Option<String>,
    working_searchable_pdf_sha256: Option<String>,
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn normalize_text(text: &str) -> String {
    text.replace("\r\n", "\n").replace('\r', "\n")
}

fn points_to_mm(value: f64) -> Mm {
    Mm((value as f32) * POINTS_TO_MM)
}

fn image_size_mm(pixels: usize) -> f32 {
    (pixels as f32) * 25.4 / IMAGE_DPI
}

fn render_text_reflow_pdf(path: &Path, text: &str) -> Result<(), String> {
    let (doc, page1, layer1) =
        PdfDocument::new("BlockVault Redacted Output", Mm(210.0), Mm(297.0), "Layer 1");
    let layer = doc.get_page(page1).get_layer(layer1);
    let font = doc
        .add_builtin_font(BuiltinFont::Helvetica)
        .map_err(|err| format!("failed to add built-in font: {err}"))?;

    let mut y = 285.0_f32;
    let line_height = 6.5_f32;
    for line in text.lines() {
        let printable = if line.is_empty() { " " } else { line };
        layer.use_text(printable, 10.0, Mm(12.0), Mm(y), &font);
        y -= line_height;
        if y < 15.0_f32 {
            break;
        }
    }

    let file = File::create(path).map_err(|err| format!("failed to create redacted PDF: {err}"))?;
    let mut writer = BufWriter::new(file);
    doc.save(&mut writer)
        .map_err(|err| format!("failed to save redacted PDF: {err}"))?;
    Ok(())
}

fn build_rectangle(bounds: &Bounds, page: &OcrPageLayout) -> Polygon {
    let x_scale = page.page_width / page.image_width as f64;
    let y_scale = page.page_height / page.image_height as f64;

    let x0 = bounds.x0 * x_scale;
    let x1 = bounds.x1 * x_scale;
    let y0 = page.page_height - (bounds.y1 * y_scale);
    let y1 = page.page_height - (bounds.y0 * y_scale);

    Polygon {
        rings: vec![vec![
            (Point::new(points_to_mm(x0), points_to_mm(y0)), false),
            (Point::new(points_to_mm(x1), points_to_mm(y0)), false),
            (Point::new(points_to_mm(x1), points_to_mm(y1)), false),
            (Point::new(points_to_mm(x0), points_to_mm(y1)), false),
        ]],
        mode: PaintMode::Fill,
        winding_order: WindingOrder::NonZero,
    }
}

fn page_image_path(images_dir: &Path, page_index: usize) -> Result<PathBuf, String> {
    let png = images_dir.join(format!("page-{page_index:04}.png"));
    if png.exists() {
        return Ok(png);
    }
    let jpg = images_dir.join(format!("page-{page_index:04}.jpg"));
    if jpg.exists() {
        return Ok(jpg);
    }
    Err(format!("missing raster image for OCR page {page_index}"))
}

fn render_raster_overlay_pdf(
    path: &Path,
    layout: &OcrLayout,
    matched_regions: &[MatchedRegion],
    page_images_dir: &Path,
) -> Result<(), String> {
    let first_page = layout
        .pages
        .first()
        .ok_or_else(|| "ocr-layout-empty".to_string())?;
    let (doc, page1, layer1) = PdfDocument::new(
        "BlockVault OCR Redacted Output",
        points_to_mm(first_page.page_width),
        points_to_mm(first_page.page_height),
        "Layer 1",
    );

    for (index, page) in layout.pages.iter().enumerate() {
        let (page_ref, layer_ref) = if index == 0 {
            (page1, layer1)
        } else {
            doc.add_page(
                points_to_mm(page.page_width),
                points_to_mm(page.page_height),
                format!("Layer {}", index + 1),
            )
        };
        let layer = doc.get_page(page_ref).get_layer(layer_ref);
        let image_path = page_image_path(page_images_dir, page.page_index)?;
        let image_file = File::open(&image_path)
            .map_err(|err| format!("failed to open OCR page image '{}': {err}", image_path.display()))?;
        let mut reader = BufReader::new(image_file);
        let decoder = PngDecoder::new(&mut reader)
            .map_err(|err| format!("failed to decode OCR page image '{}': {err}", image_path.display()))?;
        let image = Image::try_from(decoder)
            .map_err(|err| format!("failed to create PDF image for OCR page '{}': {err}", image_path.display()))?;
        image.add_to_layer(
            layer.clone(),
            ImageTransform {
                translate_x: Some(Mm(0.0)),
                translate_y: Some(Mm(0.0)),
                rotate: None,
                scale_x: Some(points_to_mm(page.page_width).0 / image_size_mm(page.image_width)),
                scale_y: Some(points_to_mm(page.page_height).0 / image_size_mm(page.image_height)),
                dpi: Some(IMAGE_DPI),
            },
        );
        layer.set_fill_color(Color::Greyscale(Greyscale::new(0.0, None)));
        for region in matched_regions.iter().filter(|region| region.page_index == page.page_index) {
            let rectangle = build_rectangle(
                &Bounds {
                    x0: region.x0,
                    y0: region.y0,
                    x1: region.x1,
                    y1: region.y1,
                },
                page,
            );
            layer.add_polygon(rectangle);
        }
    }

    let file = File::create(path).map_err(|err| format!("failed to create redacted PDF: {err}"))?;
    let mut writer = BufWriter::new(file);
    doc.save(&mut writer)
        .map_err(|err| format!("failed to save raster-overlay PDF: {err}"))?;
    Ok(())
}

fn collect_spans(text: &str, terms: &[String]) -> Result<Vec<MatchSpan>, String> {
    let mut spans = Vec::new();
    for term in terms {
        let regex = RegexBuilder::new(&regex::escape(term))
            .case_insensitive(true)
            .build()
            .map_err(|err| format!("invalid redaction term '{term}': {err}"))?;
        for matched in regex.find_iter(text) {
            spans.push(MatchSpan {
                term: term.clone(),
                start: matched.start(),
                end: matched.end(),
            });
        }
    }
    spans.sort_by(|left, right| left.start.cmp(&right.start).then(left.end.cmp(&right.end)));
    Ok(spans)
}

fn redact_text(text: &str, terms: &[String]) -> Result<String, String> {
    let mut redacted = text.to_string();
    for term in terms {
        let regex = RegexBuilder::new(&regex::escape(term))
            .case_insensitive(true)
            .build()
            .map_err(|err| format!("invalid redaction term '{term}': {err}"))?;
        redacted = regex.replace_all(&redacted, REDACTION_TOKEN).into_owned();
    }
    Ok(redacted)
}

fn estimate_matched_regions(layout: &OcrLayout, terms: &[String]) -> Result<Vec<MatchedRegion>, String> {
    let mut regions = Vec::new();
    for page in &layout.pages {
        for block in &page.blocks {
            let lowered = block.text.to_lowercase();
            let total_chars = block.text.chars().count().max(1) as f64;
            let width = (block.bounds.x1 - block.bounds.x0).max(1.0);
            for term in terms {
                let regex = RegexBuilder::new(&regex::escape(term))
                    .case_insensitive(true)
                    .build()
                    .map_err(|err| format!("invalid redaction term '{term}': {err}"))?;
                for matched in regex.find_iter(&lowered) {
                    let prefix_chars = lowered[..matched.start()].chars().count() as f64;
                    let matched_chars = lowered[matched.start()..matched.end()].chars().count().max(1) as f64;
                    let x0 = block.bounds.x0 + width * (prefix_chars / total_chars);
                    let x1 = (block.bounds.x0 + width * ((prefix_chars + matched_chars) / total_chars))
                        .max(x0 + width / total_chars.max(1.0));
                    regions.push(MatchedRegion {
                        page_index: page.page_index,
                        block_index: block.block_index,
                        term: term.clone(),
                        text: block.text.clone(),
                        x0,
                        y0: block.bounds.y0,
                        x1,
                        y1: block.bounds.y1,
                    });
                }
            }
        }
    }
    Ok(regions)
}

fn build_artifacts_from_searchable_pdf(pdf_bytes: &[u8], terms: &[String]) -> Result<RedactionArtifacts, String> {
    let extracted = pdf_extract::extract_text_from_mem(pdf_bytes)
        .map_err(|err| format!("failed to extract searchable text: {err}"))?;
    let canonical_original = normalize_text(extracted.trim());
    if canonical_original.is_empty() {
        return Err("extractable-text-required".to_string());
    }
    let matched_spans = collect_spans(&canonical_original, terms)?;
    if matched_spans.is_empty() {
        return Err("no-redaction-matches".to_string());
    }
    let canonical_redacted = redact_text(&canonical_original, terms)?;
    Ok(RedactionArtifacts {
        canonical_original,
        canonical_redacted,
        matched_spans,
        matched_regions: Vec::new(),
        ocr_engine: None,
        ocr_engine_version: None,
        ocr_layout_sha256: None,
        working_searchable_pdf_sha256: None,
    })
}

fn build_artifacts_from_page_layout(
    layout_json: &Path,
    working_searchable_pdf: Option<&Path>,
    terms: &[String],
    include_ocr_metadata: bool,
) -> Result<(OcrLayout, RedactionArtifacts), String> {
    let layout_bytes =
        fs::read(layout_json).map_err(|err| format!("failed to read page layout '{}': {err}", layout_json.display()))?;
    let layout: OcrLayout =
        serde_json::from_slice(&layout_bytes).map_err(|err| format!("failed to parse page layout '{}': {err}", layout_json.display()))?;
    if layout.pages.is_empty() {
        return Err("extractable-text-required".to_string());
    }

    let canonical_original = normalize_text(
        layout
            .pages
            .iter()
            .map(|page| {
                page.blocks
                    .iter()
                    .map(|block| block.text.trim())
                    .filter(|text| !text.is_empty())
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .filter(|page_text| !page_text.is_empty())
            .collect::<Vec<_>>()
            .join("\n\n")
            .trim(),
    );
    if canonical_original.is_empty() {
        return Err("extractable-text-required".to_string());
    }
    let matched_spans = collect_spans(&canonical_original, terms)?;
    if matched_spans.is_empty() {
        return Err("no-redaction-matches".to_string());
    }
    let canonical_redacted = redact_text(&canonical_original, terms)?;
    let matched_regions = estimate_matched_regions(&layout, terms)?;
    let working_searchable_pdf_sha256 = working_searchable_pdf
        .map(|path| fs::read(path).map(|bytes| sha256_hex(&bytes)))
        .transpose()
        .map_err(|err| format!("failed to read working searchable PDF: {err}"))?;

    Ok((
        layout.clone(),
        RedactionArtifacts {
            canonical_original,
            canonical_redacted,
            matched_spans,
            matched_regions,
            ocr_engine: if include_ocr_metadata {
                Some(layout.engine.clone())
            } else {
                None
            },
            ocr_engine_version: if include_ocr_metadata {
                layout.engine_version.clone()
            } else {
                None
            },
            ocr_layout_sha256: if include_ocr_metadata {
                Some(sha256_hex(&layout_bytes))
            } else {
                None
            },
            working_searchable_pdf_sha256: if include_ocr_metadata {
                working_searchable_pdf_sha256
            } else {
                None
            },
        },
    ))
}

fn write_manifest(output_dir: &Path, manifest: &Manifest) -> Result<(), String> {
    let manifest_path = output_dir.join("redaction_manifest.json");
    let payload =
        serde_json::to_vec_pretty(manifest).map_err(|err| format!("failed to serialize manifest: {err}"))?;
    fs::write(manifest_path, payload).map_err(|err| format!("failed to write manifest: {err}"))?;
    Ok(())
}

fn run(
    input: &Path,
    output_dir: &Path,
    terms_json: &str,
    source_mode: SourceMode,
    searchable_layout_json: Option<&Path>,
    ocr_layout_json: Option<&Path>,
    page_images_dir: Option<&Path>,
    working_searchable_pdf: Option<&Path>,
) -> Result<(), String> {
    let terms: Vec<String> =
        serde_json::from_str(terms_json).map_err(|err| format!("invalid terms JSON: {err}"))?;
    let normalized_terms: Vec<String> = terms
        .into_iter()
        .map(|term| term.trim().to_lowercase())
        .filter(|term| !term.is_empty())
        .collect();
    if normalized_terms.is_empty() {
        return Err("at least one redaction term is required".to_string());
    }

    let pdf_bytes = fs::read(input).map_err(|err| format!("failed to read input PDF: {err}"))?;
    let source_pdf_sha256 = sha256_hex(&pdf_bytes);

    let (layout_for_render, artifacts, render_mode) = match source_mode {
        SourceMode::SearchablePdf => {
            if let Some(layout_path) = searchable_layout_json {
                let (layout, artifacts) =
                    build_artifacts_from_page_layout(layout_path, None, &normalized_terms, false)?;
                (Some(layout), artifacts, "raster_overlay")
            } else {
                (
                    None,
                    build_artifacts_from_searchable_pdf(&pdf_bytes, &normalized_terms)?,
                    "text_reflow",
                )
            }
        }
        SourceMode::OcrLayout => {
            let layout_path = ocr_layout_json.ok_or_else(|| "ocr-layout-required".to_string())?;
            let (layout, artifacts) =
                build_artifacts_from_page_layout(layout_path, working_searchable_pdf, &normalized_terms, true)?;
            (Some(layout), artifacts, "raster_overlay")
        }
    };

    fs::create_dir_all(output_dir).map_err(|err| format!("failed to create output directory: {err}"))?;
    fs::write(
        output_dir.join("canonical_original.txt"),
        artifacts.canonical_original.as_bytes(),
    )
    .map_err(|err| format!("failed to write canonical original text: {err}"))?;
    fs::write(
        output_dir.join("canonical_redacted.txt"),
        artifacts.canonical_redacted.as_bytes(),
    )
    .map_err(|err| format!("failed to write canonical redacted text: {err}"))?;

    let redacted_pdf_path = output_dir.join("redacted.pdf");
    match render_mode {
        "text_reflow" => render_text_reflow_pdf(&redacted_pdf_path, &artifacts.canonical_redacted)?,
        _ => {
            let layout = layout_for_render
                .as_ref()
                .ok_or_else(|| "page-layout-required".to_string())?;
            let images_dir = page_images_dir.ok_or_else(|| "page-layout-required".to_string())?;
            render_raster_overlay_pdf(&redacted_pdf_path, layout, &artifacts.matched_regions, images_dir)?
        }
    }
    let redacted_pdf_bytes =
        fs::read(&redacted_pdf_path).map_err(|err| format!("failed to read redacted PDF: {err}"))?;

    let manifest = Manifest {
        engine_name: ENGINE_NAME.to_string(),
        engine_version: env!("CARGO_PKG_VERSION").to_string(),
        engine_mode: ENGINE_MODE.to_string(),
        searchable_text_confirmed: true,
        source_pdf_sha256,
        canonical_original_sha256: sha256_hex(artifacts.canonical_original.as_bytes()),
        canonical_redacted_sha256: sha256_hex(artifacts.canonical_redacted.as_bytes()),
        redacted_pdf_sha256: sha256_hex(&redacted_pdf_bytes),
        matched_terms: normalized_terms,
        matched_spans: artifacts.matched_spans,
        source_text_mode: source_mode.as_manifest_value().to_string(),
        ocr_used: source_mode == SourceMode::OcrLayout,
        ocr_engine: artifacts.ocr_engine,
        ocr_engine_version: artifacts.ocr_engine_version,
        ocr_layout_sha256: artifacts.ocr_layout_sha256,
        working_searchable_pdf_sha256: artifacts.working_searchable_pdf_sha256,
        render_mode: render_mode.to_string(),
        matched_regions: artifacts.matched_regions,
    };
    write_manifest(output_dir, &manifest)?;
    Ok(())
}

fn print_version_json() -> Result<(), String> {
    let info = VersionInfo {
        engine_name: ENGINE_NAME.to_string(),
        engine_version: env!("CARGO_PKG_VERSION").to_string(),
        engine_mode: ENGINE_MODE.to_string(),
    };
    let payload =
        serde_json::to_string(&info).map_err(|err| format!("failed to encode version info: {err}"))?;
    println!("{payload}");
    Ok(())
}

fn main() {
    let cli = Cli::parse();
    let result = match cli.command {
        Command::Run {
            input,
            output_dir,
            terms_json,
            source_mode,
            searchable_layout_json,
            ocr_layout_json,
            page_images_dir,
            working_searchable_pdf,
        } => run(
            &input,
            &output_dir,
            &terms_json,
            source_mode,
            searchable_layout_json.as_deref(),
            ocr_layout_json.as_deref(),
            page_images_dir.as_deref(),
            working_searchable_pdf.as_deref(),
        ),
        Command::VersionJson => print_version_json(),
    };

    if let Err(message) = result {
        eprintln!("{message}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::{collect_spans, redact_text, sha256_hex, SourceMode};

    #[test]
    fn collects_case_insensitive_spans() {
        let spans =
            collect_spans("Privileged data and privileged notes", &[String::from("privileged")]).unwrap();
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0].start, 0);
    }

    #[test]
    fn redacts_case_insensitive_terms() {
        let redacted =
            redact_text("Confidential privileged data", &[String::from("privileged")]).unwrap();
        assert!(redacted.contains("[REDACTED]"));
    }

    #[test]
    fn hashes_bytes() {
        assert_eq!(
            sha256_hex(b"blockvault"),
            "3d69b816a2b5aaab171c3bacd843861b07fdceca63d65b54ec93a8685803297b"
        );
    }

    #[test]
    fn source_mode_manifest_values_are_stable() {
        assert_eq!(SourceMode::SearchablePdf.as_manifest_value(), "direct_pdf");
        assert_eq!(SourceMode::OcrLayout.as_manifest_value(), "ocr_assisted");
    }
}
