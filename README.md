# Anuvad : same page , new language.

Translate **scanned English PDFs into Hindi**, either as an editable Word file or as a **Hindi PDF that keeps the original page layout**.

Scanned PDFs are just images, so the tool first reads the text with OCR, translates it with a neural translation model that runs **locally on your own computer** (CPU or NVIDIA GPU), and then rebuilds the output.

## Features

- **Two output modes**
  - `pdf_translate_layout.py`: Hindi PDF that looks like the original (images, logos, lines and page numbers stay in place).
  - `pdf_translate_hi.py`: clean Hindi text in a Word (`.docx`) file, one section per page, easy to edit.
- **OCR with positions** (Tesseract) to find each text block on the page.
- **Selectable translation engines** (`--engine`):
  - `nllb`: Meta's NLLB-200 model, runs locally, no rate limits, GPU supported (default for the layout mode).
  - `argos`: lightweight offline engine.
  - `google`: free Google endpoint via `deep-translator` (can be rate-limited on large files).
- **GPU acceleration** (CUDA, FP16) when a CUDA build of PyTorch is installed. Falls back to the CPU automatically.
- **Resumable**: progress is saved after every page, so a stopped run continues where it left off.
- **Correct Hindi rendering**: text is shaped with HarfBuzz (via PyMuPDF), so conjunct letters like क्ष, त्र, ज्ञ display properly.
- Saves the OCR'd English text alongside the output so you can check scan errors.

## How it works

```
Scanned PDF
   │  Poppler: page → image
   ▼
Image cleanup (grayscale, contrast, sharpen)
   │  Tesseract OCR: text + bounding boxes
   ▼
Text blocks (paragraphs / headings)
   │  Translation engine (NLLB / Argos / Google)
   ▼
Hindi text blocks
   │  Layout mode: paint over English with the local background colour,
   │               write Hindi in the same box (shrunk to fit if longer)
   │  Word mode:   write Hindi paragraphs into a .docx
   ▼
Hindi PDF  /  Hindi Word file
```

## Requirements

- Python 3.10+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows build) or your OS package manager
- [Poppler](https://github.com/oschwartz10612/poppler-windows/releases) (for `pdf2image`)
- A Hindi (Devanagari) font, e.g. Mangal, Nirmala, or [Noto Sans Devanagari](https://fonts.google.com/noto/specimen/Noto+Sans+Devanagari)
- Optional: an NVIDIA GPU for faster translation (the NLLB-600M model needs roughly 1.5 GB of GPU memory in FP16)

## Installation

```bash
git clone <your-repo-url>
cd <your-repo-folder>

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
```

Install **PyTorch** separately so you can choose the right build:

```bash
# NVIDIA GPU (CUDA). Check pytorch.org for the current command for your system:
pip install torch --index-url https://download.pytorch.org/whl/cu126

# CPU only:
pip install torch
```

Check that the GPU is visible (optional):

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

The first run downloads the NLLB model (about 2.5 GB). It is cached afterwards, so later runs start quickly.

## Usage

Always test on a couple of pages first.

### Hindi PDF with the original layout

```bash
python pdf_translate_layout.py input.pdf --engine nllb --start 1 --end 2
python pdf_translate_layout.py input.pdf --engine nllb
```

Output: `input_hindi_layout.pdf`

### Hindi Word file

```bash
python pdf_translate_hi.py input.pdf --engine nllb
```

Outputs: `input_hindi.docx` and `input_english_ocr.txt`

### Windows: pointing to Tesseract and Poppler

If they are not on your `PATH`:

```powershell
$T = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$P = "C:\poppler\Library\bin"
python pdf_translate_layout.py .\input.pdf --engine nllb --tesseract $T --poppler $P
```

### Options

| Option | Description | Default |
|---|---|---|
| `--engine` | `nllb`, `argos` or `google` | `nllb` (layout), `google` (Word) |
| `--start`, `--end` | Page range to process | whole PDF |
| `--dpi` | Render / OCR resolution | 200 (layout), 300 (Word) |
| `--font` | Path to a Devanagari `.ttf` (layout mode) | auto-detected |
| `--lang` | Tesseract language of the source | `eng` |
| `--tesseract` | Path to `tesseract.exe` | from `PATH` |
| `--poppler` | Path to the Poppler `bin` folder | from `PATH` |
| `-o`, `--output` | Output file path | `<name>_hindi...` |

## Project structure

```
.
├── pdf_translate_layout.py   # layout-preserving Hindi PDF (run this for PDF output)
├── pdf_translate_hi.py       # Word output + translation engines (also imported by the layout script)
├── requirements.txt
└── README.md
```

Both scripts must stay in the same folder, because the layout script reuses the engines and image cleanup from `pdf_translate_hi.py`.

Files created while running (progress, OCR text) are named after your PDF and are listed in `.gitignore`.

## Limitations

- **OCR quality drives everything.** Blurry, tilted or low-resolution scans produce OCR mistakes, and those carry into the Hindi. Check the saved English OCR text.
- **Hindi is longer than English**, so some text blocks are shrunk to fit in layout mode.
- **Complex tables and multi-column designs** may not look perfect, since each OCR text block is replaced separately.
- **Text inside pictures** may be detected as text and replaced.
- **Handwriting** is not supported by Tesseract.
- Machine translation can make mistakes with names, idioms and technical terms. Have important documents reviewed by a person.

## Troubleshooting

| Problem | Fix |
|---|---|
| `TooManyRequests` with `--engine google` | Google rate-limited you. Use `--engine nllb`. |
| `No Hindi font found` | Install a Devanagari font and pass `--font path\to\font.ttf`. |
| Log says "running on CPU" | You have the CPU build of PyTorch. Reinstall the CUDA build (see Installation). |
| `CUDA out of memory` | Close other GPU-heavy apps, or run on the CPU. |
| `ImportError: ... circular import` | A file was saved under the wrong name. Keep the two scripts as separate files. |
| Tesseract / Poppler not found | Pass `--tesseract` and `--poppler`, or add them to `PATH`. |

## Tech stack

Python, Tesseract OCR (`pytesseract`), Poppler (`pdf2image`), Meta NLLB-200 via Hugging Face Transformers, PyTorch (CUDA), PyMuPDF, `python-docx`, Pillow.

## Acknowledgements

- [NLLB-200](https://github.com/facebookresearch/fairseq/tree/nllb) by Meta AI
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF)

## License

Add a license of your choice (for example MIT) before publishing. Note that the NLLB model weights have their own license terms (CC-BY-NC), so check them if you plan any commercial use.
