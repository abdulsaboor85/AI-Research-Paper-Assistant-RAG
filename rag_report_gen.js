// ====================================================
//  PATH  →  rag_report_gen.js   (project root)
// ====================================================
//  Called automatically by rag_visualizer.py
//  DO NOT run this manually.
// ====================================================

const fs   = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageBreak, LevelFormat,
} = require("docx");

const jsonPath = process.argv[2];
const outPath  = process.argv[3];
const d        = JSON.parse(fs.readFileSync(jsonPath, "utf8"));

// ── Colors ────────────────────────────────────────────────────────────────────
const C = {
  blue:       "1F4E79",
  lightBlue:  "2E75B6",
  bgBlue:     "DEEAF1",
  bgGray:     "F2F2F2",
  bgGreen:    "E2EFDA",
  bgYellow:   "FFF2CC",
  bgOrange:   "FCE4D6",
  green:      "375623",
  orange:     "833C00",
  white:      "FFFFFF",
  black:      "000000",
  border:     "BFBFBF",
};

// ── Border helper ─────────────────────────────────────────────────────────────
const border = (color = C.border) => ({
  top:    { style: BorderStyle.SINGLE, size: 1, color },
  bottom: { style: BorderStyle.SINGLE, size: 1, color },
  left:   { style: BorderStyle.SINGLE, size: 1, color },
  right:  { style: BorderStyle.SINGLE, size: 1, color },
});

// ── Cell helper ───────────────────────────────────────────────────────────────
function cell(text, { width = 4680, fill = C.white, bold = false, color = C.black, size = 20, align = AlignmentType.LEFT } = {}) {
  return new TableCell({
    borders:  border(),
    width:    { size: width, type: WidthType.DXA },
    shading:  { fill, type: ShadingType.CLEAR },
    margins:  { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: align,
      children:  [new TextRun({ text: String(text), bold, color, size, font: "Consolas" })],
    })],
  });
}

// ── Header cell ───────────────────────────────────────────────────────────────
function hCell(text, width = 4680) {
  return cell(text, { width, fill: C.blue, bold: true, color: C.white, size: 20 });
}

// ── Section heading ───────────────────────────────────────────────────────────
function stepHeading(stepNum, title) {
  return new Paragraph({
    spacing: { before: 400, after: 160 },
    children: [
      new TextRun({ text: `STEP ${stepNum}  —  `, bold: true, size: 28, color: C.lightBlue, font: "Arial" }),
      new TextRun({ text: title,                  bold: true, size: 28, color: C.blue,      font: "Arial" }),
    ],
  });
}

// ── Plain paragraph ───────────────────────────────────────────────────────────
function para(text, { bold = false, size = 20, color = C.black, spacing = { before: 80, after: 80 } } = {}) {
  return new Paragraph({
    spacing,
    children: [new TextRun({ text, bold, size, color, font: "Arial" })],
  });
}

// ── Monospace paragraph (for vectors / code) ──────────────────────────────────
function mono(text, { fill = C.bgGray, size = 18 } = {}) {
  return new Paragraph({
    spacing: { before: 40, after: 40 },
    shading: { fill, type: ShadingType.CLEAR },
    indent:  { left: 360 },
    children: [new TextRun({ text, font: "Consolas", size, color: C.black })],
  });
}

// ── Similarity bar ────────────────────────────────────────────────────────────
function simBar(score) {
  const filled = Math.round(Math.max(0, score) * 28);
  const empty  = 28 - filled;
  return "█".repeat(filled) + "░".repeat(empty) + `  ${score.toFixed(4)}`;
}

// ── Format vector preview ─────────────────────────────────────────────────────
function fmtVec(preview, norm, dims) {
  const vals = preview.map(v => (v >= 0 ? "+" : "") + v.toFixed(4)).join(",   ");
  return [
    `[ ${vals},  ... ]`,
    `norm = ${norm.toFixed(4)}   total dims = ${dims}`,
  ];
}

// ── Page break ────────────────────────────────────────────────────────────────
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// ── Spacer ────────────────────────────────────────────────────────────────────
function spacer(before = 200) {
  return new Paragraph({ spacing: { before, after: 0 }, children: [new TextRun("")] });
}

// ─────────────────────────────────────────────────────────────────────────────
//  BUILD DOCUMENT
// ─────────────────────────────────────────────────────────────────────────────

const children = [];

// ════════════════════════════════════════════════════════
//  COVER
// ════════════════════════════════════════════════════════
children.push(
  spacer(1200),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing:   { before: 0, after: 240 },
    children:  [new TextRun({ text: "RAG Pipeline", bold: true, size: 56, color: C.blue, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing:   { before: 0, after: 600 },
    children:  [new TextRun({ text: "Full Visualization Report", bold: true, size: 40, color: C.lightBlue, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing:   { before: 0, after: 160 },
    children:  [new TextRun({ text: `PDF:  ${d.pdf_name}`, size: 24, color: C.black, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing:   { before: 0, after: 160 },
    children:  [new TextRun({ text: `Question:  ${d.question}`, size: 24, color: C.black, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing:   { before: 0, after: 160 },
    children:  [new TextRun({ text: `Embedding Model:  ${d.embed_model}  (${d.vector_dims} dims)`, size: 22, color: C.black, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing:   { before: 0, after: 160 },
    children:  [new TextRun({ text: `LLM:  ${d.llm_model}`, size: 22, color: C.black, font: "Arial" })],
  }),
  pageBreak(),
);

// ════════════════════════════════════════════════════════
//  STEP 1 — PDF EXTRACTION
// ════════════════════════════════════════════════════════
children.push(
  stepHeading(1, "PDF TEXT EXTRACTION"),
  para("pdfplumber reads each page word-by-word using x/y coordinates to reconstruct proper spacing. This fixes the common PDF problem where words are concatenated (e.g. hellomynameis → hello my name is).", { size: 20 }),
  spacer(160),
  new Table({
    width:        { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      new TableRow({ children: [hCell("Property", 3000), hCell("Value", 6360)] }),
      new TableRow({ children: [cell("File",        { width: 3000, fill: C.bgGray, bold: true }), cell(d.pdf_name,                     { width: 6360 })] }),
      new TableRow({ children: [cell("Total Words", { width: 3000, fill: C.bgGray, bold: true }), cell(`${d.raw_text_words} words`,     { width: 6360 })] }),
      new TableRow({ children: [cell("Method",      { width: 3000, fill: C.bgGray, bold: true }), cell("pdfplumber extract_words() with x/y coordinate grouping", { width: 6360 })] }),
    ],
  }),
  spacer(200),
  para("Extracted text sample (first 600 chars):", { bold: true }),
  mono(d.raw_text_sample, { fill: C.bgGray }),
  pageBreak(),
);

// ════════════════════════════════════════════════════════
//  STEP 2 — CHUNKING
// ════════════════════════════════════════════════════════
children.push(
  stepHeading(2, "TEXT CHUNKING"),
  para(`The extracted text is split into overlapping chunks of 100 words each, with a 20-word overlap between consecutive chunks. Overlap ensures that sentences spanning chunk boundaries are not lost. Total chunks produced: ${d.chunks.length}.`, { size: 20 }),
  spacer(160),
  new Table({
    width:        { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      new TableRow({ children: [hCell("Setting", 3000), hCell("Value", 6360)] }),
      new TableRow({ children: [cell("Chunk Size",    { width: 3000, fill: C.bgGray, bold: true }), cell("100 words",          { width: 6360 })] }),
      new TableRow({ children: [cell("Overlap",       { width: 3000, fill: C.bgGray, bold: true }), cell("20 words",           { width: 6360 })] }),
      new TableRow({ children: [cell("Total Chunks",  { width: 3000, fill: C.bgGray, bold: true }), cell(`${d.chunks.length}`, { width: 6360 })] }),
    ],
  }),
  spacer(200),
);

// All chunks table
const chunkHeaderRow = new TableRow({
  children: [hCell("Chunk #", 1200), hCell("Words", 1200), hCell("Text", 6960)],
});
const chunkRows = d.chunks.map(c =>
  new TableRow({
    children: [
      cell(`Chunk ${c.index}`, { width: 1200, fill: C.bgBlue, bold: true, align: AlignmentType.CENTER }),
      cell(`${c.word_count}`,  { width: 1200, fill: C.bgGray, align: AlignmentType.CENTER }),
      cell(c.text,             { width: 6960 }),
    ],
  })
);

children.push(
  new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [1200, 1200, 6960], rows: [chunkHeaderRow, ...chunkRows] }),
  pageBreak(),
);

// ════════════════════════════════════════════════════════
//  STEP 3 — CHUNK VECTORS
// ════════════════════════════════════════════════════════
children.push(
  stepHeading(3, "CHUNK EMBEDDINGS (VECTORS)"),
  para(`Each chunk is passed through the ${d.embed_model} model which converts the text into a ${d.vector_dims}-dimensional float vector. Semantically similar texts produce vectors that point in similar directions in this high-dimensional space. Only the first ${d.vector_preview} dimensions are shown below.`, { size: 20 }),
  spacer(160),
);

d.chunk_vectors.forEach(cv => {
  const [line1, line2] = fmtVec(cv.preview, cv.norm, d.vector_dims);
  children.push(
    para(`Chunk ${cv.chunk_index}  —  "${d.chunks[cv.chunk_index - 1].text.substring(0, 80)}${d.chunks[cv.chunk_index - 1].text.length > 80 ? "..." : ""}"`, { bold: true, size: 20, color: C.blue }),
    mono(line1),
    mono(line2, { fill: C.white }),
    spacer(120),
  );
});

children.push(pageBreak());

// ════════════════════════════════════════════════════════
//  STEP 4 — QUESTION VECTOR
// ════════════════════════════════════════════════════════
const [qLine1, qLine2] = fmtVec(d.question_vector.preview, d.question_vector.norm, d.vector_dims);

children.push(
  stepHeading(4, "QUESTION EMBEDDING (VECTOR)"),
  para(`The question is embedded using the same ${d.embed_model} model, producing a ${d.vector_dims}-dimensional vector. This vector captures the semantic meaning of the question and will be compared against every chunk vector using cosine similarity.`, { size: 20 }),
  spacer(200),
  para(`Question:  "${d.question}"`, { bold: true, size: 22, color: C.blue }),
  spacer(120),
  mono(qLine1, { fill: C.bgBlue }),
  mono(qLine2, { fill: C.bgBlue }),
  pageBreak(),
);

// ════════════════════════════════════════════════════════
//  STEP 5 — COSINE SIMILARITY
// ════════════════════════════════════════════════════════
children.push(
  stepHeading(5, "COSINE SIMILARITY — QUESTION vs ALL CHUNKS"),
  para("Cosine similarity measures the angle between two vectors in 384-dimensional space. A score of 1.0 means the vectors point in exactly the same direction (identical meaning). A score near 0.0 means unrelated content. The chunks with the highest scores are the most semantically relevant to the question.", { size: 20 }),
  spacer(160),
  new Table({
    width:        { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      new TableRow({ children: [hCell("Score", 3000), hCell("Meaning", 6360)] }),
      new TableRow({ children: [cell("1.00",  { width: 3000, fill: C.bgGreen }), cell("Identical meaning",    { width: 6360 })] }),
      new TableRow({ children: [cell("0.75+", { width: 3000, fill: C.bgGreen }), cell("Highly relevant",     { width: 6360 })] }),
      new TableRow({ children: [cell("0.50",  { width: 3000, fill: C.bgYellow }), cell("Somewhat related",   { width: 6360 })] }),
      new TableRow({ children: [cell("0.25",  { width: 3000, fill: C.bgOrange }), cell("Weakly related",     { width: 6360 })] }),
      new TableRow({ children: [cell("0.00",  { width: 3000 }),                   cell("Unrelated",          { width: 6360 })] }),
    ],
  }),
  spacer(240),
);

const simHeaderRow = new TableRow({
  children: [
    hCell("Rank",    1400),
    hCell("Chunk",   1200),
    hCell("Score",   1560),
    hCell("Bar",     2400),
    hCell("Status",  2800),
  ],
});
const simRows = d.similarities_ranked.map(r =>
  new TableRow({
    children: [
      cell(`${r.rank}`,       { width: 1400, fill: C.bgGray,  bold: true, align: AlignmentType.CENTER }),
      cell(`Chunk ${r.chunk_index}`, { width: 1200, fill: C.bgGray, align: AlignmentType.CENTER }),
      cell(`${r.score}`,      { width: 1560, fill: r.selected ? C.bgGreen : C.white, bold: r.selected, align: AlignmentType.CENTER }),
      cell(simBar(r.score),   { width: 2400, fill: r.selected ? C.bgGreen : C.white }),
      cell(r.selected ? "✓  SELECTED" : "skipped", { width: 2800, fill: r.selected ? C.bgGreen : C.white, bold: r.selected, color: r.selected ? C.green : C.black }),
    ],
  })
);

children.push(
  new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [1400, 1200, 1560, 2400, 2800], rows: [simHeaderRow, ...simRows] }),
  pageBreak(),
);

// ════════════════════════════════════════════════════════
//  STEP 6 — TOP-K CHUNKS SENT TO LLM
// ════════════════════════════════════════════════════════
children.push(
  stepHeading(6, `TOP ${d.top_k} CHUNKS SELECTED — SENT TO LLM`),
  para(`The ${d.top_k} chunks with the highest cosine similarity scores are selected as context. These chunks, along with the original question, are forwarded to the LLM (${d.llm_model}). The LLM is instructed to answer using only this context.`, { size: 20 }),
  spacer(160),
);

d.top_k_chunks.forEach(tk => {
  const [vLine1, vLine2] = fmtVec(tk.vector_preview, tk.norm, d.vector_dims);
  children.push(
    new Paragraph({
      spacing: { before: 240, after: 100 },
      shading: { fill: C.bgBlue, type: ShadingType.CLEAR },
      indent:  { left: 0 },
      children: [
        new TextRun({ text: `  Selected #${tk.rank}  —  Chunk ${tk.chunk_index}  (similarity: ${tk.score})`, bold: true, size: 22, color: C.blue, font: "Arial" }),
      ],
    }),
    mono(`Chunk Text:`, { fill: C.bgGray }),
    mono(tk.text, { fill: C.white }),
    spacer(80),
    mono(`Vector (first ${d.vector_preview} of ${d.vector_dims} dims):`),
    mono(vLine1),
    mono(vLine2, { fill: C.white }),
    spacer(200),
  );
});

children.push(
  para("Prompt structure sent to LLM:", { bold: true, size: 20 }),
  mono(`ROLE    : Research paper assistant`),
  mono(`CONTEXT : Top ${d.top_k} chunks selected above (${d.top_k_chunks.reduce((s, c) => s + c.text.split(" ").length, 0)} words total)`),
  mono(`QUESTION: ${d.question}`),
  mono(`RULE    : Answer using ONLY the provided context`),
  pageBreak(),
);

// ════════════════════════════════════════════════════════
//  STEP 7 — LLM ANSWER
// ════════════════════════════════════════════════════════
children.push(
  stepHeading(7, "LLM ANSWER"),
  new Table({
    width:        { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      new TableRow({ children: [hCell("Property", 3000), hCell("Value", 6360)] }),
      new TableRow({ children: [cell("Model Used",   { width: 3000, fill: C.bgGray, bold: true }), cell(d.llm_model,  { width: 6360 })] }),
      new TableRow({ children: [cell("Model Pool",   { width: 3000, fill: C.bgGray, bold: true }), cell(d.model_pool.join("  →  "), { width: 6360 })] }),
      new TableRow({ children: [cell("Question",     { width: 3000, fill: C.bgGray, bold: true }), cell(d.question,  { width: 6360 })] }),
    ],
  }),
  spacer(280),
  para("Answer:", { bold: true, size: 22, color: C.blue }),
  spacer(80),
  new Paragraph({
    spacing: { before: 120, after: 120 },
    indent:  { left: 360, right: 360 },
    shading: { fill: C.bgGreen, type: ShadingType.CLEAR },
    children: [new TextRun({ text: d.answer, size: 22, font: "Arial", color: C.black })],
  }),
  spacer(400),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "— End of RAG Pipeline Report —", size: 22, bold: true, color: C.lightBlue, font: "Arial" })],
  }),
);

// ─────────────────────────────────────────────────────────────────────────────
//  GENERATE DOCX
// ─────────────────────────────────────────────────────────────────────────────

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: "Arial", size: 20 } },
    },
  },
  numbering: { config: [] },
  sections: [{
    properties: {
      page: {
        size:   { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outPath, buffer);
  console.log(`Word document written to: ${outPath}`);
}).catch(err => {
  console.error("Error generating document:", err);
  process.exit(1);
});
