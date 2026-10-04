"""工具执行日志：写前意图、结果缓存、幂等校验与一次性审批。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from typing import Callable

from slothy.core.events import ToolApprovalRequested, ToolApprovalResolved
from slothy.core.events.emitter import EventEmitter
from slothy.core.model.model_models import ToolCall

from .replay import (
    ApprovalDecision, ApprovalRequest, IdempotencyCheck, ReplaySafety,
    VerificationStatus, idempotency_key, request_fingerprint,
    IdempotencyConflictError,
)
from .tool_models import ToolContext, ToolResult


class ToolJournal:
    def __init__(
        self, run_id: str, events: EventEmitter, save: Callable[[], None],
        wait: Callable[[ApprovalRequest], None],
    ):
        self.run_id, self.events, self.save, self.wait = run_id, events, save, wait
        self.records: dict[str, dict] = {}
        self._grants: dict[str, str] = {}
        self._started: dict[str, tuple[float, float]] = {}

    def prepare(self, call, step, definition, *, legacy_safe=False) -> str:
        from slothy.core.runtime.snapshot import SnapshotConflictError

        version = getattr(definition, "execution_version", "1")
        safety = getattr(definition, "replay_safety", ReplaySafety.UNSPECIFIED)
        if safety is ReplaySafety.UNSPECIFIED and legacy_safe:
            safety = ReplaySafety.IDEMPOTENT
        fingerprint = request_fingerprint(call, version)
        identity = f"{step}:{call.call_id}"
        expected = {
            "step": step, "call_id": call.call_id, "name": call.name,
            "version": version, "safety": safety.value, "fingerprint": fingerprint,
            "key": idempotency_key(self.run_id, step, call.call_id, fingerprint),
            "arguments": deepcopy(call.arguments),
        }
        previous = self.records.get(identity)
        if previous is not None:
            if any(previous[key] != value for key, value in expected.items()):
                raise SnapshotConflictError("tool identity or safety has changed")
        else:
            self.records[identity] = {
                **expected, "attempts": 0, "status": "ready", "result": None,
                "elapsed_seconds": 0.0, "approval_sequence": 0,
                "pending": None, "approvals": [], "end_emitted": False,
            }
        return identity

    def cached(self, identity: str) -> ToolResult | None:
        record = self.records[identity]
        if record["status"] == "completed":
            return ToolResult(**deepcopy(record["result"]))
        return None

    def completed_identity(self, call: ToolCall, step: int) -> str | None:
        """已完成调用只核对原请求，不要求当前工具仍使用旧实现。"""
        from slothy.core.runtime.snapshot import SnapshotConflictError

        identity = f"{step}:{call.call_id}"
        record = self.records.get(identity)
        if record is None or record["status"] != "completed":
            return None
        if (
            record["name"] != call.name
            or record["fingerprint"] != request_fingerprint(call, record["version"])
        ):
            raise SnapshotConflictError("completed tool request has changed")
        return identity

    def authorize(self, identity, call, context, executor):
        record = self.records[identity]
        safety = ReplaySafety(record["safety"])
        bound = (
            replace(context, idempotency_key=record["key"],
                    request_fingerprint=record["fingerprint"], approval_id="")
            if safety is ReplaySafety.KEYED else context
        )
        reason = None
        if safety is ReplaySafety.KEYED:
            verify = getattr(executor, "verify_idempotency", None)
            try:
                check = verify(deepcopy(call), bound) if callable(verify) else None
            except IdempotencyConflictError:
                raise
            except Exception:
                check = None
            if not isinstance(check, IdempotencyCheck):
                reason = "verification_unavailable"
            elif check.status is VerificationStatus.COMPLETED:
                self.completed(identity, check.result)
                return bound, check.result
            elif check.status is VerificationStatus.UNKNOWN:
                reason = "execution_unknown"
        elif safety is ReplaySafety.UNVERIFIABLE:
            reason = "unverifiable"
        elif safety is ReplaySafety.UNSPECIFIED and record["attempts"]:
            reason = "undeclared_replay"
        grant = self._grants.pop(identity, "")
        if reason is not None and not grant:
            self.request_approval(identity, reason)
        return (
            replace(bound, approval_id=grant, idempotency_key=record["key"],
                    request_fingerprint=record["fingerprint"])
            if grant else bound
        ), None

    def request_approval(self, identity, reason):
        record = self.records[identity]
        if record["pending"] is None:
            record["approval_sequence"] += 1
            request_id = sha256(
                f'{record["key"]}:{record["approval_sequence"]}'.encode()
            ).hexdigest()
            record["pending"] = asdict(ApprovalRequest(
                request_id, self.run_id, record["step"], record["call_id"],
                record["name"], record["fingerprint"], record["attempts"] + 1,
                reason,
                arguments=record["arguments"],
            ))
        record["status"] = "awaiting_approval"
        self.save()
        request = ApprovalRequest(**record["pending"])
        self.events.emit(ToolApprovalRequested(
            request_id=request.request_id, call_id=request.call_id,
            name=request.tool_name, attempt=request.attempt, reason=request.reason,
        ))
        self.wait(request)
        raise AssertionError("approval wait must suspend execution")

    @property
    def pending_approval(self) -> ApprovalRequest | None:
        pending = [record["pending"] for record in self.records.values()
                   if record["pending"] is not None]
        if len(pending) > 1:
            from slothy.core.runtime.snapshot import SnapshotError

            raise SnapshotError("multiple pending approvals")
        return ApprovalRequest(**pending[0]) if pending else None

    def resolve(self, decision: ApprovalDecision):
        from slothy.core.runtime.snapshot import SnapshotConflictError

        request = self.pending_approval
        if request is None or request.request_id != decision.request_id:
            raise SnapshotConflictError("approval does not match pending request")
        identity = f"{request.step_number}:{request.call_id}"
        record = self.records[identity]
        if (
            request.fingerprint != record["fingerprint"]
            or request.attempt != record["attempts"] + 1
        ):
            raise SnapshotConflictError("approval binding has changed")
        record["pending"] = None
        record["approvals"].append({
            "request_id": request.request_id, "approved": decision.approved,
            "actor": decision.actor, "attempt": request.attempt,
        })
        record["status"] = "unknown" if record["attempts"] else "ready"
        if decision.approved:
            # 不序列化授权；重启后必须重新校验或重新请求同意。
            self._grants[identity] = request.request_id
        else:
            self.completed(identity, ToolResult(
                output={"error": "用户拒绝执行工具"}, is_error=True,
            ))
        self.save()
        self.events.emit(ToolApprovalResolved(
            request_id=request.request_id, call_id=request.call_id,
            name=request.tool_name, approved=decision.approved,
        ))

    def started(self, identity: str):
        record = self.records[identity]
        record["attempts"] += 1
        record["status"] = "executing"
        self._started[identity] = (self.events.clock(), record["elapsed_seconds"])
        self.save()  # 保存失败时禁止调用执行器。

    def _elapsed(self, identity):
        if identity in self._started:
            start, previous = self._started[identity]
            return previous + max(0, self.events.clock() - start)
        return self.records[identity]["elapsed_seconds"]

    def completed(self, identity, result):
        record = self.records[identity]
        record["elapsed_seconds"] = self._elapsed(identity)
        self._started.pop(identity, None)
        record["status"] = "completed"
        record["result"] = {
            "output": deepcopy(result.output), "is_error": result.is_error,
        }
        record["pending"] = None
        self.save()

    def failed(self, identity):
        record = self.records[identity]
        record["elapsed_seconds"] = self._elapsed(identity)
        self._started.pop(identity, None)
        record["status"] = "unknown"
        record["result"] = None
        self.save()

    def snapshot_state(self) -> dict:
        records = deepcopy(self.records)
        for identity, record in records.items():
            record["elapsed_seconds"] = self._elapsed(identity)
        return {"records": records}

    def restore_state(self, data: dict):
        from slothy.core.runtime.snapshot import SnapshotError, count, seconds

        if set(data) != {"records"} or not isinstance(data["records"], dict):
            raise SnapshotError("invalid tool journal")
        expected = {
            "step", "call_id", "name", "version", "safety", "fingerprint", "key",
            "attempts", "status", "result", "elapsed_seconds", "approval_sequence",
            "pending", "approvals", "end_emitted",
            "arguments",
        }
        records = deepcopy(data["records"])
        for identity, record in records.items():
            if not isinstance(record, dict) or set(record) != expected:
                raise SnapshotError("invalid tool record")
            step = count(record["step"], "tool step", 1)
            if identity != f'{step}:{record["call_id"]}':
                raise SnapshotError("invalid tool identity")
            if any(not isinstance(record[key], str) or not record[key] for key in (
                "call_id", "name", "version", "fingerprint", "key",
            )) or not isinstance(record["arguments"], dict):
                raise SnapshotError("invalid stored tool request")
            fingerprint = request_fingerprint(
                ToolCall(record["call_id"], record["name"], record["arguments"]),
                record["version"],
            )
            if record["fingerprint"] != fingerprint or record["key"] != idempotency_key(
                self.run_id, step, record["call_id"], fingerprint,
            ):
                raise SnapshotError("invalid idempotency binding")
            count(record["attempts"], "tool attempts")
            count(record["approval_sequence"], "approval sequence")
            seconds(record["elapsed_seconds"], "tool elapsed")
            if record["status"] not in {
                "ready", "executing", "unknown", "completed", "awaiting_approval",
            } or record["safety"] not in {value.value for value in ReplaySafety}:
                raise SnapshotError("invalid tool safety/status")
            if not isinstance(record["end_emitted"], bool):
                raise SnapshotError("invalid tool event marker")
            if record["status"] == "completed":
                if not isinstance(record["result"], dict) or set(record["result"]) != {
                    "output", "is_error",
                } or not isinstance(record["result"]["is_error"], bool):
                    raise SnapshotError("invalid stored tool result")
            elif record["result"] is not None:
                raise SnapshotError("unfinished tool has a result")
            if record["pending"] is not None:
                try:
                    request = ApprovalRequest(**record["pending"])
                except (TypeError, ValueError) as error:
                    raise SnapshotError("invalid pending approval") from error
                if (
                    request.run_id != self.run_id or request.step_number != step
                    or request.call_id != record["call_id"]
                    or request.tool_name != record["name"]
                    or request.fingerprint != record["fingerprint"]
                    or request.attempt != record["attempts"] + 1
                    or request.arguments != record["arguments"]
                    or request.request_id != sha256(
                        f'{record["key"]}:{record["approval_sequence"]}'.encode()
                    ).hexdigest()
                ):
                    raise SnapshotError("approval does not match tool")
            if not isinstance(record["approvals"], list):
                raise SnapshotError("invalid approval audit")
            if (record["pending"] is not None) != (
                record["status"] == "awaiting_approval"
            ) or (record["end_emitted"] and record["status"] != "completed"):
                raise SnapshotError("inconsistent tool checkpoint")
            audit_ids = []
            for audit in record["approvals"]:
                if not isinstance(audit, dict) or set(audit) != {
                    "request_id", "approved", "actor", "attempt",
                }:
                    raise SnapshotError("invalid approval audit fields")
                try:
                    ApprovalDecision(
                        audit["request_id"], audit["approved"], audit["actor"],
                    )
                except ValueError as error:
                    raise SnapshotError("invalid approval audit value") from error
                count(audit["attempt"], "approval attempt", 1)
                audit_ids.append(audit["request_id"])
            if len(set(audit_ids)) != len(audit_ids):
                raise SnapshotError("approval was consumed twice")
        self.records = records
        self.pending_approval  # 验证最多只有一个等待点。
