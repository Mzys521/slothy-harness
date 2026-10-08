"""有容量上限的同步调用隔离。超时后忽略晚到结果，不重试。"""

from queue import Queue, Empty
from threading import BoundedSemaphore, Thread


class BoundedInvoker:
    def __init__(self, capacity=4):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity 必须为正整数")
        self._slots = BoundedSemaphore(capacity)

    def invoke(self, operation, timeout_seconds):
        if not self._slots.acquire(blocking=False):
            raise TimeoutError("检索调用隔离容量已用尽")
        result = Queue(maxsize=1)

        def run():
            try:
                result.put((True, operation()))
            except BaseException as error:
                result.put((False, error))
            finally:
                self._slots.release()

        try:
            Thread(target=run, daemon=True).start()
        except BaseException:
            self._slots.release()
            raise
        try:
            succeeded, value = result.get(timeout=timeout_seconds)
        except Empty:
            raise TimeoutError("检索或摘要调用超时") from None
        if not succeeded:
            raise value
        return value


class TimedSummarizer:
    def __init__(self, summarizer, timeout_seconds, invoker):
        self.summarizer, self.timeout_seconds, self.invoker = summarizer, timeout_seconds, invoker

    def __call__(self, messages, output_token_budget):
        return self.invoker.invoke(lambda: self.summarizer(messages, output_token_budget), self.timeout_seconds)
