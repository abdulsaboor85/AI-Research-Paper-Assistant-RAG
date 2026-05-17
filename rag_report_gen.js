const fs = require("fs");
const { Document, Packer, Paragraph, Table, TableRow, TableCell, TextRun, BorderStyle, WidthType, AlignmentType, UnderlineType, HeadingLevel } = require("docx");

async function generateReport(jsonPath, docxPath) {
  const data = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));

  const sections = [];

  // ─────────────────────────────────────────────────────────────────────────────
  // TITLE PAGE
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "RAG PIPELINE VISUALIZATION REPORT",
      heading: HeadingLevel.HEADING_1,
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: `PDF: ${data.pdf_name}`,
      spacing: { after: 100 },
      bold: true,
    })
  );

  sections.push(
    new Paragraph({
      text: `Question: "${data.question}"`,
      spacing: { after: 100 },
      bold: true,
    })
  );

  sections.push(
    new Paragraph({
      text: `Embedding Model: ${data.embed_model}`,
      spacing: { after: 100 },
    })
  );

  sections.push(
    new Paragraph({
      text: `LLM Used: ${data.llm_model}`,
      spacing: { after: 400 },
    })
  );

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 1: RAW TEXT EXTRACTION
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 1: PDF TEXT EXTRACTION",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: `Total words extracted: ${data.raw_text_words}`,
      spacing: { after: 100 },
    })
  );

  sections.push(
    new Paragraph({
      text: "Sample (first 600 characters):",
      bold: true,
      spacing: { after: 50 },
    })
  );

  sections.push(
    new Paragraph({
      text: data.raw_text_sample,
      spacing: { after: 200 },
      border: {
        top: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
        bottom: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
        left: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
        right: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
      },
    })
  );

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 2: TEXT CHUNKING
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 2: TEXT CHUNKING",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: `Total chunks created: ${data.chunks.length}`,
      spacing: { after: 150 },
      bold: true,
    })
  );

  const chunkTableRows = [
    new TableRow({
      children: [
        new TableCell({
          children: [new Paragraph({ text: "Chunk #", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Word Count", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Text (Preview)", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
      ],
    }),
  ];

  data.chunks.slice(0, Math.min(10, data.chunks.length)).forEach((chunk) => {
    chunkTableRows.push(
      new TableRow({
        children: [
          new TableCell({
            children: [new Paragraph({ text: String(chunk.index) })],
          }),
          new TableCell({
            children: [new Paragraph({ text: String(chunk.word_count) })],
          }),
          new TableCell({
            children: [new Paragraph({ text: chunk.text.substring(0, 100) + "..." })],
          }),
        ],
      })
    );
  });

  if (data.chunks.length > 10) {
    chunkTableRows.push(
      new TableRow({
        children: [
          new TableCell({
            columnSpan: 3,
            children: [
              new Paragraph({
                text: `... and ${data.chunks.length - 10} more chunks`,
                italics: true,
              }),
            ],
          }),
        ],
      })
    );
  }

  sections.push(
    new Table({
      rows: chunkTableRows,
      width: { size: 100, type: WidthType.PERCENTAGE },
    })
  );

  sections.push(new Paragraph({ text: "", spacing: { after: 200 } }));

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 3: CHUNK EMBEDDING
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 3: CHUNK EMBEDDING",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: `Dimension: ${data.vector_dims}`,
      spacing: { after: 100 },
      bold: true,
    })
  );

  sections.push(
    new Paragraph({
      text: "Sample chunk vectors (first 8 dimensions shown):",
      spacing: { after: 100 },
      italics: true,
    })
  );

  const chunkVecTableRows = [
    new TableRow({
      children: [
        new TableCell({
          children: [new Paragraph({ text: "Chunk #", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Vector Preview", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Norm", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
      ],
    }),
  ];

  data.chunk_vectors.slice(0, Math.min(8, data.chunk_vectors.length)).forEach((vec) => {
    const preview = vec.preview
      .map((v) => v.toFixed(4))
      .join(", ");
    chunkVecTableRows.push(
      new TableRow({
        children: [
          new TableCell({
            children: [new Paragraph({ text: String(vec.chunk_index) })],
          }),
          new TableCell({
            children: [new Paragraph({ text: `[${preview}...]` })],
          }),
          new TableCell({
            children: [new Paragraph({ text: vec.norm.toFixed(4) })],
          }),
        ],
      })
    );
  });

  sections.push(
    new Table({
      rows: chunkVecTableRows,
      width: { size: 100, type: WidthType.PERCENTAGE },
    })
  );

  sections.push(new Paragraph({ text: "", spacing: { after: 200 } }));

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 4: QUESTION EMBEDDING
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 4: QUESTION EMBEDDING",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: `Question: "${data.question}"`,
      spacing: { after: 100 },
      italics: true,
    })
  );

  const qVecPreview = data.question_vector.preview
    .map((v) => v.toFixed(4))
    .join(", ");

  sections.push(
    new Paragraph({
      text: `Vector Preview (first 8 dims): [${qVecPreview}...]`,
      spacing: { after: 50 },
    })
  );

  sections.push(
    new Paragraph({
      text: `Vector Norm: ${data.question_vector.norm.toFixed(4)}`,
      spacing: { after: 200 },
    })
  );

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 5A: VECTOR COMPARISON (ENHANCED)
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 5A: VECTOR COMPARISON - QUESTION vs CHUNKS",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: "Comparing the question vector with each chunk vector (side-by-side):",
      spacing: { after: 150 },
      italics: true,
    })
  );

  // Show detailed comparison for top chunks
  data.vector_comparisons.slice(0, Math.min(5, data.vector_comparisons.length)).forEach((comparison) => {
    sections.push(
      new Paragraph({
        text: `Chunk ${comparison.chunk_index}: "${comparison.chunk_text.substring(0, 60)}..."`,
        bold: true,
        spacing: { after: 100, before: 100 },
      })
    );

    const qVecPrev = comparison.question_vector_preview
      .map((v) => v.toFixed(4))
      .join(", ");
    const cVecPrev = comparison.chunk_vector_preview
      .map((v) => v.toFixed(4))
      .join(", ");

    sections.push(
      new Table({
        rows: [
          new TableRow({
            children: [
              new TableCell({
                children: [
                  new Paragraph({
                    text: "Question Vector",
                    bold: true,
                    alignment: AlignmentType.CENTER,
                  }),
                ],
                shading: { fill: "B3D9FF" },
              }),
              new TableCell({
                children: [
                  new Paragraph({
                    text: "Chunk Vector",
                    bold: true,
                    alignment: AlignmentType.CENTER,
                  }),
                ],
                shading: { fill: "FFD9B3" },
              }),
            ],
          }),
          new TableRow({
            children: [
              new TableCell({
                children: [
                  new Paragraph({
                    text: `[${qVecPrev}...]`,
                    font: "Courier New",
                    size: 18,
                  }),
                ],
              }),
              new TableCell({
                children: [
                  new Paragraph({
                    text: `[${cVecPrev}...]`,
                    font: "Courier New",
                    size: 18,
                  }),
                ],
              }),
            ],
          }),
          new TableRow({
            children: [
              new TableCell({
                children: [
                  new Paragraph({
                    text: `Norm: ${comparison.question_vector_norm.toFixed(4)}`,
                  }),
                ],
              }),
              new TableCell({
                children: [
                  new Paragraph({
                    text: `Norm: ${comparison.chunk_vector_norm.toFixed(4)}`,
                  }),
                ],
              }),
            ],
          }),
        ],
        width: { size: 100, type: WidthType.PERCENTAGE },
      })
    );

    sections.push(new Paragraph({ text: "", spacing: { after: 150 } }));
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 5B: SIMILARITY CALCULATION BREAKDOWN (ENHANCED)
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 5B: COSINE SIMILARITY CALCULATION",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: "Formula: cos(θ) = (A · B) / (||A|| × ||B||)",
      spacing: { after: 150 },
      bold: true,
      font: "Courier New",
    })
  );

  // Show calculations for top chunks
  data.similarity_calculations.slice(0, Math.min(5, data.similarity_calculations.length)).forEach((calc) => {
    sections.push(
      new Paragraph({
        text: `Chunk ${calc.chunk_index}:`,
        bold: true,
        spacing: { after: 80, before: 80 },
      })
    );

    sections.push(
      new Paragraph({
        text: `Dot Product (A · B): ${calc.dot_product}`,
        spacing: { after: 40 },
      })
    );

    sections.push(
      new Paragraph({
        text: `Question Norm (||A||): ${calc.question_norm}`,
        spacing: { after: 40 },
      })
    );

    sections.push(
      new Paragraph({
        text: `Chunk Norm (||B||): ${calc.chunk_norm}`,
        spacing: { after: 40 },
      })
    );

    sections.push(
      new Paragraph({
        text: `Formula: ${calc.formula}`,
        spacing: { after: 80 },
        bold: true,
        font: "Courier New",
      })
    );

    sections.push(
      new Paragraph({
        text: `Similarity Score: ${calc.final_score}`,
        spacing: { after: 150 },
        bold: true,
        shading: { fill: "FFFF99" },
      })
    );
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 5C: SIMILARITY RANKING
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 5C: RANKING ALL CHUNKS BY SIMILARITY",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  const rankTableRows = [
    new TableRow({
      children: [
        new TableCell({
          children: [new Paragraph({ text: "Rank", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Chunk #", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Score", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Selected?", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
        new TableCell({
          children: [new Paragraph({ text: "Text Preview", bold: true })],
          shading: { fill: "E8E8E8" },
        }),
      ],
    }),
  ];

  data.similarities_ranked.forEach((sim) => {
    rankTableRows.push(
      new TableRow({
        children: [
          new TableCell({
            children: [new Paragraph({ text: String(sim.rank) })],
          }),
          new TableCell({
            children: [new Paragraph({ text: String(sim.chunk_index) })],
          }),
          new TableCell({
            children: [
              new Paragraph({
                text: sim.score.toFixed(4),
                bold: sim.selected,
                color: sim.selected ? "00AA00" : "000000",
              }),
            ],
          }),
          new TableCell({
            children: [
              new Paragraph({
                text: sim.selected ? "✓ YES" : "✗ NO",
                bold: sim.selected,
                color: sim.selected ? "00AA00" : "FF0000",
              }),
            ],
          }),
          new TableCell({
            children: [new Paragraph({ text: sim.text })],
          }),
        ],
      })
    );
  });

  sections.push(
    new Table({
      rows: rankTableRows,
      width: { size: 100, type: WidthType.PERCENTAGE },
    })
  );

  sections.push(new Paragraph({ text: "", spacing: { after: 200 } }));

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 6: TOP-K RETRIEVAL
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: `STEP 6: RETRIEVING TOP ${data.top_k} CHUNKS`,
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  data.top_k_chunks.forEach((chunk) => {
    sections.push(
      new Paragraph({
        text: `[Rank ${chunk.rank}] Chunk ${chunk.chunk_index} | Score: ${chunk.score.toFixed(4)}`,
        bold: true,
        spacing: { after: 50, before: 50 },
      })
    );

    sections.push(
      new Paragraph({
        text: chunk.text,
        spacing: { after: 100 },
        border: {
          top: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
          bottom: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
          left: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
          right: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
        },
      })
    );

    const vecPrev = chunk.vector_preview
      .map((v) => v.toFixed(4))
      .join(", ");

    sections.push(
      new Paragraph({
        text: `Vector: [${vecPrev}...] | Norm: ${chunk.norm.toFixed(4)}`,
        spacing: { after: 150 },
        italics: true,
        size: 18,
      })
    );
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // STEP 7: LLM RESPONSE
  // ─────────────────────────────────────────────────────────────────────────────
  sections.push(
    new Paragraph({
      text: "STEP 7: LLM GENERATED ANSWER",
      heading: HeadingLevel.HEADING_2,
      spacing: { after: 100, before: 200 },
    })
  );

  sections.push(
    new Paragraph({
      text: data.answer,
      spacing: { after: 200 },
      border: {
        top: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
        bottom: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
        left: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
        right: { color: "CCCCCC", space: 1, style: BorderStyle.SINGLE },
      },
    })
  );

  // ─────────────────────────────────────────────────────────────────────────────
  // CREATE DOCUMENT
  // ─────────────────────────────────────────────────────────────────────────────
  const doc = new Document({
    sections: [
      {
        children: sections,
      },
    ],
  });

  const packer = new Packer();
  packer.toBuffer(doc).then((buffer) => {
    fs.writeFileSync(docxPath, buffer);
    console.log(`✓ Word document generated: ${docxPath}`);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// ENTRY POINT
// ─────────────────────────────────────────────────────────────────────────────
const jsonPath = process.argv[2];
const docxPath = process.argv[3];

if (!jsonPath || !docxPath) {
  console.error("Usage: node rag_report_gen.js <json_path> <docx_path>");
  process.exit(1);
}

generateReport(jsonPath, docxPath);