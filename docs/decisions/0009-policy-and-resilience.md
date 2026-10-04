# ADR 0009: Composable runtime Policy and resilience

Status: accepted for synchronous cooperative runtime.

## Context

Runner compared its step counter to `max_steps`; Run separately checked deadlines,
and model/tool exceptions always terminated execution. Changing these decisions
required changing orchestration or state code. Tool safety already had a rule
engine, which must remain compatible.

## Decision

Introduce `Policy` with limits, termination, failure, remaining-time and tool-verdict
decisions. `DefaultPolicy`, `TimeoutPolicy`, `RetryPolicy` and `SafetyPolicy` compose
by wrapping a base. Configurations are immutable; `PolicySession` owns per-run
execution. Runner uses the stable session entry point rather than comparing loop
indices. Run preserves state invariants and translates decisions into classified
errors and lifecycle events. Model/tool sessions perform attempts and own their
domain events. Legacy configuration and executor signatures remain compatible.

Retries are bounded and confined to a logical call. They never reset deadlines.
Tool retry requires an explicit idempotent allowlist. Structured error results are
not thrown failures. Delivered text prevents model retry. Cancellation and runtime
termination override recovery. SDK retries are disabled to prevent hidden attempts.
Safety compares consecutive identical exchanges through private digests, ignoring
call IDs and model wording, and can return safe tool failures to the model.

## Consequences and limits

The acceptance demonstration uses the same Runner implementation with five-round
and twenty-round/thirty-second configurations, plus retry and no-progress cases.
Tests use fake clocks/providers/executors and SDK responses, without network.

Deadlines remain cooperative. Remaining seconds reach model I/O and tool context;
declared tool deadlines are enforced at call boundaries. Arbitrary synchronous
operations cannot be forcibly interrupted by Core. A hard wall-clock guarantee
needs an Infrastructure isolation adapter with lifecycle and side-effect semantics.
Neither boundary checks nor abandoned background threads represent hard termination.

No process isolation, asynchronous loop, approval waiting, retry backoff, price
router, persistence or semantic progress classifier is introduced here.
See [Policy System](../policy-system.md) for runnable examples and error semantics.

Subsequent extension: [ADR 0010](0010-runtime-snapshot-and-replay-safety.md) adds
persisted recovery, trusted replay declarations and per-attempt human approval.
It extends the original tool allowlist while retaining cooperative timeout limits.
