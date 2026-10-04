"""事件契约、分发和时间线的测试。"""

import unittest

from slothy.core.events import (
    EVENT_TYPES,
    EventBus,
    LLMTimeout,
    Metric,
    ModelError,
    ModelResponded,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    RunTimeline,
    StepEnd,
    StepOutcome,
    StepStarted,
    TokenUsage,
    ToolCallEnd,
    ToolCallStart,
    ToolError,
    ToolTimeout,
    describe_error,
)
from slothy.core.model import ModelUsage
from slothy.core.runtime import (
    RunDeadlineExceededError,
    StepLimitExceededError,
    StepTimeoutError,
)


class EventContractTests(unittest.TestCase):
    def test_every_event_type_is_unique_and_dotted(self) -> None:
        identifiers = [event.EVENT_TYPE for event in EVENT_TYPES]

        self.assertEqual(len(identifiers), len(set(identifiers)))
        for identifier in identifiers:
            with self.subTest(identifier=identifier):
                self.assertTrue(identifier.startswith("run."))

    def test_events_share_a_single_base_class(self) -> None:
        for event in EVENT_TYPES:
            with self.subTest(event=event.__name__):
                self.assertTrue(issubclass(event, RunEvent))

    def test_record_contains_only_safe_primitives(self) -> None:
        event = ToolCallStart(call_id="call-1", name="lookup", argument_keys=("key",))
        event.run_id = "run-1"
        event.sequence = 3
        event.step_number = 1

        record = event.as_record()

        self.assertEqual(record["event_type"], "run.tool.call_started")
        self.assertEqual(record["run_id"], "run-1")
        self.assertEqual(record["step_number"], 1)
        self.assertEqual(record["argument_keys"], ("key",))

    def test_error_codes_are_stable_classifications(self) -> None:
        cases = {
            RunDeadlineExceededError("x"): "run_timeout",
            StepTimeoutError("x"): "step_timeout",
            StepLimitExceededError("x"): "step_limit_reached",
        }
        for error, expected in cases.items():
            with self.subTest(error=type(error).__name__):
                self.assertEqual(describe_error(error).error_code, expected)

        self.assertIsNone(describe_error(None))
        self.assertEqual(describe_error(ValueError("x")).error_type, "ValueError")
        self.assertEqual(
            describe_error(TimeoutError("x")).error_code, "unexpected_timeout"
        )
        self.assertEqual(describe_error(ValueError("x")).error_code, "runtime_error")

    def test_model_and_tool_events_carry_only_metadata(self) -> None:
        usage = ModelUsage(total_tokens=3)
        for event in (
            ModelResponded(duration_ms=1.0, text_length=5, usage=usage),
            ModelError(error=None),
            LLMTimeout(),
            ToolCallEnd(call_id="c", name="lookup", output_size=12),
            ToolError(call_id="c", name="lookup"),
            ToolTimeout(call_id="c", name="lookup"),
            TokenUsage(usage=usage, cumulative=usage),
            Metric(name="run.duration_ms", value=1.0, unit="ms"),
        ):
            with self.subTest(event=type(event).__name__):
                values = vars(event).values()
                self.assertFalse(any(isinstance(value, BaseException) for value in values))


class EventBusTests(unittest.TestCase):
    def test_subscribers_receive_only_matching_events(self) -> None:
        bus = EventBus()
        steps: list[int] = []
        runs: list[str] = []
        bus.subscribe(StepStarted, lambda event: steps.append(event.step_number))
        bus.subscribe(RunCompleted, lambda event: runs.append(event.event_type))

        bus.notify(StepStarted(step_number=1))
        bus.notify(RunCompleted())
        bus.notify(RunFailed())

        self.assertEqual((steps, runs), ([1], ["run.completed"]))

    def test_base_class_subscription_covers_subclasses(self) -> None:
        bus = EventBus()
        received: list[str] = []
        bus.subscribe(RunEvent, lambda event: received.append(event.event_type))

        bus.notify(StepStarted())
        bus.notify(ToolCallStart(call_id="call-1"))

        self.assertEqual(received, ["run.step.started", "run.tool.call_started"])

    def test_on_decorator_and_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[str] = []

        @bus.on(StepEnd)
        def record(event: StepEnd) -> None:
            received.append(event.outcome.value)

        bus.notify(StepEnd(outcome=StepOutcome.COMPLETED))
        unsubscribe = bus.subscribe(StepEnd, lambda event: received.append("extra"))
        unsubscribe()
        bus.notify(StepEnd(outcome=StepOutcome.FAILED))

        self.assertEqual(received, ["completed", "failed"])

    def test_failing_subscriber_is_isolated_and_recorded(self) -> None:
        bus = EventBus()
        delivered: list[str] = []

        def broken(event: RunEvent) -> None:
            raise RuntimeError("监听器故障")

        bus.subscribe(RunStarted, broken)
        bus.subscribe(RunStarted, lambda event: delivered.append(event.event_type))

        bus.notify(RunStarted(max_steps=1))

        self.assertEqual(delivered, ["run.started"])
        self.assertEqual(len(bus.failures), 1)
        self.assertEqual(bus.failures[0].error_type, "RuntimeError")
        self.assertEqual(bus.failures[0].event_type, "run.started")

    def test_clear_removes_subscriptions_but_keeps_failures(self) -> None:
        bus = EventBus()
        bus.subscribe(RunStarted, lambda event: 1 / 0)
        bus.notify(RunStarted())

        bus.clear()
        bus.notify(RunStarted())

        self.assertEqual(len(bus.failures), 1)


class RunTimelineTests(unittest.TestCase):
    def test_timeline_records_arrival_order_and_filters(self) -> None:
        bus = EventBus()
        timeline = RunTimeline(bus)

        bus.notify(ModelResponded(text_length=2, usage=ModelUsage(total_tokens=1)))
        bus.notify(StepEnd(outcome=StepOutcome.COMPLETED, tool_call_count=1))
        bus.notify(RunCompleted(steps=1))

        self.assertEqual(
            timeline.types(),
            ["run.model.responded", "run.step.ended", "run.completed"],
        )
        self.assertEqual(len(timeline.of_type(StepEnd)), 1)
        self.assertEqual(
            timeline.first("run.completed").event_type, "run.completed"
        )
        self.assertIsNone(timeline.first(RunFailed))
        self.assertEqual(timeline.first(StepEnd).tool_call_count, 1)

    def test_timeline_shares_bus_failures(self) -> None:
        bus = EventBus()
        timeline = RunTimeline(bus)
        bus.subscribe(RunStarted, lambda event: 1 / 0)

        bus.notify(RunStarted())

        self.assertEqual(len(timeline.failures), 1)

    def test_timeline_without_bus_accepts_manual_events(self) -> None:
        timeline = RunTimeline()
        timeline.notify(RunCompleted())
        timeline.clear()

        self.assertEqual(timeline.types(), [])


if __name__ == "__main__":
    unittest.main()
