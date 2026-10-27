"""Map FineReader Engine JSON (FineParser outputType=json) to Docling TextCells.

FRE JSON layout:
    layout.pages[] {width, height, texts[] {lines[] {text, position{l,t,r,b}, confidence, words[]}}}

Positions are integer pixels, top-left origin. From FineParser 1.0.1 they and the page
`width`/`height` are on the submitted image; earlier versions report FRE's
deskewed/resampled working image, which drifts on skewed input. Either way we scale
that frame onto the Docling OCR rect.
"""

from __future__ import annotations

from typing import Any, Literal

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

Granularity = Literal["line", "word"]


def unit_confidence(unit: dict[str, Any]) -> float:
    """Confidence 0..1 for a line or word: 1 - worst character errorProbability.

    FRE's `confidence` (CharConfidence) is image-only, not comparable across characters
    and comes out as a flat 55 by default; ABBYY recommends errorProbability (0..100,
    context-aware) for reliability. Characters taken from a PDF text layer have no
    errorProbability; then fall back to `confidence`.
    """
    words = unit.get("words") if "words" in unit else [unit]
    probs = [
        c["errorProbability"]
        for w in words or []
        for c in w.get("chars") or []
        if c.get("errorProbability") is not None
    ]
    if probs:
        return 1.0 - max(probs) / 100.0
    conf = unit.get("confidence")
    return conf / 100.0 if conf is not None and conf >= 0 else 1.0


def iter_units(fre_page: dict[str, Any], granularity: Granularity):
    """Yield (text, confidence 0..1, position) for every line or word on a page.

    Table cell text is included: FRE puts it under tables[].cells[].lines, not texts[].
    """
    blocks = list(fre_page.get("texts") or [])
    for table in fre_page.get("tables") or []:
        blocks.extend(table.get("cells") or [])
    for block in blocks:
        for line in block.get("lines") or []:
            units = [line] if granularity == "line" else line.get("words") or []
            for u in units:
                # Empty blocks and table cells come back as a blank line with no position.
                if "position" not in u or not u.get("text", "").strip():
                    continue
                yield u["text"], unit_confidence(u), u["position"]


def fre_page_to_cells(
    fre_page: dict[str, Any],
    rect: BoundingBox,
    granularity: Granularity = "line",
    start_index: int = 0,
) -> list[TextCell]:
    """Convert one FRE page to TextCells in Docling page coordinates (points, top-left).

    `rect` is the region (top-left origin, page points) whose rendered image was sent.
    """
    sx = rect.width / fre_page["width"]
    sy = rect.height / fre_page["height"]
    cells: list[TextCell] = []
    for text, conf, pos in iter_units(fre_page, granularity):
        text = text.strip()
        if not text:
            continue
        bbox = BoundingBox.from_tuple(
            (
                rect.l + pos["l"] * sx,
                rect.t + pos["t"] * sy,
                rect.l + pos["r"] * sx,
                rect.t + pos["b"] * sy,
            ),
            origin=CoordOrigin.TOPLEFT,
        )
        cells.append(
            TextCell(
                index=start_index + len(cells),
                text=text,
                orig=text,
                from_ocr=True,
                confidence=conf,
                rect=BoundingRectangle.from_bounding_box(bbox),
            )
        )
    return cells
