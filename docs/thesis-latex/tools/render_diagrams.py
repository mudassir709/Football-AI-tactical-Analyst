"""Render every diagram in diagrams/diagrams.mmd to figures/<name>.pdf.

Each diagram starts with a line "%% ==== <name>". Mermaid draws it in
Microsoft Edge and the page is printed to PDF at exactly the size of the
drawing. The result is a vector graphic, so text stays sharp at any print size
(the supervisor found the old PNG screenshots too blurry to read).

Run from docs/thesis-latex (Mermaid comes from docs/thesis/node_modules):
    python tools/render_diagrams.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent  # docs/thesis-latex
MERMAID = HERE.parent / "thesis" / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"
OUT = HERE / "figures"

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>
  @page { margin: 0 }
  html, body { margin: 0; padding: 0; background: #fff }
  #out { display: inline-block; padding: 8px }
</style></head><body><div id="out"></div></body></html>"""


def diagrams() -> dict[str, str]:
    """The diagrams of the .mmd file, by name."""
    sections: dict[str, str] = {}
    name = None
    for line in (HERE / "diagrams" / "diagrams.mmd").read_text(encoding="utf-8").splitlines():
        if line.startswith("%% ===="):
            name = line.removeprefix("%% ====").strip()
            sections[name] = ""
        elif name:
            sections[name] += line + "\n"
    return sections


def main(only: set[str]) -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()
        for name, source in diagrams().items():
            if only and name not in only:
                continue
            page.set_content(PAGE)
            page.add_script_tag(path=str(MERMAID))
            # Large text and little empty space between the boxes: in print, the
            # text size depends on how wide the whole diagram is compared with
            # its text, so tight layouts stay readable when scaled to the page.
            page.evaluate("""mermaid.initialize({
                startOnLoad: false, theme: 'neutral', securityLevel: 'loose',
                fontFamily: 'Arial, Helvetica, sans-serif',
                themeVariables: {fontSize: '18px'},
                flowchart: {htmlLabels: true, curve: 'basis', useMaxWidth: false,
                            nodeSpacing: 22, rankSpacing: 32, padding: 8},
                er: {useMaxWidth: false, fontSize: 16, entityPadding: 8},
                sequence: {useMaxWidth: false, actorMargin: 25, width: 110, boxMargin: 6,
                           messageMargin: 28, mirrorActors: false,
                           messageFontSize: 18, actorFontSize: 18, noteFontSize: 18},
                state: {useMaxWidth: false}, class: {useMaxWidth: false},
            })""")
            # Draw the diagram and measure it, so the PDF page fits it exactly.
            size = page.evaluate(
                """async ([name, src]) => {
                    const {svg} = await mermaid.render('d_' + name, src);
                    const out = document.getElementById('out');
                    out.innerHTML = svg;
                    const el = out.querySelector('svg');
                    el.style.maxWidth = 'none';
                    const box = out.getBoundingClientRect();
                    return [Math.ceil(box.width), Math.ceil(box.height)];
                }""",
                [name, source],
            )
            target = OUT / f"{name}.pdf"
            page.pdf(path=str(target), width=f"{size[0]}px", height=f"{size[1] + 2}px",
                     print_background=True, page_ranges="1")
            print(f"{target.name}: {size[0]} x {size[1]} px")
        browser.close()


if __name__ == "__main__":
    main(set(sys.argv[1:]))
