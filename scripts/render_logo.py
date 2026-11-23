from pathlib import Path

from playwright.sync_api import sync_playwright

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
svg_path = WORKSPACE_ROOT / "assets" / "logo.svg"
png_path = WORKSPACE_ROOT / "assets" / "logo.png"

html_content = f"""<!DOCTYPE html>
<html>
<head>
<style>
body {{ margin: 0; padding: 0; overflow: hidden; background: transparent; }}
</style>
</head>
<body>
<img src="{svg_path.as_uri()}" width="1024" height="1024" style="display:block;" />
</body>
</html>"""

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, args=["--allow-file-access-from-files", "--disable-web-security"]
    )
    page = browser.new_page(viewport={"width": 1024, "height": 1024})
    page.set_content(html_content, wait_until="load")
    page.wait_for_selector("img", timeout=5000)
    page.screenshot(path=str(png_path), omit_background=True)
    browser.close()

print(f"Exported {png_path} ({png_path.stat().st_size} bytes)")
