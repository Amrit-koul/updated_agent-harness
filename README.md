# AgentHarness

AgentHarness is a governed agentic AI platform for banking demos. It combines a
FastAPI backend, a React control plane, reusable agent governance, and seeded
local data.

The included demos cover:

- Policy assistance using retrieval-augmented generation (RAG)
- Retail loan assessment
- Collections intelligence workflows
- Agent registration, contracts, budgets, authorization, and kill switches
- Audit logs, observability, usage tracking, MCP governance, and A2A endpoints

## Quick start

### Prerequisites

Install the following tools before starting:

- Python 3.10 or newer
- Node.js 18 or newer
- npm
- A Groq API key for live AI responses

The control plane can start without a Groq API key, but chat, loan, voice, and
other model-backed operations will not work.

### 1. Clone the repository

```bash
git clone https://github.com/Amrit-koul/updated_agent-harness.git
cd updated_agent-harness
```

### 2. Start the backend

Open a terminal in the repository root:

```bash
cd Backend
python -m venv .venv
```

Activate the virtual environment.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
source .venv/bin/activate
```

Install the Python dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create `Backend/banking_agents/.env` and add your Groq API key:

```dotenv
GROQ_API_KEY=your_groq_api_key
```

Start the API from the `Backend` directory:

```bash
python -m uvicorn banking_agents.main:app --host 127.0.0.1 --port 8000 --reload
```

The backend is ready when this URL returns a successful response:

```text
http://127.0.0.1:8000/health
```

API documentation is available at:

```text
http://127.0.0.1:8000/docs
```

On the first run, the backend may take longer to initialize while the local
embedding model is downloaded.

### 3. Start the frontend

Keep the backend running. Open a second terminal in the repository root:

```bash
cd Frontend
npm install
npm run dev
```

Open the application at:

```text
http://localhost:5173
```

No frontend environment file is needed for local development. Vite proxies
`/api` and `/health` requests to `http://localhost:8000` by default.

## Optional configuration

Add optional backend settings to `Backend/banking_agents/.env`.

### LangSmith tracing

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_PROJECT=aria-agent-harness-demo
```

### Control-plane administration

To enable the RBAC administration screen locally, set a matching secret in the
backend and frontend.

`Backend/banking_agents/.env`:

```dotenv
CONTROL_PLANE_ADMIN_SECRET=replace_with_a_local_demo_secret
```

`Frontend/.env`:

```dotenv
VITE_CONTROL_PLANE_ADMIN_SECRET=replace_with_a_local_demo_secret
```

Restart both servers after changing environment files. Vite environment values
are visible in browser code, so this setup is for local demonstrations only and
must not be used as production authentication.

### Custom backend URL

The frontend uses the local proxy by default. If the API runs elsewhere, create
`Frontend/.env`:

```dotenv
VITE_API_BASE=http://127.0.0.1:8000
```

## Seeded data and document ingestion

The repository includes the data needed for the demo:

- `Backend/data/control_plane.db` contains seeded control-plane and audit data.
- `Backend/chroma_db/` contains the prebuilt policy and loan vector stores.

You do not need to ingest documents for the normal quick start.

If you add or replace documents in `Backend/data_ingestion/policy_documents/`,
rebuild the vector store from the `Backend` directory:

```bash
python data_ingestion/ingest_docs.py
```

## Useful URLs

| Page | URL |
| --- | --- |
| Control plane | `http://localhost:5173/control/tower` |
| Policy assistant | `http://localhost:5173/chat` |
| Loan assessment | `http://localhost:5173/loan-assessment` |
| Collections demo | `http://localhost:5173/collections` |
| Backend health | `http://127.0.0.1:8000/health` |
| API documentation | `http://127.0.0.1:8000/docs` |

## Verify the installation

With the backend running, check it from another terminal:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/control/agents
```

Run the backend tests from `Backend`:

```bash
python -m unittest discover -s tests -v
```

Create a production frontend build from `Frontend`:

```bash
npm run build
```

## Troubleshooting

### `python` is not recognized on Windows

Install Python and enable the **Add Python to PATH** option. If the Python
launcher is available, replace `python` with `py -3.10` in the commands above.

### PowerShell blocks virtual-environment activation

Run this once in the current PowerShell window, then activate the environment
again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### The frontend cannot reach the backend

Confirm that the backend is running on port `8000` and that
`http://127.0.0.1:8000/health` opens successfully. Restart Vite after changing
`Frontend/.env`.

### AI operations report a missing API key

Confirm that `GROQ_API_KEY` is in `Backend/banking_agents/.env`, then restart the
backend. Do not commit `.env` files; they are excluded by `.gitignore`.

## Project structure

```text
Final_AgentHarness/
|-- Backend/
|   |-- agent_harness/       Reusable governance and runtime library
|   |-- banking_agents/      FastAPI app, agents, routes, and configuration
|   |-- chroma_db/           Seeded vector store
|   |-- data/                Seeded SQLite data
|   |-- data_ingestion/      Policy documents and ingestion script
|   `-- tests/               Backend test suite
|-- Frontend/                React and Vite application
`-- docs/                    Architecture, feature, and demo documentation
```
