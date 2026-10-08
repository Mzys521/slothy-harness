# Slothy frontend

Vue 3 + TypeScript + Vite + Tailwind CSS. The UI follows the layout and interaction
patterns of DeepSeek Harness while preserving Slothy's desktop API and brand
specification. Source references and licensing are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

```powershell
npm --prefix frontend run dev
npm --prefix frontend run build
.\.venv\Scripts\python.exe -X utf8 -m slothy.desktop --browser
```

Start the backend for live interaction. Development requests go through the Vite
`/api` proxy to `127.0.0.1:8765`. The production desktop and browser share the same
Application operations; missing service/model configuration is shown explicitly.

```text
src/
  components/   reusable presentation components, layout, composer, inspection
  views/        workspace page composition
  stores/       frontend state, async requests, UI appearance preference
  services/     one typed bridge boundary and event-to-display projections
  types/        explicit Application DTO contracts
  styles/       brand → semantic tokens → component styling
```

The workspace defaults to light appearance, with dark and system options in
Settings. `Ctrl K` / `Cmd K` starts a task draft; `Ctrl P` / `Cmd P` searches task
records. Enter sends, Shift Enter inserts a line, and IME composition never sends.

The top sidebar switches between slothy chat and sloty coding. Coding projects
contain collapsible task lists and a details popover; Chat hides the project
environment. Create or edit a project to attach its source folder using the native
folder picker or the browser path form. Settings configure execution budgets, edit
permissions and fixed check presets, persisted by Application. File writes and project checks each require
approval followed by an explicit resume. Existing tasks keep their original
workspace and permissions when projects or settings change. Mode drafts are
separate, and switching modes does not cancel background execution.

Run details show actual events, retries, structured task state and context budgets.
Approval and resume are separate actions. Follow-up input creates another Run;
it does not pretend to be persisted cross-Run conversation history. Schedule and
plugin installation services remain unavailable. Model output is escaped text.

The previous frontend was backed up locally before its source and build output
were removed. Backups, reference downloads, test databases and screenshots are
inside ignored `.slothy/`; none are part of the frontend distribution.

See [desktop-ui.md](../docs/desktop-ui.md) for the runtime contract, testing commands
and existing cooperative cancellation and persistence limits.


Settings supports DeepSeek, Qwen, MiMo and GLM with preset endpoints/models and API Key input. The composer model menu switches configured text models; each task keeps its original provider/region/model. Credentials are encrypted with Windows DPAPI, never returned in configuration DTOs or written to browser storage. See [model-providers.md](../docs/model-providers.md) for supported standard API endpoints, regional keys, model IDs and offline SDK/UI verification.
