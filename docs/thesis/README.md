# Thesis documentation

Source of the BSc thesis document *Tactical Eye: Automated Video Analytics & Tactical Visualization Platform*.

| Path | Content |
|---|---|
| `content/*.md` | The chapters, in a small Markdown dialect described at the top of `build.js` |
| `figures/` | Diagrams, charts and cropped screenshots used in the document |
| `screenshots/` | Raw dashboard screenshots (1440 × 900) |
| `diagrams.mmd` | Mermaid sources of the diagrams |

Building (Windows, with Node.js, Microsoft Edge and Microsoft Word installed):

```bash
npm install                                  # docx and mermaid
python render_diagrams.py                    # diagrams.mmd -> figures/*.png (needs playwright)
python make_figures.py                       # charts and algorithm figures (worker's Python environment)
python capture_screenshots.py <clips dir>    # optional: new screenshots from the running platform
python crop_screenshots.py                   # screenshots/ -> figures/ss_*.png
node build.js                                # -> "Tactical Eye - Thesis.docx" and numbering.txt
powershell -ExecutionPolicy Bypass -File export_pdf.ps1   # fills in the contents, -> PDF
```

`numbering.txt` lists every numbered heading, figure, table and listing; use it to check
cross-references such as "Table 3.8" after editing the chapters.
