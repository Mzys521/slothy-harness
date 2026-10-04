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

The core agent loop and runtime state are implemented in `core/runtime`; model contracts remain in `core/model`, and tool contracts remain in `core/tools`. Application now provides `RuntimeAPI → RuntimeService → Core` with JSON DTOs, independent create/execute/approval/resume operations, ownership checks and event forwarding. Concrete dependencies are injected by a composition root. Desktop integration remains planned. See [Application API](application-api.md) and [Project Initialization Guide](Project-Initialization-Guide.md).

`AgentRunner` exposes fixed run/resume entry points; `RunExecution` owns the loop, lifecycle coordination and recoverable cursor. Runtime limits, failure decisions, retries and progress checks enter through `PolicySession`; `Run` translates policy termination decisions into state and lifecycle events. Domain operations enter through `context.conversation.add`, `ModelSession.model_call`, and `ToolSession.tool_call`. Message construction, model streaming/usage and tool progress/events belong to those modules. Tool permission decisions use `policy.evaluation.check_tool_call`. Modules share the Run's relay through `EventEmitter`, and runtime observation records duration metrics. See [ADR 0007](decisions/0007-runner-module-entrypoints.md) and [ADR 0009](decisions/0009-policy-and-resilience.md).

`Policy` configurations compose `DefaultPolicy`, `TimeoutPolicy`, `RetryPolicy` and `SafetyPolicy` without editing Runner. Timeout enforcement remains cooperative; Infrastructure must implement isolation to forcibly interrupt arbitrary synchronous calls. See [Policy System](policy-system.md) for actual guarantees and compatibility details.

Context reads use the `Context.get_windowed_messages()` protocol. The default `InMemoryContext` separates complete history from the request window and enforces an 8192 budget under the configured token estimator. `TrimOldestStrategy` and injected `SummaryStrategy` can be exchanged without editing the Runner. See [Context System](context-system.md) and [ADR 0008](decisions/0008-context-system.md).

Runtime snapshots serialize domain data and the cursor, not providers or callbacks. Context, Model, Policy and Tool modules own their snapshot sections. `SnapshotStore` belongs to Core; SQLite implementations live in Infrastructure. `ToolJournal` persists intent before execution and results before cursor advancement. Trusted replay declarations gate retries independently from Policy: keyed calls verify receipts, and unverifiable attempts suspend for a host-authenticated human decision. Approval requests are persisted; consumable grants are not. Recovery keeps elapsed budgets and uses a new Run generation. See [Runtime recovery](runtime-recovery.md) and [ADR 0010](decisions/0010-runtime-snapshot-and-replay-safety.md) for transaction, approval and external-effect limits.
