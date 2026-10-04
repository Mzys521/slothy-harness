# ADR 0010: Runtime snapshots and safe tool replay

Status: accepted.

## Context

An in-memory loop loses its cursor on interruption. Retrying a non-idempotent tool
after a lost response can repeat an effect that already occurred. A message list
alone cannot distinguish pending calls, saved results and unknown execution.

## Decision

Keep AgentRunner as a fixed facade. RunExecution owns the recoverable orchestration
cursor; Context, ModelSession, PolicySession and ToolJournal own their snapshot
sections. RuntimeSnapshot uses versioned finite JSON and strict identity checks,
never executable objects. SnapshotStore compares revisions atomically. Core ships
an in-memory implementation; Infrastructure supplies SQLite persistence.

Persist an execution intent before invoking a tool. Save its result before committing
the message and advancing the batch. Recovery reuses known results and completed
prefixes. Preserve recorded elapsed budgets, attempts, progress and event counters.
Exclude offline/approval waiting from execution budgets. Resume creates a new Run
generation; it does not mutate the original object's terminal history. Cancellation
and exhausted runtime limits remain terminal.

Trusted registrations declare IDEMPOTENT, KEYED, UNVERIFIABLE or legacy UNSPECIFIED.
Policy chooses whether to retry; ToolJournal independently gates every attempt.
Generate a stable key from Run, step, call and canonical request fingerprint.
Keyed verification must report not started, completed with a result, or unknown.
Reuse completed receipts; unknown/missing verification requires approval. A key
bound to different arguments is always a conflict. Incomplete calls must retain
their implementation version and declaration across recovery.

UNVERIFIABLE calls wait before every attempt. Undeclared tools retain first-call
compatibility, but unknown replay waits. WAITING_APPROVAL is a persisted pause,
returned to the host with concrete arguments and an approval request. The trusted
host authenticates the actual human decision. Approval binds one request and one
attempt; grants are never serialized. Denial returns a controlled error without
execution. Old snapshots/decisions cannot override newer shared-store revisions.

SQLiteIdempotencyLedger atomically reserves keys and stores completed receipts;
reservation tokens prevent a stale worker from overwriting a later attempt.
Business effects between reservation and receipt remain unknown after a crash.
Explicit consent may permit an attempt that duplicates such an effect.

## Consequences and limits

Snapshots contain raw context, arguments and results; hosts must protect their
storage. Events expose only safe identifiers, counts and classifications for
recovery/approval. Existing policy ASK rules remain controlled blocks. This adds
the replay-specific approval contract, not desktop UI or general permission storage.

The default memory store cannot prove cross-process freshness. Durable storage and
the same trusted adapters/configurations are required for restart recovery. One
active driver per Run is expected; no distributed execution lease is introduced.
External effects require business-service idempotency or transactional integration
for stronger guarantees. Keys cover a logical tool call, not semantically similar
new model requests. There is no arbitrary external exactly-once guarantee.

Interruption remains cooperative. Unknown model calls may be issued again, and
unreported usage or time after the last checkpoint cannot be reconstructed.
Events do not have a transactional outbox; crash recovery may repeat or omit
delivery. No executable serialization, async scheduler or process isolation is added.

Verification uses fake providers/executors and temporary SQLite databases, including
the two critical crash windows: an effect without a receipt, and a receipt without
the Runtime result commit. See [Runtime recovery](../runtime-recovery.md).
