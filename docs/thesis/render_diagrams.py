"""Render every diagram in diagrams.mmd to figures/<name>.png.

Each diagram starts with a line "%% ==== <name>". Mermaid (from
node_modules) draws it in Microsoft Edge, and the SVG is screenshotted at
2x resolution so it stays sharp in print.

    npm install && python render_diagrams.py
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
MERMAID = HERE / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"
OUT = HERE / "figures"

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;padding:16px;background:#fff;font-family:Segoe UI,Arial,sans-serif}</style>
</head><body><div id="out"></div></body></html>"""


def diagrams() -> dict[str, str]:
    sections: dict[str, str] = {}
    name = None
    for line in (HERE / "diagrams.mmd").read_text(encoding="utf-8").splitlines():
        if line.startswith("%% ===="):
            name = line.removeprefix("%% ====").strip()
            sections[name] = ""
        elif name:
            sections[name] += line + "\n"
    return sections


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
        page.set_content(PAGE)
        page.add_script_tag(path=str(MERMAID))
        page.evaluate("""mermaid.initialize({
            startOnLoad: false, theme: 'neutral', securityLevel: 'loose',
            fontFamily: 'Segoe UI, Arial, sans-serif',
            flowchart: {htmlLabels: true, curve: 'basis'},
            er: {useMaxWidth: false}, sequence: {useMaxWidth: false},
        })""")
        for name, source in diagrams().items():
            page.evaluate(
                """async ([name, src]) => {
                    const {svg} = await mermaid.render('d_' + name, src);
                    const out = document.getElementById('out');
                    out.innerHTML = svg;
                    const el = out.querySelector('svg');
                    el.style.maxWidth = 'none';
                }""",
                [name, source],
            )
            page.locator("#out svg").screenshot(path=OUT / f"{name}.png")
            print("rendered", name)
        browser.close()


if __name__ == "__main__":
    main()
