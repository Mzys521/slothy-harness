"""运行时状态和协作式中断的测试。"""

import unittest
from inspect import isabstract
from unittest.mock import patch

from slothy.core.events import RunTimeline, StepEnd, StepOutcome, StepTimeout
from slothy.core.runtime import (
    Run,
    RunDeadlineExceededError,
    RunStatus,
    StepStatus,
    StepTimeoutError,
)
from slothy.core.tools import ToolExecutor


class FakeClock:
    """可推进的单调时钟，替代难以维护的调用序列模拟。"""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RunStateTests(unittest.TestCase):
    def test_tool_executor_is_abstract(self) -> None:
        self.assertTrue(isabstract(ToolExecutor))
        with self.assertRaises(TypeError):
            ToolExecutor()

    def test_deadline_marks_active_step_failed(self) -> None:
        runtime = Run(run_id="run-deadline", max_steps=2, deadline_seconds=1.0)
        clock = FakeClock(10.0)

        with patch("slothy.core.runtime.state.monotonic", clock):
            runtime.start()
            runtime.begin_step(1)
            clock.now = 12.0
            with self.assertRaises(RunDeadlineExceededError):
                runtime.check_active()

        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(runtime.steps[0].status, StepStatus.FAILED)

    def test_step_timeout_emits_step_timeout_before_run_failed(self) -> None:
        timeline = RunTimeline()
        runtime = Run(
            run_id="run-step-timeout",
            max_steps=2,
            step_timeout_seconds=1.0,
            events=timeline,
        )
        clock = FakeClock(20.0)

        with patch("slothy.core.runtime.state.monotonic", clock):
            runtime.start()
            runtime.begin_step(1)
            clock.now = 21.0
            with self.assertRaises(StepTimeoutError):
                runtime.check_active()

        self.assertIsNotNone(timeline.first(StepTimeout))
        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(runtime.steps[0].status, StepStatus.FAILED)
        self.assertEqual(
            timeline.types()[-3:],
            ["run.step.ended", "run.step.timeout", "run.failed"],
        )
        self.assertEqual(timeline.first(StepEnd).outcome, StepOutcome.FAILED)

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "run_id"):
            Run(run_id=" ", max_steps=1)
        with self.assertRaisesRegex(ValueError, "max_steps"):
            Run(run_id="run-1", max_steps=0)
        with self.assertRaisesRegex(ValueError, "deadline_seconds"):
            Run(run_id="run-1", max_steps=1, deadline_seconds=0)
        with self.assertRaisesRegex(ValueError, "step_timeout_seconds"):
            Run(run_id="run-1", max_steps=1, step_timeout_seconds=-1.0)


if __name__ == "__main__":
    unittest.main()
