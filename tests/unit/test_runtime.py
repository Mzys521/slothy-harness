"""运行时状态和协作式截止时间的测试。"""

import unittest
from inspect import isabstract
from unittest.mock import patch

from slothy.core.runtime import Run, RunDeadlineExceededError, RunStatus, StepStatus
from slothy.core.tools import ToolExecutor


class RunStateTests(unittest.TestCase):
    def test_tool_executor_is_abstract(self) -> None:
        self.assertTrue(isabstract(ToolExecutor))
        with self.assertRaises(TypeError):
            ToolExecutor()

    def test_deadline_marks_active_step_failed(self) -> None:
        runtime = Run(run_id="run-deadline", max_steps=2, deadline_seconds=1.0)

        with patch("slothy.core.runtime.state.monotonic", side_effect=[10.0, 10.0, 12.0]):
            runtime.start()
            runtime.begin_step(1)
            with self.assertRaises(RunDeadlineExceededError):
                runtime.check_active()

        self.assertEqual(runtime.status, RunStatus.FAILED)
        self.assertEqual(runtime.steps[0].status, StepStatus.FAILED)

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "run_id"):
            Run(run_id=" ", max_steps=1)
        with self.assertRaisesRegex(ValueError, "max_steps"):
            Run(run_id="run-1", max_steps=0)
        with self.assertRaisesRegex(ValueError, "deadline_seconds"):
            Run(run_id="run-1", max_steps=1, deadline_seconds=0)


if __name__ == "__main__":
    unittest.main()
