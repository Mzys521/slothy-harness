"""事件契约的基础类型与错误映射。

核心层只定义事件与接收端的抽象；事件的具体消费方（界面、日志、持久化）位于
外层，通过 ``EventSink`` 注入，核心层不得导入它们。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from slothy.core.runtime.state import RunStateError


@dataclass
class EventDeliveryFailure:
    """记录一次被隔离的事件投递失败。"""

    event_type: str
    sequence: int
    error_type: str
    message: str


@dataclass
class RunEvent:
    """所有运行时事件的基类。

    每个事件都必须可安全地交给外层观察者，因此只携带标识、计数、状态和分类
    信息，不携带密钥、未经筛选的工具参数、工具结果原文或内部异常堆栈。

    ``run_id`` 与 ``sequence`` 由事件的发射方补充：``Run`` 的状态迁移和运行器
    都会在分发前写入，构造事件时无需传入。
    """

    #: 稳定的分类标识，供日志、界面和测试按字符串匹配。
    EVENT_TYPE: ClassVar[str] = "run.event"

    run_id: str = ""
    sequence: int = 0
    step_number: int | None = None
    occurred_at: float = field(default_factory=monotonic)

    @property
    def event_type(self) -> str:
        """返回事件的稳定分类标识。"""
        return self.EVENT_TYPE

    def as_record(self) -> dict[str, Any]:
        """转换为可直接序列化的字典，供日志和界面层使用。"""
        record = {"event_type": self.event_type}
        record.update(vars(self))
        return record


@runtime_checkable
class EventSink(Protocol):
    """接收运行时事件的最小契约。

    核心层只依赖本协议。实现可以分发到订阅者、写入日志或转发到界面，
    但这些实现位于外层。
    """

    def notify(self, event: RunEvent) -> None:
        """接收一个事件；实现不应改变运行时结果。"""
        ...


@dataclass(frozen=True)
class ErrorInfo:
    """对一次失败的安全描述。

    ``error_type`` 只保留异常类名，``error_code`` 是核心层定义的稳定分类。
    原始异常文本可能包含提供方请求细节或本地路径，因此不进入事件。
    """

    error_code: str
    error_type: str | None = None


class RunCheckedError(RuntimeError):
    """核心层为受控外部调用定义的错误分类。

    模型提供方和工具执行器抛出本类的子类，运行时就能给出准确的事件与错误分类；
    子类自带的 ``error_code`` 会被 ``describe_error`` 直接采用。
    """

    #: 事件的 ``ErrorInfo.error_code``；由子类覆盖。
    error_code = "runtime_error"


def describe_error(error: BaseException | None) -> ErrorInfo | None:
    """把原始异常映射为稳定的错误分类，不复制异常文本。"""
    if error is None:
        return None

    from slothy.core.runtime.state import RunStateError
    from slothy.core.context.contracts import ContextError

    if isinstance(error, (RunCheckedError, RunStateError, ContextError)):
        return ErrorInfo(error_code=error.error_code)
    if isinstance(error, TimeoutError):
        # 非核心层定义的超时说明调用方没有使用统一分类，单独标记以便排查。
        return ErrorInfo(error_code="unexpected_timeout")
    return ErrorInfo(error_code="runtime_error", error_type=type(error).__name__)
