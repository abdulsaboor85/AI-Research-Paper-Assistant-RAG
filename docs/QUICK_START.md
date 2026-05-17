# QUICK START - Copy & Paste Commands

## **🚀 First Time Setup (5 minutes)**

```bash
# 1. Clone the project
git clone https://github.com/abdulsaboor85/AI-Research-Paper-Assistant-RAG.git
cd AI-Research-Paper-Assistant-RAG

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 4. Install all Python packages
pip install -r requirements.txt

# 5. Install Node.js packages
npm install

# 6. Create .env file with your API key
# (Create a file named ".env" and add this line:)
# GEMINI_API_KEY=your_actual_key_from_aistudio.google.com
```

---

## **📚 Usage (After Setup)**

### **Run Full Visualization Pipeline:**
```bash
python src/rag_visualizer.py "papers/your_paper.pdf" "your question"
```

**Example:**
```bash
python src/rag_visualizer.py "papers/easy/cybersecurity_easy.pdf" "what should employees do"
```

**Output:** Creates `reports/<paper-name>__<question>/rag_report.docx` with full RAG visualization

---

### **Run Interactive Q&A:**
```bash
cd pipeline
python pipeline.py "../papers/easy/cybersecurity_easy.pdf"
```

Then type your questions (type `exit` to quit)

---

## **📋 Dependencies (in requirements.txt)**

| Package | Version | Purpose |
|---------|---------|---------|
| pdfplumber | 0.10.3 | PDF text extraction |
| python-dotenv | 1.0.0 | Load .env variables |
| sentence-transformers | 2.2.2 | Vector embeddings |
| numpy | 1.24.3 | Math operations |
| chromadb | 0.3.21 | Vector database |
| google-genai | 0.3.0 | Gemini API |

Node.js package: `docx` (for Word generation)

---

## **🔧 Common Issues & Fixes**

| Issue | Command to Fix |
|-------|----------------|
| Missing packages | `pip install -r requirements.txt` |
| API key error | Create `.env` with `GEMINI_API_KEY=your_key` |
| Module not found | `pip install --upgrade google-genai` |
| PDF not found | Use correct path: `"papers/file.pdf"` |

---

## **📁 File Structure**

```
AI-Research-Paper-Assistant-RAG/
├── src/
│   ├── rag_visualizer.py      ← Main script (run this)
│   └── analyze_pdf.py         ← Difficulty analyzer
├── scripts/
│   └── rag_report_gen.js      ← Word doc generator
├── docs/                      ← Guides and notes
├── assets/                    ← Images and visual assets
├── reports/                   ← Generated reports
├── pipeline/                  ← RAG pipeline modules
├── papers/                    ← Put your PDF files here
├── chroma_db/                 ← Auto-created vector database
├── requirements.txt           ← Install with: pip install -r requirements.txt
├── package.json               ← Install with: npm install
├── .env                       ← Create this! Add: GEMINI_API_KEY=...
└── .gitignore                 ← Prevents .env from being pushed
```

---

## **🎯 Full Example Workflow**

```bash
# Step 1: Clone
git clone https://github.com/abdulsaboor85/AI-Research-Paper-Assistant-RAG.git
cd AI-Research-Paper-Assistant-RAG

# Step 2: Setup (one time only)
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
npm install

# Step 3: Create .env
# (Create file ".env" with: GEMINI_API_KEY=your_key_here)

# Step 4: Add your PDF
# (Put your PDF in the papers/ folder)

# Step 5: Run!
python src/rag_visualizer.py "papers/easy/cybersecurity_easy.pdf" "What is this about?"

# Step 6: Check output
# (Open reports/<paper-name>__<question>/rag_report.docx)
```

---

## **✅ Verification Commands**

```bash
# Check Python packages installed correctly
pip list

# Check Node packages installed correctly
npm list docx

# Test Python imports
python -c "import pdfplumber, sentence_transformers, google.genai; print('✅ All packages OK')"

# Check if .env exists and has API key
type .env  # Windows
cat .env   # Mac/Linux
```

---

## **🔑 Getting the API Key**

1. Go to: **https://aistudio.google.com/app/apikey**
2. Click **"Create API Key"**
3. Copy the key
4. Create `.env` file with: `GEMINI_API_KEY=your_copied_key`

---

**That's it! Your friend is ready to go! 🚀**
