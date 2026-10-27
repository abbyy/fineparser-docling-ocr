# fineparser-docling-ocr

This plugin replaces [Docling](https://github.com/docling-project/docling)'s built in OCR with [ABBYY FineParser](https://github.com/abbyy/FineParser). FineParser is built on the ABBYY FineReader Engine recognition core, so the text and positions your pipeline works with come from ABBYY's production OCR, and it runs entirely on CPU.

Your Docling pipeline runs the same as it always does. Layout analysis, table structure and export all work the way you'd expect, and when Docling gets to the OCR step it hands each page to your FineParser container. The lines (or words) FineParser reads come back as Docling text cells, with their positions and confidence scores, ready for the rest of the pipeline.

## What you'll need

- Python 3.10 or newer, and Docling 2.139 or newer.
- A FineParser container, version 1.0.1 or later.

### Getting FineParser running

FineParser ships as the [`abbyyteam/fineparser`](https://hub.docker.com/r/abbyyteam/fineparser) Docker image and needs a license file to run. The Free plan at [fineparser.ai](https://www.fineparser.ai/#pricing) gives you 1,000 pages per month.

```bash
docker run -d --name fineparser -p 8080:8080 --stop-timeout 60 \
  -e FINEPARSER_LICENSE_DATA="$(cat your.fineparserlicense)" \
  -v fineparser-output:/app/output \
  abbyyteam/fineparser

curl -s localhost:8080/healthz
```

A licensed container reports `"ready":true` from `/healthz`. On an ARM host, like an Apple silicon Mac, add `--platform linux/amd64` to the `docker run` command, since the image is amd64 only for now.

The container starts in high fidelity mode with English. Recognition mode and languages are set when the container starts, not per request, so if your documents need something else, add `-mode` or `-language` after the image name. The [FineParser documentation](https://docs.abbyy.com/fine-parser/basics/configuration) covers the full set of options. If you run into problems with FineParser itself, [abbyy/FineParser](https://github.com/abbyy/FineParser) is the place to open an issue.

## Installing

Since FineParser runs on CPU, your whole pipeline can too. Docling still uses PyTorch for its layout and table models, and those run fine on CPU as well, so you can skip the CUDA build of torch entirely. That's several GB less to download and no GPU to provision. Install the CPU build first, then the plugin.

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install "fineparser-docling-ocr @ git+https://github.com/abbyy/fineparser-docling-ocr.git"
```

The package registers itself with Docling's plugin system under the engine kind `abbyy_fineparser`, so there's nothing else to wire up.

## Using it

Docling only loads OCR engines from outside its own package when `allow_external_plugins` is on, so make sure you set that.

```python
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
from fineparser_docling_ocr import FineParserOcrOptions

opts = PdfPipelineOptions(
    do_ocr=True,
    allow_external_plugins=True,
    ocr_options=FineParserOcrOptions(),  # uses $FINEPARSER_URL, or http://127.0.0.1:8080 if that's not set
)
converter = DocumentConverter(format_options={
    InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
    InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts),
})
print(converter.convert("scan.pdf").document.export_to_markdown())
```

### Options

These all live on `FineParserOcrOptions`.

| option | default | notes |
|---|---|---|
| `url` | `$FINEPARSER_URL` or `http://127.0.0.1:8080` | Where your FineParser container is listening. |
| `mode` | `OcrMode.FULL_PAGE` | Sends one FineParser job per page. Docling's other modes send one job per region that needs OCR. |
| `scale` | `300/72` | Renders pages at 300 dpi, which is what FineParser works best with. The PNG gets tagged with that DPI. |
| `granularity` | `"line"` | Return `"line"` or `"word"` cells. |
| `job_timeout` | `300` | How many seconds to wait on a single job. |
| `poll_interval` | `0.25` | How many seconds between job status checks. |
| `lang` | `["English"]` | Informational only. FineParser's languages are fixed when the container starts, through `-language`. |

Every page you send through counts against your FineParser page allowance, so keep that in mind if you're on the Free plan.

## How the mapping works

The plugin asks FineParser for its JSON output (`outputType=json`) and pulls the lines out of `layout.pages[].texts[].lines[]`, plus any text inside table cells from `tables[].cells[].lines[]`. Empty blocks and table cells come back as blank lines with no position, and the plugin skips those.

FineParser reports boxes in pixels. The plugin scales them from the page's `width` and `height` onto whatever region Docling rendered, so they end up in Docling's page points with a top left origin.

For confidence, the plugin takes `1 − max(errorProbability)/100` across the characters in each cell. We went with `errorProbability` because it accounts for the surrounding context, which makes it the more reliable number. The per character `confidence` value only looks at the character image and doesn't compare well from one character to the next. Characters that came from a PDF's text layer don't have an `errorProbability` at all, so for those the plugin falls back to `confidence`. Worth knowing that Docling only uses OCR confidence for its document quality grade (`ConfidenceReport.ocr_score`), so in practice this mostly affects that score.

If a FineParser job fails, the plugin logs it in `ConversionResult.errors` as an `INFERENCE_FAILURE` and the page keeps moving through the rest of the pipeline. One bad page won't take down the whole conversion.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

The tests run against FineParser JSON we captured from real runs (in `tests/fixtures/`), so you don't need a FineParser container to run them.

## License

The plugin is licensed under the [Apache License 2.0](./LICENSE). FineParser itself is licensed separately, see [Licenses and plans](https://docs.abbyy.com/fine-parser/basics/licenses-and-plans).
