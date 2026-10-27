# Opens the generated thesis in Microsoft Word, fills in the table of contents
# and page numbers, saves the .docx and exports a PDF next to it.
#   powershell -ExecutionPolicy Bypass -File export_pdf.ps1
$ErrorActionPreference = "Stop"
$docx = Join-Path $PSScriptRoot "Tactical Eye - Thesis.docx"
$pdf = [System.IO.Path]::ChangeExtension($docx, ".pdf")

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($docx)
    $doc.Fields.Update() | Out-Null
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Save()
    $doc.ExportAsFixedFormat($pdf, 17)  # 17 = wdExportFormatPDF
    try { $doc.Close() } catch { }  # Word sometimes disconnects after exporting; the files are already written
} finally {
    try { $word.Quit() } catch { }
}
"Exported $pdf"
