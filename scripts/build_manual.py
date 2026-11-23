#!/usr/bin/env python3
"""Build script for the Lathe User Manual.

Converts docs/manual/USER_MANUAL.md to a styled HTML document and renders
a complete, publication-quality PDF via Playwright (Chromium).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

# Root and asset paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
SOURCE_MD = WORKSPACE_ROOT / "docs" / "manual" / "USER_MANUAL.md"
OUTPUT_HTML = WORKSPACE_ROOT / "docs" / "manual" / "manual_preview.html"
OUTPUT_PDF = WORKSPACE_ROOT / "assets" / "manual" / "Lathe-User-Manual.pdf"
MERMAID_JS_PATH = WORKSPACE_ROOT / "scripts" / "mermaid.min.js"
LOGO_PATH = WORKSPACE_ROOT / "assets" / "logo.png"


def load_version() -> str:
    """Extract version string from pyproject.toml."""
    pyproject = WORKSPACE_ROOT / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("version ="):
                return line.split("=")[1].strip().strip('"')
    return "0.1.0"


def transform_callouts(md_text: str) -> str:
    """Transform GitHub-style alerts (> [!NOTE], etc.) into styled callout divs."""
    pattern = re.compile(
        r"^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\n((?:^>.*$\n?)+)",
        re.MULTILINE,
    )

    def _replace_callout(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        lines = match.group(2).splitlines()
        content = "\n".join(line[1:].lstrip() if line.startswith(">") else line for line in lines)
        icon_map = {
            "note": "ℹ️ Note",
            "tip": "💡 Tip",
            "important": "📌 Important",
            "warning": "⚠️ Warning",
            "caution": "🛑 Caution",
        }
        title = icon_map.get(kind, kind.capitalize())
        return (
            f'<div class="callout callout-{kind}">\n'
            f'<div class="callout-title">{title}</div>\n'
            f"{content}\n"
            f"</div>\n"
        )

    return pattern.sub(_replace_callout, md_text)


def process_mermaid_blocks(md_text: str) -> str:
    """Convert fenced mermaid code blocks to <div class='mermaid'> tags."""
    pattern = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)

    def _replace_mermaid(match: re.Match[str]) -> str:
        graph = match.group(1).strip()
        return f'<div class="mermaid-container"><div class="mermaid">\n{graph}\n</div></div>'

    return pattern.sub(_replace_mermaid, md_text)


def resolve_image_paths(md_text: str) -> str:
    """Convert relative image paths to absolute file URIs for Playwright rendering."""

    def _replace_img(match: re.Match[str]) -> str:
        alt = match.group(1)
        rel_path = match.group(2)
        # Normalize relative path from docs/manual/
        if rel_path.startswith("../../"):
            abs_target = (WORKSPACE_ROOT / rel_path[6:]).resolve()
        elif rel_path.startswith("../"):
            abs_target = (WORKSPACE_ROOT / "docs" / rel_path[3:]).resolve()
        else:
            abs_target = (WORKSPACE_ROOT / "docs" / "manual" / rel_path).resolve()

        if abs_target.exists():
            return f"![{alt}]({abs_target.as_uri()})"
        return match.group(0)

    return re.sub(r"!\[(.*?)\]\((.*?)\)", _replace_img, md_text)


def generate_html(md_content: str, version: str) -> str:
    """Render full HTML document with styling, cover page, and scripts."""
    # Pre-process markdown
    text = transform_callouts(md_content)
    text = process_mermaid_blocks(text)
    text = resolve_image_paths(text)

    # Separate cover and main body
    lines = text.splitlines()
    # Strip primary h1 for custom cover page
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body_md = "\n".join(lines)

    # Convert to HTML via markdown package
    html_body = markdown.markdown(
        body_md,
        extensions=[
            "fenced_code",
            "tables",
            "toc",
            "codehilite",
            "attr_list",
            "def_list",
        ],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "guess_lang": False,
                "use_pygments": True,
            },
            "toc": {
                "permalink": True,
                "toc_depth": "2-3",
            },
        },
    )

    pygments_css = HtmlFormatter(style="monokai").get_style_defs(".highlight")

    # Load local mermaid.min.js if available
    mermaid_js = ""
    if MERMAID_JS_PATH.exists():
        mermaid_js = MERMAID_JS_PATH.read_text(encoding="utf-8")

    logo_uri = LOGO_PATH.as_uri() if LOGO_PATH.exists() else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Lathe User Manual v{version}</title>
<style>
  /* Base Reset & Typography */
  *, *::before, *::after {{
    box-sizing: border-box;
  }}
  @page {{
    size: A4;
    margin: 18mm 14mm 18mm 14mm;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1e293b;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
  }}

  /* Cover Page */
  .cover-page {{
    page-break-after: always;
    min-height: 90vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    background: radial-gradient(circle at 50% 30%, #0f172a 0%, #070a13 100%);
    color: #ffffff;
    padding: 40px 20px;
    border-radius: 8px;
    margin-bottom: 30px;
  }}
  .cover-logo {{
    max-width: 440px;
    height: auto;
    margin-bottom: 24px;
    filter: drop-shadow(0 0 25px rgba(56, 189, 248, 0.45));
  }}
  .cover-title {{
    font-size: 32pt;
    font-weight: 800;
    letter-spacing: -0.5px;
    color: #ffffff;
    margin: 0 0 12px 0;
  }}
  .cover-subtitle {{
    font-size: 13pt;
    color: #38bdf8;
    max-width: 600px;
    margin: 0 0 32px 0;
    font-weight: 500;
    line-height: 1.4;
  }}
  .cover-meta {{
    font-size: 10pt;
    color: #94a3b8;
    border-top: 1px solid #334155;
    padding-top: 16px;
    width: 320px;
  }}
  .cover-meta p {{
    margin: 4px 0;
  }}

  /* Section Headings */
  h1, h2, h3, h4, h5, h6 {{
    color: #0f172a;
    font-weight: 700;
    line-height: 1.25;
  }}
  h2 {{
    font-size: 16pt;
    border-bottom: 2px solid #0284c7;
    padding-bottom: 6px;
    margin-top: 26pt;
    margin-bottom: 12pt;
    page-break-before: always;
  }}
  h3 {{
    font-size: 12.5pt;
    color: #0369a1;
    margin-top: 16pt;
    margin-bottom: 8pt;
    page-break-after: avoid;
  }}
  h4 {{
    font-size: 11pt;
    color: #334155;
    margin-top: 12pt;
    margin-bottom: 6pt;
    page-break-after: avoid;
  }}

  p, li {{
    color: #334155;
  }}

  /* Hyperlinks */
  a {{
    color: #0284c7;
    text-decoration: none;
  }}
  a:hover {{
    text-decoration: underline;
  }}

  /* Code Blocks & Inline Monospace */
  code {{
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    font-size: 9.5pt;
    background-color: #f1f5f9;
    color: #0f172a;
    padding: 2px 5px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
  }}
  pre {{
    background-color: #0b1120 !important;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 12px 16px;
    overflow-x: auto;
    page-break-inside: avoid;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  }}
  pre code {{
    background: transparent !important;
    border: none;
    padding: 0;
    color: #e2e8f0;
    font-size: 9pt;
    line-height: 1.45;
  }}

  /* Pygments Syntax Theme */
  {pygments_css}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
  }}
  th, td {{
    border: 1px solid #cbd5e1;
    padding: 8px 10px;
    text-align: left;
    vertical-align: top;
  }}
  th {{
    background-color: #0f172a;
    color: #f8fafc;
    font-weight: 600;
  }}
  tr:nth-child(even) {{
    background-color: #f8fafc;
  }}

  /* Terminal Screenshots & Diagrams */
  img {{
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    border: 1px solid #94a3b8;
    box-shadow: 0 6px 12px -2px rgba(15, 23, 42, 0.2);
    margin: 14px 0;
    page-break-inside: avoid;
  }}

  /* Mermaid Diagrams */
  .mermaid-container {{
    display: flex;
    justify-content: center;
    background-color: #0b1120;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 20px;
    margin: 16px 0;
    page-break-inside: avoid;
  }}
  .mermaid {{
    text-align: center;
  }}

  /* Callout Boxes */
  .callout {{
    border-left: 4px solid #0284c7;
    background-color: #f0f9ff;
    padding: 12px 16px;
    margin: 14px 0;
    border-radius: 0 6px 6px 0;
    page-break-inside: avoid;
  }}
  .callout-title {{
    font-weight: 700;
    margin-bottom: 6px;
    color: #0369a1;
  }}
  .callout-tip {{
    border-left-color: #10b981;
    background-color: #ecfdf5;
  }}
  .callout-tip .callout-title {{
    color: #047857;
  }}
  .callout-warning {{
    border-left-color: #f59e0b;
    background-color: #fffbeb;
  }}
  .callout-warning .callout-title {{
    color: #b45309;
  }}
  .callout-caution {{
    border-left-color: #ef4444;
    background-color: #fef2f2;
  }}
  .callout-caution .callout-title {{
    color: #b91c1c;
  }}

  /* Table of Contents */
  .toc {{
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 16px 24px;
    margin: 20px 0;
    page-break-after: always;
  }}
  .toc ul {{
    list-style-type: none;
    padding-left: 16px;
  }}
  .toc > ul {{
    padding-left: 0;
  }}
  .toc li {{
    margin: 4px 0;
  }}
</style>
</head>
<body>

<!-- Cover Page -->
<div class="cover-page">
  {"<img class='cover-logo' src='" + logo_uri + "' alt='Lathe Logo' />" if logo_uri else ""}
  <div class="cover-title">Lathe User Manual</div>
  <div class="cover-subtitle">
    Autonomous Terminal AI Coding Agent Powered by Dual Open-Source Models & Automated Merging
  </div>
  <div class="cover-meta">
    <p><strong>Version:</strong> v{version}</p>
    <p><strong>Release Date:</strong> November 2026</p>
    <p><strong>Author:</strong> Aditya Surse & Lathe Contributors</p>
    <p><strong>License:</strong> Apache-2.0</p>
  </div>
</div>

<!-- Main Body -->
<div class="manual-content">
{html_body}
</div>

<!-- Offline Mermaid Script -->
<script>
{mermaid_js}
</script>
<script>
if (typeof mermaid !== 'undefined') {{
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'dark',
    themeVariables: {{
      darkMode: true,
      background: '#0b1120',
      primaryColor: '#0284c7',
      primaryTextColor: '#f8fafc',
      primaryBorderColor: '#38bdf8',
      lineColor: '#38bdf8',
      secondaryColor: '#1e293b',
      tertiaryColor: '#0f172a'
    }}
  }});
}}
</script>
</body>
</html>"""
    return html


def build_manual() -> None:
    """Read markdown source, generate HTML, and print to PDF via Playwright."""
    print("=" * 60)
    print("Building Lathe User Manual")
    print("=" * 60)

    if not SOURCE_MD.exists():
        print(f"Error: Source manual not found at {SOURCE_MD}", file=sys.stderr)
        sys.exit(1)

    version = load_version()
    print(f"1. Reading source manual: {SOURCE_MD} (Lathe v{version})")
    md_content = SOURCE_MD.read_text(encoding="utf-8")

    print("2. Generating styled HTML with Mermaid and Pygments...")
    html_content = generate_html(md_content, version)
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_content, encoding="utf-8")
    print(f"✓ Wrote HTML preview to: {OUTPUT_HTML}")

    print("3. Launching Playwright Chromium to render PDF...")
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--allow-file-access-from-files", "--disable-web-security"]
        )
        page = browser.new_page()

        # Navigate to HTML file
        page.goto(OUTPUT_HTML.as_uri(), wait_until="networkidle")

        # Allow mermaid to complete rendering if diagrams exist
        try:
            page.wait_for_selector(".mermaid svg", timeout=5000)
            print("✓ Rendered Mermaid diagrams successfully.")
        except Exception:
            print("Notice: No mermaid SVG selector rendered or timeout reached.")

        # Print PDF with headers, footers, and page numbers
        page.pdf(
            path=str(OUTPUT_PDF),
            format="A4",
            print_background=True,
            margin={"top": "18mm", "bottom": "18mm", "left": "15mm", "right": "15mm"},
            display_header_footer=True,
            header_template=(
                '<div style="font-size: 8pt; font-family: -apple-system, sans-serif; '
                'color: #94a3b8; width: 100%; text-align: right; padding-right: 15mm;">'
                f"Lathe User Manual · v{version}</div>"
            ),
            footer_template=(
                '<div style="font-size: 8pt; font-family: -apple-system, sans-serif; '
                'color: #94a3b8; width: 100%; text-align: center;">'
                '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
            ),
        )
        browser.close()

    if OUTPUT_PDF.exists():
        pdf_size = OUTPUT_PDF.stat().st_size
        print("\n[SUCCESS] Generated User Manual PDF:")
        print(f"  Path: {OUTPUT_PDF}")
        print(f"  Size: {pdf_size / (1024 * 1024):.2f} MB ({pdf_size:,} bytes)\n")
    else:
        print("Error: PDF output file was not created.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    build_manual()
