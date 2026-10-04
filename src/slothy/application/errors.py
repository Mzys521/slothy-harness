"""应用边界的稳定错误；响应不包含底层异常文本。"""

from slothy.application.dto.runtime import ErrorDTO


class ApplicationError(Exception):
    def __init__(self, code: str, message: str, *, run_id: str | None = None):
        super().__init__(message)
        self.dto = ErrorDTO(code, message, run_id)


_EXECUTION_ERRORS = {
    "run_cancelled": "执行已取消。",
    "run_timeout": "执行超过总时限。",
    "step_timeout": "当前步骤超过时限。",
    "step_limit_reached": "执行达到步骤上限。",
    "no_progress": "策略检测到执行没有进展。",
    "llm_timeout": "模型请求超时。",
    "model_transient_error": "模型暂时不可用，重试额度已耗尽。",
    "model_error": "模型请求失败。",
    "tool_timeout": "工具执行超时。",
    "tool_error": "工具执行失败。",
    "idempotency_conflict": "工具幂等记录与本次请求不一致。",
    "tool_execution_unknown": "工具执行结果无法确认。",
    "context_error": "上下文无法构建。",
    "context_budget_exceeded": "上下文无法满足令牌预算。",
    "snapshot_error": "快照读取、校验或保存失败。",
    "snapshot_conflict": "快照版本冲突，请重新查询执行状态。",
}


def execution_error(error: Exception, run_id: str) -> ApplicationError:
    code = getattr(error, "error_code", "execution_failed")
    if code not in _EXECUTION_ERRORS:
        code = "execution_failed"
    return ApplicationError(
        code, _EXECUTION_ERRORS.get(code, "执行失败，请查询执行状态。"), run_id=run_id,
    )
