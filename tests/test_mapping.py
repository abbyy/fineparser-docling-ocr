import json
from pathlib import Path

import pytest
from docling_core.types.doc import BoundingBox, CoordOrigin

from fineparser_docling_ocr.mapping import fre_page_to_cells

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def fre():
    return json.loads((FIXTURES / "test_15_p1.json").read_text())


def letter(l=0.0, t=0.0):
    return BoundingBox(l=l, t=t, r=l + 612, b=t + 792, coord_origin=CoordOrigin.TOPLEFT)


def test_line_cells_scale_px_to_points(fre):
    page = fre["layout"]["pages"][0]  # 2550x3300 px == Letter at 300 dpi
    cells = fre_page_to_cells(page, letter())
    assert [c.text for c in cells][:2] == ["Page 1", "of 15"]
    first = page["texts"][0]["lines"][0]["position"]
    bb = cells[0].rect.to_bounding_box()
    assert bb.coord_origin == CoordOrigin.TOPLEFT
    assert bb.l == pytest.approx(first["l"] * 72 / 300)
    assert bb.b == pytest.approx(first["b"] * 72 / 300)
    assert all(c.from_ocr and 0 <= c.confidence <= 1 for c in cells)
    assert [c.index for c in cells] == list(range(len(cells)))


def test_rect_offset_and_word_granularity(fre):
    page = fre["layout"]["pages"][0]
    lines = fre_page_to_cells(page, letter())
    words = fre_page_to_cells(page, letter(l=10, t=20), granularity="word", start_index=5)
    assert len(words) > len(lines)
    assert words[0].index == 5
    assert words[0].text == "Page"
    w0 = page["texts"][0]["lines"][0]["words"][0]["position"]
    assert words[0].rect.to_bounding_box().t == pytest.approx(20 + w0["t"] * 72 / 300)


def test_table_cells_and_blank_text_skipped():
    page = {
        "width": 100, "height": 100,
        "texts": [{"lines": [{"text": "  ", "confidence": 90, "position": {"l": 0, "t": 0, "r": 1, "b": 1}, "words": []}]}],
        "tables": [{"cells": [{"lines": [{"text": "cell", "confidence": 80, "position": {"l": 10, "t": 10, "r": 50, "b": 20}, "words": []}]}]}],
    }
    cells = fre_page_to_cells(page, BoundingBox(l=0, t=0, r=50, b=50, coord_origin=CoordOrigin.TOPLEFT))
    assert [c.text for c in cells] == ["cell"]
    assert cells[0].confidence == pytest.approx(0.8)
    assert cells[0].rect.to_bounding_box().r == pytest.approx(25)


def test_confidence_from_error_probability():
    def ch(t, ep):
        return {"text": t, "confidence": 55, "errorProbability": ep, "position": {"l": 0, "t": 0, "r": 1, "b": 1}}

    line = {
        "text": "ab cd", "confidence": 55, "position": {"l": 0, "t": 0, "r": 10, "b": 10},
        "words": [
            {"text": "ab", "confidence": 55, "position": {"l": 0, "t": 0, "r": 4, "b": 10}, "chars": [ch("a", 0), ch("b", 19)]},
            {"text": "cd", "confidence": 55, "position": {"l": 6, "t": 0, "r": 10, "b": 10}, "chars": [ch("c", 2), ch("d", None)]},
        ],
    }
    page = {"width": 10, "height": 10, "texts": [{"lines": [line]}]}
    rect = BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT)
    (line_cell,) = fre_page_to_cells(page, rect, "line")
    assert line_cell.confidence == pytest.approx(0.81)
    w1, w2 = fre_page_to_cells(page, rect, "word")
    assert (w1.confidence, w2.confidence) == (pytest.approx(0.81), pytest.approx(0.98))


def test_skewed_scan_original_coords_and_confidence():
    # FineParser output (with original-image coordinates) for a 200 dpi Letter page
    # rotated 1.2 deg; the page frame is the submitted PNG, not FRE's working image.
    page = json.loads((FIXTURES / "scan_p1_skewed.json").read_text())["layout"]["pages"][0]
    assert (page["width"], page["height"]) == (1746, 2236)
    rect = BoundingBox(l=0, t=0, r=1746 * 72 / 200, b=2236 * 72 / 200, coord_origin=CoordOrigin.TOPLEFT)
    cells = fre_page_to_cells(page, rect)
    assert len(cells) == 8 and cells[0].text == "Page 1"
    assert cells[0].rect.to_bounding_box().l == pytest.approx(page["texts"][0]["lines"][0]["position"]["l"] * 72 / 200)
    confs = [c.confidence for c in cells]
    assert all(0.8 < c <= 1 for c in confs) and len(set(confs)) > 1  # not FRE's flat 55


def test_blank_lines_without_position_are_skipped():
    # Seen on a real receipt: empty blocks/table cells are a blank line with no position.
    blank = {"confidence": -1, "text": "", "words": []}
    page = {
        "width": 10, "height": 10,
        "texts": [{"lines": [blank]}, {"lines": [{"text": "ok", "confidence": 70, "position": {"l": 0, "t": 0, "r": 5, "b": 5}, "words": []}]}],
        "tables": [{"cells": [{"lines": [blank]}]}],
    }
    rect = BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT)
    assert [c.text for c in fre_page_to_cells(page, rect)] == ["ok"]
    assert fre_page_to_cells(page, rect, "word") == []
