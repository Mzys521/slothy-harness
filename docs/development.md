# Development

## Local tools

Use Git, Python 3.11+, a Node.js version supported by the installed Vite release, npm, and PowerShell.

## Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

With MSYS2 Python, activation is `.\.venv\bin\Activate.ps1`; its interpreter is `.\.venv\bin\python.exe`.

The virtual environment and `.env` are local and ignored by Git. Copy `.env.example` to `.env` only when configuration is needed; do not commit secrets.

## Frontend

```powershell
cd frontend
npm install
npm run dev
npm run build
```

The Vue workspace now calls the real loopback desktop API through Vite's `/api` proxy. Build with `npm --prefix frontend run build`, then launch `python -m slothy.desktop` from the repository root; add `--browser` for a browser preview. See [Desktop layout and verification](desktop-ui.md). The desktop does not use a fake model fallback.

Switch modes at the top of the sidebar. In sloty coding, create a project and
attach a source folder; Settings configures permissions and execution budgets.
File edits and fixed project checks each require a human decision followed by
resume. Coding adapters live in Infrastructure; Application persists settings
and binds each task to its original directory/permissions. See [ADR 0016](decisions/0016-coding-agent-mode-and-controlled-tools.md) and [ADR 0017](decisions/0017-work-modes-and-project-workspaces.md).

## Branches

`main` is the baseline branch; `dev` is for ongoing integration. Suggested short-lived branch prefixes: `feature/`, `fix/`, `refactor/`, `docs/`, `chore/`, and `release/`.

## Runtime demonstration and Application

`main.py` is an independent validation program, not a product service. Run the assembled offline demo with:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --demo
```

Real MiMo calls require explicit `--live`; use `--live --interactive` for a prompt loop. See [Demo composition](main-demo.md). Product hosts inject dependencies into `RuntimeService` and call `RuntimeAPI` from Presentation; see [Application API](application-api.md) and [ADR 0011](decisions/0011-application-api-and-demo-composition.md).

[Controlled RAG tools](context-system.md) are implemented as Context adapters; the Core remains independent of provider SDKs and SQLite. [MCP, automated source ingestion and manifests](plans/mcp-rag-plan.md) remain planned extensions. Implement those only when their contracts and minimal use cases are authorized.

## Documentation

Record consequential decisions in `docs/decisions/` using numbered names such as `0001-project-architecture.md`. Follow [Theme Color Constraints](Theme-Color-Constraints.md) for brand colors and semantic tokens.


Desktop users configure DeepSeek, Qwen, MiMo or GLM directly in Settings; endpoints and default text models are preset. API keys use Windows DPAPI storage, and UI model selection applies to new tasks in either work mode. Keep supplier SDK/credential code in Infrastructure and inject it in desktop.py; see [model providers](model-providers.md) and [ADR 0018](decisions/0018-model-providers-and-secure-credentials.md). Offline SDK integration uses temporary fake credentials and MockTransport; the model UI fixture on port 8767 never calls an external API.
