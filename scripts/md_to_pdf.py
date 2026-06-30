"""Convert Markdown docs to print-ready HTML (and optionally PDF via headless Chrome).

Two workflows:
  1. HTML, then "Save as PDF" in Chrome (matches a right-click → Chrome → Print flow):
       .venv/bin/python scripts/md_to_pdf.py docs/cypher-queries.md
     -> writes docs/export/cypher-queries.html ; open it in Chrome and Cmd-P → Save as PDF.

  2. Fully automated PDF via headless Chrome (macOS Chrome auto-detected):
       .venv/bin/python scripts/md_to_pdf.py --pdf docs/*.md

With no file arguments, converts every docs/*.md.
"""

import argparse
import glob
import pathlib
import subprocess
import sys

import markdown

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPORT = ROOT / "docs" / "export"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

# GitHub-ish, print-friendly styling. @page margins keep tables/code readable on Letter.
CSS = """
@page { size: Letter; margin: 18mm 16mm; }
body { font: 14px/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       color: #1f2328; max-width: 980px; margin: 0 auto; padding: 24px; }
h1,h2,h3 { line-height: 1.25; margin-top: 1.4em; }
h1 { font-size: 1.9em; border-bottom: 1px solid #d0d7de; padding-bottom: .3em; }
h2 { font-size: 1.4em; border-bottom: 1px solid #d8dee4; padding-bottom: .3em; }
h2 { page-break-before: auto; break-inside: avoid; }
code { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace; font-size: 85%; }
:not(pre) > code { background: #eff1f3; padding: .15em .35em; border-radius: 4px; }
pre { background: #f6f8fa; padding: 14px 16px; border-radius: 6px; overflow: auto;
      border: 1px solid #e4e8ec; break-inside: avoid; }
pre code { font-size: 12px; }
table { border-collapse: collapse; margin: 1em 0; width: 100%; break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: 6px 12px; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
blockquote { border-left: 4px solid #d0d7de; margin: 1em 0; padding: .2em 1em; color: #57606a;
             background: #f6f8fa; }
a { color: #0969da; text-decoration: none; }
"""

HTML = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>{css}</style></head><body>{body}</body></html>"""


def find_chrome():
    for c in CHROME_CANDIDATES:
        if pathlib.Path(c).exists():
            return c
    return None


def convert(md_path):
    md_path = pathlib.Path(md_path)
    EXPORT.mkdir(parents=True, exist_ok=True)
    html_body = markdown.markdown(
        md_path.read_text(),
        extensions=["tables", "fenced_code", "codehilite", "toc", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False}},
    )
    html_path = EXPORT / (md_path.stem + ".html")
    html_path.write_text(HTML.format(title=md_path.stem, css=CSS, body=html_body))
    return html_path


def to_pdf(html_path, chrome):
    pdf_path = html_path.with_suffix(".pdf")
    subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", html_path.as_uri()],
        check=True, capture_output=True,
    )
    return pdf_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="markdown files (default: docs/*.md)")
    ap.add_argument("--pdf", action="store_true", help="also emit PDF via headless Chrome")
    args = ap.parse_args()

    files = args.files or sorted(glob.glob(str(ROOT / "docs" / "*.md")))
    if not files:
        sys.exit("no markdown files found")

    chrome = find_chrome() if args.pdf else None
    if args.pdf and not chrome:
        sys.exit("--pdf requested but no Chrome/Chromium/Edge found; open the .html manually")

    for f in files:
        html_path = convert(f)
        if args.pdf:
            pdf_path = to_pdf(html_path, chrome)
            print(f"{f} -> {pdf_path}")
        else:
            print(f"{f} -> {html_path}   (open in Chrome, Cmd-P → Save as PDF)")


if __name__ == "__main__":
    main()
