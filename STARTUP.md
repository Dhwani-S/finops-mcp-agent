# FinOps MCP Agent — Local Setup Guide

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Git | any recent |
| Google Cloud SDK | latest (`gcloud`) |

---

## 1. Clone & Navigate

```bash
git clone <repo-url>
cd finops-mcp-agent
```

---

## 2. Python Backend Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate (macOS / Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 3. Environment Variables

Copy the example and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with the following variables:

| Variable | Description |
|----------|-------------|
| `GCP_PROJECT_ID` | Vertex AI project (e.g. `cie-costmanagement-803717`) |
| `BQ_DATA_PROJECT` | BigQuery data project (e.g. `cie-costmanagement-prod-152136`) |
| `GCP_LOCATION` | GCP region (e.g. `us-central1`) |
| `GEMINI_MODEL` | Model name (e.g. `gemini-2.5-pro`) |
| `GOOGLE_GENAI_USE_VERTEXAI` | Set to `TRUE` for Vertex AI auth |
| `GOOGLE_CLOUD_PROJECT` | Same as `GCP_PROJECT_ID` |
| `GOOGLE_CLOUD_LOCATION` | Same as `GCP_LOCATION` |
| `SQL_SERVER_HOST` | Azure SQL Server hostname |
| `SQL_SERVER_DB` | SQL database name |
| `SQL_SERVER_USER` | SQL username |
| `SQL_SERVER_PASS` | SQL password |

### Authentication (choose one)

**Option A — GCP Application Default Credentials (recommended):**

```bash
gcloud auth application-default login
```

**Option B — Service account key (base64):**

Set `GCP_DEV_CREDENTIALS_BASE64` in `.env` to the base64-encoded service account JSON.

**Option C — Service account key file:**

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa-key.json"
```

---

## 4. Initialize State

Ensure state files exist (run once):

```bash
# Windows PowerShell
New-Item -Path state -ItemType Directory -Force
Set-Content -Path state\memory.json -Value "[]"
Set-Content -Path state\conversation.json -Value "[]"

# macOS / Linux
mkdir -p state
echo "[]" > state/memory.json
echo "[]" > state/conversation.json
```

---

## 5. Start Backend

```bash
# From project root, with venv activated
python -m uvicorn web_api:app --port 8000
```

You should see:

```
finops-agent | INFO | Agent ready — 30 tools across 5 servers
INFO:     Uvicorn running on http://127.0.0.1:8000
```

The backend starts 5 MCP servers (stdio) automatically:

| Server | Tools | Purpose |
|--------|-------|---------|
| bq | 5 | BigQuery cost queries |
| analytics | 9 | Anomaly detection, forecasting |
| file | 6 | Report generation (CSV/MD) |
| cross_examine | 6 | Cross-cloud comparison, rightsizing |
| sql | 4 | Recommendations, identity lookup |

---

## 6. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at **http://localhost:5173**. The Vite dev server proxies `/api/*` requests to the backend on port 8000.

---

## 7. Verify

1. Open http://localhost:5173 in your browser
2. You should see the FinOps Agent chat interface
3. Try: *"Show me my cloud spend breakdown across all clouds"*
4. The agent should respond with cost data and charts

---

## Resetting State

To clear conversation history and memory between sessions:

```bash
# Windows PowerShell
Set-Content -Path state\memory.json -Value "[]"
Set-Content -Path state\conversation.json -Value "[]"

# macOS / Linux
echo "[]" > state/memory.json
echo "[]" > state/conversation.json
```

Then hit the "New Chat" button in the UI, or restart the backend.

---

## Project Structure

```
finops-mcp-agent/
├── agent.py                  # Core agent — MCP orchestration + Gemini loop
├── web_api.py                # FastAPI server — SSE streaming, perception layer
├── artifacts.py              # Content-addressable artifact store
├── memory.py                 # Session memory persistence
├── trace.py                  # Tool call tracing
├── a2a_server.py             # A2A federation server (optional, port 9108)
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── prompts/
│   └── system_prompt.md      # Agent system prompt
├── mcp_servers/
│   ├── finops_bq_server_v2.py
│   ├── finops_analytics_server.py
│   ├── finops_file_server.py
│   ├── finops_cross_examine_server.py
│   └── finops_sql_server_deprecated.py
├── state/
│   ├── memory.json
│   ├── conversation.json
│   └── artifacts/
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
├── docs/
└── tests/
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Import "google.genai" could not be resolved` | Make sure venv is activated and `pip install -r requirements.txt` completed |
| Port 8000 already in use | Kill existing process: `Get-NetTCPConnection -LocalPort 8000 \| Select -Exp OwningProcess \| % { Stop-Process -Id $_ -Force }` |
| `quota exceeded` warning | Run `gcloud auth application-default login` to refresh credentials |
| Frontend can't reach API | Ensure backend is running on port 8000 before starting frontend |
| Empty agent response | Check that `.env` variables are set correctly, especially `GOOGLE_GENAI_USE_VERTEXAI=TRUE` |
