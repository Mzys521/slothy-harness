# Slothy / 思洛

Slothy is a desktop project for building a Python based agent Harness with a Vue interface.

**Status:** Project skeleton only. The Harness, desktop bridge, and product UI are not implemented yet.

## Technology

- Desktop host: pywebview
- Frontend: Vue 3, TypeScript, Vite, Tailwind CSS
- Harness core: pure Python
- Repository: Python and frontend in one Git repository

## Architecture

`Vue → frontend bridge → pywebview presentation → application API/services → core`.
Infrastructure adapters implement the interfaces needed by the core; the core does not import desktop, UI, operating system, database, or LLM SDK code. See [architecture](docs/architecture.md).

## Prerequisites and local setup

Git, Python 3.11+, Node.js compatible with the installed Vite version, npm, and PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
cd frontend
npm install
npm run dev
```

When Python comes from MSYS2, use `.\.venv\bin\Activate.ps1` and `.\.venv\bin\python.exe` instead of the `Scripts` paths above.

The frontend development server starts a UI workspace only. Desktop startup and the Python bridge will be added during Harness development. See [development notes](docs/development.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `frontend/` | Vue application workspace |
| `src/slothy/presentation/` | Desktop presentation boundary |
| `src/slothy/application/` | Application API, services, and DTOs |
| `src/slothy/core/` | Framework independent Harness contracts and logic |
| `src/slothy/infrastructure/` | External system adapters |
| `tests/` | Unit, integration, and end-to-end tests |
| `docs/` | Architecture, development, decisions, and brand constraints |
| `scripts/` | Development and build helpers |
| `logos/` | Existing Slothy brand assets |

## License

MIT. See [LICENSE](LICENSE).
