"""Docling plugin entry point (group "docling")."""

from .model import FineParserOcrModel


def ocr_engines():
    return {"ocr_engines": [FineParserOcrModel]}
