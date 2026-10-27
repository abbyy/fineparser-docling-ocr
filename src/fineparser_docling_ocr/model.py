"""Docling OCR engine backed by ABBYY FineParser.

One FineParser job per OCR rect: Docling renders the region, we upload it as a PNG
(with its DPI set so FRE knows the resolution), and map the returned FRE JSON back.
Use OcrMode.FULL_PAGE so that is one job per page.
"""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import ConfigDict, Field

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import (
    DoclingComponentType,
    ErrorItem,
    FailureCategory,
    Page,
)
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import OcrMode, OcrOptions
from docling.models.base_ocr_model import BaseOcrModel
from docling.utils.profiling import TimeRecorder

from .client import FineParserClient
from .mapping import fre_page_to_cells

_log = logging.getLogger(__name__)


class FineParserOcrOptions(OcrOptions):
    kind: ClassVar[Literal["abbyy_fineparser"]] = "abbyy_fineparser"
    # FineParser languages are FRE names ("English,German") and are fixed per container
    # (-language); lang is informational and passed through untouched.
    canonicalize_lang: ClassVar[bool] = False
    lang: list[str] = ["English"]
    mode: OcrMode = OcrMode.FULL_PAGE
    # 300 dpi renders, FRE's preferred input resolution.
    scale: float = Field(default=300 / 72, gt=0)

    url: str = Field(default_factory=lambda: os.environ.get("FINEPARSER_URL", "http://127.0.0.1:8080"))
    job_timeout: float = 300.0
    poll_interval: float = 0.25
    granularity: Literal["line", "word"] = "line"

    model_config = ConfigDict(extra="forbid")


class FineParserOcrModel(BaseOcrModel):
    def __init__(
        self,
        *,
        enabled: bool,
        artifacts_path: Path | None,
        options: FineParserOcrOptions,
        accelerator_options: AcceleratorOptions,
    ):
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        self.options: FineParserOcrOptions
        self._client = (
            FineParserClient(options.url, timeout=options.job_timeout, poll_interval=options.poll_interval)
            if enabled
            else None
        )

    @classmethod
    def get_options_type(cls) -> type[OcrOptions]:
        return FineParserOcrOptions

    def __call__(self, conv_res: ConversionResult, page_batch: Iterable[Page]) -> Iterable[Page]:
        if not self.enabled or self._client is None:
            yield from page_batch
            return

        scale = self.options.scale
        for page in page_batch:
            assert page._backend is not None
            if not page._backend.is_valid():
                yield page
                continue

            with TimeRecorder(conv_res, "ocr"):
                cells = []
                for i, rect in enumerate(self.get_ocr_rects(page)):
                    if rect.area() == 0:
                        continue
                    image = page._backend.get_page_image(scale=scale, cropbox=rect)
                    buf = io.BytesIO()
                    image.save(buf, format="PNG", dpi=(72 * scale, 72 * scale))
                    del image
                    try:
                        fre = self._client.parse_json(buf.getvalue(), f"page{page.page_no}_r{i}.png")
                        fre_pages = fre["layout"]["pages"]
                        if len(fre_pages) != 1:
                            raise ValueError(f"expected 1 page in FineParser result, got {len(fre_pages)}")
                        cells.extend(
                            fre_page_to_cells(
                                fre_pages[0], rect, self.options.granularity, start_index=len(cells)
                            )
                        )
                    except Exception as e:
                        _log.error("FineParser OCR failed for page %d rect %d: %s", page.page_no, i, e)
                        conv_res.errors.append(
                            ErrorItem(
                                component_type=DoclingComponentType.MODEL,
                                module_name=type(self).__name__,
                                error_message=str(e) or e.__class__.__name__,
                                category=FailureCategory.INFERENCE_FAILURE,
                                page_no=page.page_no,
                            )
                        )

                self.post_process_cells(cells, page, conv_res)

            yield page

    def __del__(self):
        if getattr(self, "_client", None) is not None:
            self._client.close()
