// Builds "Tactical Eye - Thesis.docx" from the chapter files in content/.
//
// The chapters are written in a small Markdown dialect:
//   # Chapter / ## Section / ### Subsection   numbered automatically (# *Title = unnumbered)
//   #### Heading                              unnumbered minor heading
//   paragraph text with **bold**, *italic* and `code`
//   - bullet (indent two spaces per level) / 1. numbered item
//   Table: caption {widths=30,70}  followed by | pipe | table |  (first row = header)
//   ![caption](path/to/image.png){w=15}      figure, width in cm
//   Listing: caption  followed by a ```fenced``` code block
//   $$ formula $$                            centred formula line
//   \newpage                                 page break
//
//   npm install && node build.js
const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, Footer, Header, HeadingLevel, ImageRun, LevelFormat,
  PageBreak, PageNumber, Packer, Paragraph, ShadingType, Table, TableCell, TableOfContents,
  TableRow, TextRun, WidthType,
} = require("docx");

const HERE = __dirname;
const OUTPUT = path.join(HERE, "Tactical Eye - Thesis.docx");
const META = {
  university: "EÖTVÖS LORÁND UNIVERSITY",
  faculty: "FACULTY OF INFORMATICS",
  department: "DEPARTMENT OF MEDIA AND EDUCATIONAL TRAINING",
  title: "Tactical Eye",
  subtitle: "Automated Video Analytics & Tactical Visualization Platform",
  supervisor: ["Gaál Bence", "Assistant Professor"],
  author: ["Mudassir Ahmed Chaudhry", "BSc Computer Science"],
  place: "Budapest, 2026",
};

const FONT = "Times New Roman";
const MONO = "Consolas";
const PAGE_WIDTH_DXA = 11906 - 2 * 1418; // A4 minus 2.5 cm margins
const CM = 1440 / 2.54;

// ---------------------------------------------------------------- inline text
function runs(text, base = {}) {
  const out = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) out.push(new TextRun({ text: text.slice(last, match.index), ...base }));
    const token = match[0];
    if (token.startsWith("**")) out.push(new TextRun({ text: token.slice(2, -2), bold: true, ...base }));
    else if (token.startsWith("`")) out.push(new TextRun({ text: token.slice(1, -1), font: MONO, size: 21, ...base }));
    else out.push(new TextRun({ text: token.slice(1, -1), italics: true, ...base }));
    last = match.index + token.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

// ---------------------------------------------------------------- images
function pngSize(file) {
  const buffer = fs.readFileSync(file);
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20), buffer };
}

// ---------------------------------------------------------------- state
const counters = { chapter: 0, section: 0, subsection: 0, figure: 0, table: 0, listing: 0, list: 0 };
const chapterLabel = () => String(counters.chapter);
// Every numbered item, written to numbering.txt to help keep cross-references right.
const numbering = [];

function heading(level, text) {
  const unnumbered = text.startsWith("*");
  const title = unnumbered ? text.slice(1).trim() : text;
  let number = "";
  if (level === 1) {
    if (!unnumbered) {
      counters.chapter += 1;
      counters.section = 0;
      counters.figure = 0;
      counters.table = 0;
      counters.listing = 0;
      number = `${counters.chapter}  `;
    }
  } else if (level === 2) {
    counters.section += 1;
    counters.subsection = 0;
    number = `${counters.chapter}.${counters.section}  `;
  } else if (level === 3) {
    counters.subsection += 1;
    number = `${counters.chapter}.${counters.section}.${counters.subsection}  `;
  }
  if (number) numbering.push(`${number.trim()}  ${title}`);
  const levels = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3, HeadingLevel.HEADING_4];
  return new Paragraph({
    heading: levels[level - 1],
    pageBreakBefore: level === 1,
    children: [new TextRun(number + title)],
  });
}

function figure(caption, file, widthCm) {
  counters.figure += 1;
  numbering.push(`    Figure ${chapterLabel()}.${counters.figure}: ${caption}`);
  const { width, height, buffer } = pngSize(path.join(HERE, file));
  const maxHeightCm = 21;
  let w = widthCm;
  let h = (widthCm * height) / width;
  if (h > maxHeightCm) {
    h = maxHeightCm;
    w = (maxHeightCm * width) / height;
  }
  const px = (cm) => Math.round((cm / 2.54) * 96);
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      keepNext: true,
      spacing: { before: 120, after: 60 },
      children: [new ImageRun({ type: "png", data: buffer, transformation: { width: px(w), height: px(h) },
        altText: { title: caption, description: caption, name: path.basename(file) } })],
    }),
    new Paragraph({
      style: "Caption",
      alignment: AlignmentType.CENTER,
      children: runs(`Figure ${chapterLabel()}.${counters.figure}: ${caption}`),
    }),
  ];
}

function table(caption, widths, rows) {
  counters.table += 1;
  numbering.push(`    Table ${chapterLabel()}.${counters.table}: ${caption}`);
  const columns = rows[0].length;
  const weights = widths && widths.length === columns ? widths : Array(columns).fill(1);
  const total = weights.reduce((a, b) => a + b, 0);
  const columnWidths = weights.map((w) => Math.floor((w / total) * PAGE_WIDTH_DXA));
  const border = { style: BorderStyle.SINGLE, size: 4, color: "8A8A8A" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const out = [];
  if (caption) {
    out.push(new Paragraph({
      style: "Caption", keepNext: true, spacing: { before: 200, after: 80 },
      children: runs(`Table ${chapterLabel()}.${counters.table}: ${caption}`),
    }));
  }
  out.push(new Table({
    width: { size: PAGE_WIDTH_DXA, type: WidthType.DXA },
    columnWidths,
    rows: rows.map((cells, r) => new TableRow({
      tableHeader: r === 0,
      cantSplit: true,
      children: cells.map((cell, c) => new TableCell({
        borders,
        width: { size: columnWidths[c], type: WidthType.DXA },
        shading: r === 0 ? { fill: "DCE6E2", type: ShadingType.CLEAR, color: "auto" } : undefined,
        margins: { top: 50, bottom: 50, left: 90, right: 90 },
        children: cell.split("<br>").map((part) => new Paragraph({
          spacing: { line: 250, before: 0, after: 0 },
          children: runs(part.trim(), { size: 20, bold: r === 0 ? true : undefined }),
        })),
      })),
    })),
  }));
  out.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
  return out;
}

function listing(caption, lines) {
  const out = [];
  if (caption) {
    counters.listing += 1;
    numbering.push(`    Listing ${chapterLabel()}.${counters.listing}: ${caption}`);
    out.push(new Paragraph({
      style: "Caption", keepNext: true, spacing: { before: 200, after: 60 },
      children: runs(`Listing ${chapterLabel()}.${counters.listing}: ${caption}`),
    }));
  }
  lines.forEach((line, i) => out.push(new Paragraph({
    keepNext: i < lines.length - 1,
    spacing: { line: 240, before: 0, after: 0 },
    shading: { fill: "F3F4F6", type: ShadingType.CLEAR, color: "auto" },
    indent: { left: 200, right: 200 },
    children: [new TextRun({ text: line.length ? line : " ", font: MONO, size: 17 })],
  })));
  out.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
  return out;
}

// ---------------------------------------------------------------- parser
function parse(markdown) {
  const lines = markdown.replace(/\r/g, "").split("\n");
  const out = [];
  let paragraph = [];
  let pendingTable = null;
  let pendingListing = null;
  let listType = null;

  const flush = () => {
    if (paragraph.length) {
      const text = paragraph.join(" ");
      // Bibliography entries contain long URLs, which justification would stretch.
      const alignment = /^\[\d+\]/.test(text) ? AlignmentType.LEFT : AlignmentType.JUSTIFIED;
      out.push(new Paragraph({ alignment, children: runs(text) }));
      paragraph = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      flush();
      const code = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith("```"); i++) code.push(lines[i]);
      out.push(...listing(pendingListing, code));
      pendingListing = null;
      continue;
    }
    if (!trimmed) {
      flush();
      listType = null;
      continue;
    }
    if (trimmed === "\\newpage") {
      flush();
      out.push(new Paragraph({ children: [new PageBreak()] }));
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (h) {
      flush();
      out.push(heading(h[1].length, h[2]));
      continue;
    }
    const tableCaption = /^Table:\s*(.*?)\s*(\{widths=([\d,.]+)\})?$/.exec(trimmed);
    if (tableCaption) {
      flush();
      pendingTable = { caption: tableCaption[1], widths: tableCaption[3]?.split(",").map(Number) };
      continue;
    }
    if (trimmed.startsWith("Listing:")) {
      flush();
      pendingListing = trimmed.slice(8).trim();
      continue;
    }
    if (trimmed.startsWith("|")) {
      flush();
      const rows = [];
      for (; i < lines.length && lines[i].trim().startsWith("|"); i++) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, "|").trim());
        if (cells.every((c) => /^:?-{3,}:?$/.test(c))) continue;
        rows.push(cells);
      }
      i--;
      out.push(...table(pendingTable?.caption, pendingTable?.widths, rows));
      pendingTable = null;
      continue;
    }
    const image = /^!\[(.*)\]\((.*?)\)(\{w=([\d.]+)\})?$/.exec(trimmed);
    if (image) {
      flush();
      out.push(...figure(image[1], image[2], Number(image[4] ?? 15)));
      continue;
    }
    const formula = /^\$\$(.*)\$\$$/.exec(trimmed);
    if (formula) {
      flush();
      out.push(new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { before: 120, after: 120 },
        children: [new TextRun({ text: formula[1].trim(), font: "Cambria Math", italics: true })],
      }));
      continue;
    }
    const bullet = /^(\s*)[-*]\s+(.*)$/.exec(line);
    const numbered = /^(\s*)\d+\.\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flush();
      const match = bullet ?? numbered;
      const level = Math.min(Math.floor(match[1].length / 2), 2);
      if (numbered && listType !== "numbered") counters.list += 1;
      listType = numbered ? "numbered" : listType === "numbered" ? "numbered" : "bullet";
      out.push(new Paragraph({
        alignment: AlignmentType.LEFT,
        spacing: { after: 40 },
        numbering: bullet
          ? { reference: "bullets", level }
          : { reference: "numbers", level, instance: counters.list },
        children: runs(match[2]),
      }));
      continue;
    }
    paragraph.push(trimmed);
  }
  flush();
  return out;
}

// ---------------------------------------------------------------- title page
function titlePage() {
  const centred = (text, size, opts = {}) => new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 80 },
    children: [new TextRun({ text, size, font: "Arial", ...opts })],
  });
  const block = (label, lines, align) => [label, ...lines].map((text, i) => new Paragraph({
    alignment: align, spacing: { after: 0, line: 300 },
    children: [new TextRun({ text, font: "Arial", size: 24, bold: i === 1 })],
  }));
  const twoColumns = new Table({
    width: { size: PAGE_WIDTH_DXA, type: WidthType.DXA },
    columnWidths: [PAGE_WIDTH_DXA / 2, PAGE_WIDTH_DXA / 2],
    borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE },
      right: { style: BorderStyle.NONE }, insideHorizontal: { style: BorderStyle.NONE }, insideVertical: { style: BorderStyle.NONE } },
    rows: [new TableRow({ children: [
      new TableCell({ width: { size: PAGE_WIDTH_DXA / 2, type: WidthType.DXA }, children: block("Supervisor:", META.supervisor, AlignmentType.LEFT) }),
      new TableCell({ width: { size: PAGE_WIDTH_DXA / 2, type: WidthType.DXA }, children: block("Author:", META.author, AlignmentType.RIGHT) }),
    ] })],
  });
  const gap = (twips) => new Paragraph({ spacing: { before: twips }, children: [] });
  return [
    gap(200),
    centred(META.university, 30, { bold: true }),
    centred(META.faculty, 26, { bold: true }),
    centred(META.department, 24, { bold: true }),
    gap(2200),
    centred(META.title, 52, { bold: true }),
    centred(META.subtitle, 30),
    gap(2600),
    twoColumns,
    gap(900),
    centred(META.place, 24),
    new Paragraph({ children: [new PageBreak()] }),
    new Paragraph({ spacing: { after: 360 }, children: [new TextRun({ text: "Contents", font: "Arial", size: 36, bold: true, color: "0F3D33" })] }),
    new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-3" }),
  ];
}

// ---------------------------------------------------------------- document
function build() {
  const files = fs.readdirSync(path.join(HERE, "content")).filter((f) => f.endsWith(".md")).sort();
  const body = files.flatMap((file) => parse(fs.readFileSync(path.join(HERE, "content", file), "utf8")));

  const doc = new Document({
    creator: META.author[0],
    title: `${META.title}: ${META.subtitle}`,
    description: "BSc thesis documentation",
    features: { updateFields: true },
    styles: {
      default: { document: { run: { font: FONT, size: 24 }, paragraph: { spacing: { line: 360, after: 120 } } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 36, bold: true, font: "Arial", color: "0F3D33" },
          paragraph: { spacing: { before: 240, after: 360 }, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 28, bold: true, font: "Arial", color: "0F3D33" },
          paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 1, keepNext: true } },
        { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 25, bold: true, font: "Arial", color: "1F2937" },
          paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 2, keepNext: true } },
        { id: "Heading4", name: "Heading 4", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 24, bold: true, italics: true, font: FONT },
          paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 3, keepNext: true } },
        { id: "Caption", name: "Caption", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 20, italics: true, color: "374151" },
          paragraph: { spacing: { before: 60, after: 240, line: 260 } } },
      ],
    },
    numbering: {
      config: [
        { reference: "bullets", levels: [0, 1, 2].map((level) => ({
          level, format: LevelFormat.BULLET, text: ["•", "–", "▪"][level], alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720 + level * 360, hanging: 300 } } },
        })) },
        { reference: "numbers", levels: [0, 1, 2].map((level) => ({
          level, format: [LevelFormat.DECIMAL, LevelFormat.LOWER_LETTER, LevelFormat.LOWER_ROMAN][level],
          text: `%${level + 1}.`, alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720 + level * 360, hanging: 360 } } },
        })) },
      ],
    },
    sections: [{
      properties: {
        titlePage: true,
        page: { size: { width: 11906, height: 16838 }, margin: { top: 1418, bottom: 1418, left: 1418, right: 1418 } },
      },
      headers: {
        first: new Header({ children: [] }),
        default: new Header({ children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "9CA3AF", space: 4 } },
          children: [new TextRun({ text: `${META.title}: ${META.subtitle}`, size: 18, color: "6B7280", font: "Arial" })],
        })] }),
      },
      footers: {
        first: new Footer({ children: [] }),
        default: new Footer({ children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ children: [PageNumber.CURRENT], size: 20 })],
        })] }),
      },
      children: [...titlePage(), ...body],
    }],
  });
  return Packer.toBuffer(doc).then((buffer) => {
    fs.writeFileSync(OUTPUT, buffer);
    fs.writeFileSync(path.join(HERE, "numbering.txt"), `${numbering.join("\n")}\n`);
    console.log(`Wrote ${OUTPUT}: ${counters.chapter} chapters`);
  });
}

build().catch((error) => {
  console.error(error);
  process.exit(1);
});
