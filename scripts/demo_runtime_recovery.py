"""无网络恢复演示；副作用仅为临时 SQLite 数据库中的一条演示记录。"""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from slothy.core.model import ModelProvider, ModelResult, ToolCall
from slothy.core.policy import RetryPolicy
from slothy.core.runtime import AgentRunner, RunStatus
from slothy.core.tools import (
    ApprovalDecision, ReplaySafety, ToolContext, ToolRegistry, ToolResult, tool,
)
from slothy.infrastructure.app_tools.idempotency import (
    KeyedToolExecutor, SQLiteIdempotencyLedger,
)
from slothy.infrastructure.persistence.runtime_store import SQLiteSnapshotStore


class SimulatedCrash(BaseException):
    """模拟进程丢失；不让普通异常处置把未知结果转换为受控错误。"""


@tool(replay_safety=ReplaySafety.KEYED, execution_version="1")
def create_demo_record(value: int) -> int:
    """创建本地演示记录。"""
    return value


class DemoModel(ModelProvider):
    def generate(self, messages, **kwargs):
        if messages[-1]["role"] == "tool":
            return ModelResult(text="工具结果已收到")
        return ModelResult(tool_calls=[
            ToolCall("create-1", "create_demo_record", {"value": 7}),
        ])


class DemoExecutor:
    def __init__(self, path, registry, *, crash=False):
        self.path, self.registry, self.crash = path, registry, crash
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS effects (value INTEGER)")

    def execute(self, call, context, on_progress=None):
        definition = self.registry.get_tool(call.name)
        if definition is None or call.name != "create_demo_record":
            return ToolResult(output={"error": "工具不允许"}, is_error=True)
        arguments = definition.args_model.model_validate(call.arguments)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO effects VALUES (?)", (arguments.value,))
        if self.crash:
            raise SimulatedCrash()
        return ToolResult(output=arguments.value)


def effects(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0]


def make_runner(path, *, crash=False, store=None):
    registry = ToolRegistry()
    registry.register(create_demo_record)
    executor = KeyedToolExecutor(
        DemoExecutor(path, registry, crash=crash), SQLiteIdempotencyLedger(path),
    )
    return AgentRunner(
        DemoModel(), registry, executor, policy=RetryPolicy(),
        snapshot_store=store or SQLiteSnapshotStore(path),
    )


def known_result(path):
    class CrashBeforeResultSnapshot(SQLiteSnapshotStore):
        def save(self, snapshot, *, expected_revision):
            records = snapshot.to_dict()["tools"]["records"].values()
            if any(record["status"] == "completed" for record in records):
                raise SimulatedCrash()
            return super().save(snapshot, expected_revision=expected_revision)

    context = ToolContext("known-result")
    try:
        make_runner(path, store=CrashBeforeResultSnapshot(path)).run(
            "创建演示记录", context=context,
        )
    except SimulatedCrash:
        pass
    snapshot = SQLiteSnapshotStore(path).load(context.run_id)
    result = make_runner(path).resume(snapshot, context=context)
    assert result.run.status is RunStatus.COMPLETED and effects(path) == 1
    print("known result: completed, effects=1 (receipt reused)")


def unknown_result(path, decision):
    context = ToolContext("unknown-result")
    try:
        make_runner(path, crash=True).run("创建演示记录", context=context)
    except SimulatedCrash:
        pass
    snapshot = SQLiteSnapshotStore(path).load(context.run_id)
    waiting = make_runner(path).resume(snapshot, context=context)
    assert waiting.run.status is RunStatus.WAITING_APPROVAL and effects(path) == 1
    print(f"unknown result: waiting_approval, effects=1, "
          f"attempt={waiting.approval.attempt}")
    if decision == "wait":
        return
    # 命令行明确选择的是临时示例的宿主决定；生产中必须来自真实用户输入。
    result = make_runner(path).resume(
        waiting.snapshot, context=context,
        approval=ApprovalDecision(
            waiting.approval.request_id, decision == "approve", "demo-user",
        ),
    )
    expected = 2 if decision == "approve" else 1
    assert result.run.status is RunStatus.COMPLETED and effects(path) == expected
    print(f"demo decision={decision}: completed, effects={expected}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", choices=("wait", "deny", "approve"),
                        default="wait", help="仅对临时示例模拟宿主审批；默认保持阻塞")
    options = parser.parse_args()
    with TemporaryDirectory() as directory:
        known_result(Path(directory) / "known.sqlite")
        unknown_result(Path(directory) / "unknown.sqlite", options.decision)
