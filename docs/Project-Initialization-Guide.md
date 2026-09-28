# Slothy Project Initialization Guide

> **Purpose:** Quickly initialize the Slothy project repository and directory structure.  
> **Scope:** Project skeleton, Python environment, Vue 3 frontend workspace, Git repository, branch strategy, ignore rules, documentation directories, and development conventions.  
> **Note:** This document does **not** contain Harness implementation code, UI implementation code, or business logic.

---

## 1. Technology Baseline

The initial technology stack is fixed as:

- **Desktop Host:** pywebview
- **Frontend:** Vue 3
- **UI Styling:** Tailwind CSS
- **Harness Core:** Pure Python
- **Architecture:** Presentation / Application / Core + Infrastructure
- **Version Control:** Git
- **Repository Style:** Monorepo

High-level dependency direction:

```text
Presentation
    ↓
Application
    ↓
Core

Infrastructure
    ↓
Core Interfaces
```

The Core layer must remain independent from pywebview, Vue, Tailwind, operating-system APIs, databases, and third-party LLM SDK implementations.

---

# 2. Prerequisites

Before initialization, confirm the following tools are installed:

- Git
- Python 3.11 or newer
- Node.js LTS
- npm
- A code editor or IDE
- PowerShell

Recommended verification commands:

```powershell
git --version
python --version
node --version
npm --version
```

---

# 3. Create the Project Root

Recommended project name:

```text
slothy
```

Create the root directory and enter it:

```powershell
mkdir slothy
cd slothy
```

The repository root should contain both the Python runtime and Vue frontend.

---

# 4. Initialize Git

Initialize the repository immediately after creating the root directory:

```powershell
git init
```

Set the default branch to:

```powershell
git branch -M main
```

Verify repository status:

```powershell
git status
```

Recommended primary branches:

```text
main
dev
```

Create the development branch after the first baseline commit:

```powershell
git switch -c dev
```

Recommended branch naming convention:

```text
feature/<name>
fix/<name>
refactor/<name>
docs/<name>
chore/<name>
release/<version>
```

Examples:

```text
feature/tool-runtime
feature/desktop-shell
fix/webview-bridge
docs/architecture
chore/project-init
```

Do not use long-lived feature branches unless necessary.

---

# 5. Root Directory Structure

The initial repository structure should be:

```text
slothy/
│
├── frontend/
│
├── src/
│   └── slothy/
│       ├── presentation/
│       ├── application/
│       ├── core/
│       └── infrastructure/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docs/
│
├── scripts/
│
├── .gitignore
├── .env.example
├── README.md
├── LICENSE
└── pyproject.toml
```

---

# 6. Create the Python Directory Skeleton

Create the Python source root:

```powershell
mkdir src
mkdir src\slothy
```

Create the four major architectural areas:

```powershell
mkdir src\slothy\presentation
mkdir src\slothy\application
mkdir src\slothy\core
mkdir src\slothy\infrastructure
```

---

# 7. Presentation Layer Structure

Create the Python desktop presentation layer:

```powershell
mkdir src\slothy\presentation\desktop
```

Target structure:

```text
presentation/
└── desktop/
```

Responsibilities:

- pywebview window lifecycle
- Desktop window configuration
- Frontend resource loading
- Presentation-layer event forwarding
- Calls into the Application layer

The Presentation layer must not directly execute Harness Core logic.

---

# 8. Application Layer Structure

Create:

```powershell
mkdir src\slothy\application\api
mkdir src\slothy\application\services
mkdir src\slothy\application\dto
```

Target structure:

```text
application/
├── api/
├── services/
└── dto/
```

Responsibilities:

### `api/`

Defines the operations exposed to the Presentation layer.

Examples of future operation categories:

- Agent execution
- Runtime control
- Tool approval
- Settings
- Session management

### `services/`

Coordinates application use cases.

### `dto/`

Defines data exchanged between Application and Presentation.

The UI must not directly consume Core internal objects.

---

# 9. Core Layer Structure

Create:

```powershell
mkdir src\slothy\core\agent
mkdir src\slothy\core\model
mkdir src\slothy\core\context
mkdir src\slothy\core\tools
mkdir src\slothy\core\runtime
mkdir src\slothy\core\policy
mkdir src\slothy\core\events
```

Target structure:

```text
core/
├── agent/
├── model/
├── context/
├── tools/
├── runtime/
├── policy/
└── events/
```

Responsibilities:

### `agent/`

Agent execution lifecycle and control flow.

### `model/`

Model abstraction and model request/response contracts.

### `context/`

Conversation context and message management.

### `tools/`

Tool definitions, registry, invocation model, and execution contracts.

### `runtime/`

Run, Step, execution state, cancellation, and future checkpoint concepts.

### `policy/`

Permission and policy decisions.

### `events/`

Runtime event definitions and event dispatching abstractions.

The Core layer must remain pure Python and must not depend on:

- pywebview
- Vue
- Tailwind
- SQLite implementation
- Windows APIs
- HTTP frameworks
- concrete LLM SDKs

---

# 10. Infrastructure Layer Structure

Create:

```powershell
mkdir src\slothy\infrastructure\llm
mkdir src\slothy\infrastructure\persistence
mkdir src\slothy\infrastructure\filesystem
mkdir src\slothy\infrastructure\shell
mkdir src\slothy\infrastructure\config
mkdir src\slothy\infrastructure\logging
```

Target structure:

```text
infrastructure/
├── llm/
├── persistence/
├── filesystem/
├── shell/
├── config/
└── logging/
```

Responsibilities:

- Concrete LLM provider implementations
- Database implementations
- File-system access
- Shell execution
- Configuration loading
- Logging adapters
- Operating-system integration

Infrastructure may implement interfaces defined by Core.

Core must not depend on concrete Infrastructure implementations.

---

# 11. Test Directory Structure

Create:

```powershell
mkdir tests
mkdir tests\unit
mkdir tests\integration
mkdir tests\e2e
```

Target structure:

```text
tests/
├── unit/
├── integration/
└── e2e/
```

Recommended responsibility:

### `unit/`

Pure Core and Application unit tests.

### `integration/`

Integration between components such as:

- Application + Core
- Core + Infrastructure adapters
- Persistence
- Tool execution

### `e2e/`

End-to-end desktop workflows.

---

# 12. Documentation Structure

Create:

```powershell
mkdir docs
```

Recommended initial documentation files:

```text
docs/
├── architecture.md
├── development.md
├── Theme-Color-Constraints.md
└── decisions/
```

Create the architecture decision directory:

```powershell
mkdir docs\decisions
```

Use `docs/decisions/` for important architecture decisions.

Recommended naming format:

```text
0001-project-architecture.md
0002-pywebview-vue-bridge.md
0003-tool-runtime-boundary.md
```

The purpose is to preserve *why* architectural decisions were made.

---

# 13. Scripts Directory

Create:

```powershell
mkdir scripts
```

Target use:

```text
scripts/
├── development helpers
├── build helpers
├── packaging helpers
└── release helpers
```

Do not place business logic in this directory.

---

# 14. Initialize the Vue 3 Frontend

The frontend must live in:

```text
frontend/
```

Initialize the Vue workspace from the repository root.

Recommended configuration:

- Vue 3
- TypeScript
- Vite
- Router: optional initially
- Pinia: recommended when global state is required
- ESLint: recommended
- Prettier: recommended

After Vue initialization, the frontend should evolve toward:

```text
frontend/
├── public/
├── src/
│   ├── assets/
│   ├── components/
│   ├── views/
│   ├── stores/
│   ├── services/
│   ├── types/
│   └── styles/
├── package.json
├── vite.config.ts
└── tsconfig.json
```

---

# 15. Frontend Directory Initialization

Create the planned frontend application directories if they are not generated automatically:

```powershell
mkdir frontend\src\assets
mkdir frontend\src\components
mkdir frontend\src\views
mkdir frontend\src\stores
mkdir frontend\src\services
mkdir frontend\src\types
mkdir frontend\src\styles
```

Responsibilities:

```text
assets/       Logo, icon, image, static design assets
components/   Reusable UI components
views/        Page-level views
stores/       Frontend state
services/     pywebview bridge access
types/        TypeScript contracts
styles/       Theme tokens and global styles
```

The frontend should access Python through a dedicated bridge service rather than calling `window.pywebview` throughout the component tree.

---

# 16. Theme Specification Location

The Slothy color specification should be stored at:

```text
docs/Theme-Color-Constraints.md
```

The core brand colors are fixed:

```text
Slothy Green   #60DD06
Slothy Cream   #FCEAC9
Slothy Brown   #95611F
```

Frontend theme tokens must derive from the specification rather than defining independent project colors.

---

# 17. Python Environment

Create a dedicated virtual environment for the project.

Recommended location:

```text
.venv/
```

Example:

```powershell
python -m venv .venv
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

The virtual environment must not be committed to Git.

---

# 18. Python Project Metadata

The root should contain:

```text
pyproject.toml
```

This file will later manage:

- Project metadata
- Python version
- Runtime dependencies
- Development dependencies
- Formatting tools
- Linting tools
- Type-checking configuration
- Testing configuration
- Packaging configuration

Do not distribute Python configuration across multiple files unless there is a clear reason.

---

# 19. Environment Variables

Create:

```text
.env.example
```

The real local environment file should later be:

```text
.env
```

Rules:

```text
.env.example    MUST be committed
.env            MUST NOT be committed
```

`.env.example` should contain variable names only and must never contain production secrets.

Potential future categories:

```text
LLM provider
API key
Model name
Application environment
Database location
Logging level
Development flags
```

---

# 20. Git Ignore Rules

The repository `.gitignore` should cover at least the following categories.

## Python

```text
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
```

## Environment

```text
.env
.env.local
.env.*.local
```

Do not ignore:

```text
.env.example
```

## Node / Vue

```text
frontend/node_modules/
frontend/dist/
frontend/.vite/
```

## IDE

```text
.vscode/
.idea/
```

If shared VS Code project configuration is intentionally maintained, whitelist only the required files instead of committing the whole editor state.

## OS

```text
.DS_Store
Thumbs.db
desktop.ini
```

## Runtime Data

Future runtime data should normally not enter version control:

```text
data/
logs/
tmp/
cache/
```

If a directory itself must exist in the repository, keep it using a placeholder such as `.gitkeep`.

---

# 21. Recommended Git Attributes

Consider adding:

```text
.gitattributes
```

Recommended goals:

- Normalize line endings
- Keep text files consistent across Windows/Linux
- Define binary asset handling

Because Slothy development currently targets Windows but may later support additional platforms, consistent Git line endings are important.

---

# 22. Initial Repository Files

Before the first commit, the root should contain at least:

```text
README.md
LICENSE
.gitignore
.env.example
pyproject.toml
docs/
frontend/
src/
tests/
scripts/
```

The project does not need Harness implementation code before the first repository baseline is committed.

---

# 23. README Initial Scope

The first README only needs to establish:

- Project name
- One-sentence project purpose
- Current development status
- Technology stack
- High-level architecture
- Local development prerequisites
- License
- Basic repository structure

Avoid documenting unfinished functionality as if it already exists.

---

# 24. License

Choose the project license before public release.

If Slothy is intended to remain permissive and open-source, common options include:

```text
MIT
Apache-2.0
```

Do not publish the repository publicly without intentionally choosing a license.

---

# 25. First Git Commit

Before the first commit, verify:

```powershell
git status
```

Then stage the initialized project skeleton:

```powershell
git add .
```

Create the baseline commit:

```powershell
git commit -m "chore: initialize Slothy project structure"
```

Recommended commit convention:

```text
feat:      New user-facing capability
fix:       Bug fix
refactor:  Internal structural change
docs:      Documentation
test:      Tests
chore:     Tooling / repository maintenance
build:     Build system
ci:        CI/CD
style:     Formatting-only changes
```

---

# 26. Development Branch

After the initial `main` baseline commit:

```powershell
git switch -c dev
```

Recommended flow:

```text
feature/*
    ↓
dev
    ↓
main
```

`main` should represent a stable project state.

`dev` may contain ongoing integration work.

Small projects may later simplify this flow if maintaining `dev` provides little value.

---

# 27. Optional Remote Repository Initialization

After creating a remote repository, connect it using:

```powershell
git remote add origin <repository-url>
```

Verify:

```powershell
git remote -v
```

Push `main`:

```powershell
git push -u origin main
```

Push `dev`:

```powershell
git push -u origin dev
```

Do not commit API keys, `.env`, local databases, runtime logs, or development secrets before pushing.

---

# 28. Recommended Initialization Order

Use this order when starting from an empty directory:

```text
1. Create project root
2. Initialize Git
3. Create README / LICENSE / .gitignore / .env.example
4. Create Python src layout
5. Create architectural layer directories
6. Create test directories
7. Create docs directory
8. Add Theme-Color-Constraints.md
9. Create scripts directory
10. Create Python virtual environment
11. Initialize Vue 3 frontend
12. Add Tailwind to frontend
13. Verify frontend directory layout
14. Create pyproject.toml
15. Verify Git ignored files
16. Create first baseline commit
17. Create dev branch
18. Connect remote repository when ready
```

---

# 29. Expected Initial Directory Tree

After initialization, the repository should approximately look like this:

```text
slothy/
│
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── assets/
│   │   ├── components/
│   │   ├── views/
│   │   ├── stores/
│   │   ├── services/
│   │   ├── types/
│   │   └── styles/
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── src/
│   └── slothy/
│       ├── presentation/
│       │   └── desktop/
│       │
│       ├── application/
│       │   ├── api/
│       │   ├── services/
│       │   └── dto/
│       │
│       ├── core/
│       │   ├── agent/
│       │   ├── model/
│       │   ├── context/
│       │   ├── tools/
│       │   ├── runtime/
│       │   ├── policy/
│       │   └── events/
│       │
│       └── infrastructure/
│           ├── llm/
│           ├── persistence/
│           ├── filesystem/
│           ├── shell/
│           ├── config/
│           └── logging/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docs/
│   ├── Theme-Color-Constraints.md
│   └── decisions/
│
├── scripts/
│
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
└── pyproject.toml
```

---

# 30. Architecture Constraints From Day One

The following constraints apply immediately, even before implementation starts:

```text
Presentation may depend on Application.
Application may depend on Core.
Infrastructure may implement Core abstractions.
Core must not depend on Presentation.
Core must not depend on Application.
Core must not depend on pywebview.
Core must not depend on Vue.
Core must not depend on concrete LLM SDKs.
Core must not depend on concrete database implementations.
Vue must not directly depend on Core internals.
```

The intended dependency chain is:

```text
Vue
 ↓
Frontend Bridge
 ↓
pywebview Presentation
 ↓
Application API
 ↓
Application Service
 ↓
Core
```

External systems enter through Infrastructure:

```text
LLM
Database
Filesystem
Shell
OS
 ↓
Infrastructure
 ↓
Core Abstractions
```

---

# 31. Initialization Completion Checklist

Before starting Harness implementation, verify:

```text
□ Git repository initialized
□ main branch exists
□ Initial baseline commit created
□ dev branch created if using the proposed branching model
□ .gitignore exists
□ .env is ignored
□ .env.example is tracked
□ Python virtual environment exists locally
□ frontend workspace exists
□ Vue 3 initialized
□ Tailwind prepared
□ src/slothy exists
□ Presentation layer exists
□ Application layer exists
□ Core layer exists
□ Infrastructure layer exists
□ tests directories exist
□ docs directory exists
□ Theme-Color-Constraints.md is stored in docs
□ scripts directory exists
□ No business logic has been added prematurely
□ Core has no framework dependency
```

Once all items above are complete, the repository is ready to enter the first Harness development phase.

---

# 32. Baseline Rule

The initialization phase has one objective:

> **Establish boundaries before adding functionality.**

Do not optimize for the number of files or features.

The initial repository should make the following architectural intent immediately visible:

```text
Presentation = How the product is presented
Application  = What the application asks to do
Core         = How the Harness works
Infrastructure = How the system interacts with the outside world
```

This structure is the baseline for future Slothy series development.
