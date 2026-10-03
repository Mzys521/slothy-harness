# Architecture

Slothy uses four Python areas with one-way boundaries:

```text
Vue UI → frontend bridge → Presentation → Application → Core
                                              ↑
                                Infrastructure implements Core interfaces
```

- **Presentation:** pywebview window lifecycle, frontend loading, and event forwarding.
- **Application:** operations offered to the UI, use-case coordination, and DTOs.
- **Core:** pure Python agent, model, context, tool, runtime, policy, and event abstractions.
- **Infrastructure:** concrete LLM, persistence, filesystem, shell, config, logging, and operating-system adapters.

Core must not import Presentation, Application, pywebview, Vue, Tailwind, database implementations, operating-system APIs, or concrete LLM SDKs. Vue communicates through a dedicated bridge service and receives DTOs rather than Core objects.

This is the initial boundary plan. The core agent loop and basic runtime state are implemented in `core/runtime`; model contracts remain in `core/model`, and tool contracts remain in `core/tools`. Desktop integration remains planned. See [Project Initialization Guide](Project-Initialization-Guide.md) for the full rationale.
