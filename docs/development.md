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

This currently runs the Vue workspace. The desktop host and bridge are planned, not yet runnable.

## Branches

`main` is the baseline branch; `dev` is for ongoing integration. Suggested short-lived branch prefixes: `feature/`, `fix/`, `refactor/`, `docs/`, `chore/`, and `release/`.

## Runtime demonstration and Application

`main.py` is an independent validation program, not a product service. Run the assembled offline demo with:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m slothy.main --demo
```

Real MiMo calls require explicit `--live`; use `--live --interactive` for a prompt loop. See [Demo composition](main-demo.md). Product hosts inject dependencies into `RuntimeService` and call `RuntimeAPI` from Presentation; see [Application API](application-api.md) and [ADR 0011](decisions/0011-application-api-and-demo-composition.md).

[MCP and RAG](plans/mcp-rag-plan.md) are planned extensions only. Do not add their SDKs or empty interfaces before the corresponding contract and minimal use case are approved for implementation.

## Documentation

Record consequential decisions in `docs/decisions/` using numbered names such as `0001-project-architecture.md`. Follow [Theme Color Constraints](Theme-Color-Constraints.md) for brand colors and semantic tokens.
