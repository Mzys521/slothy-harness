"""MiMo SDK 异常映射、时限和策略重试集成；不访问网络。"""

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from openai import APIConnectionError, APIStatusError, APITimeoutError

from slothy.core.events import (
    LLMTimeoutError, RunTimeline, TokenChunk, TransientModelError,
)
from slothy.core.policy import RetryPolicy, TimeoutPolicy
from slothy.core.runtime import AgentRunner
from slothy.core.tools import ToolContext
from slothy.infrastructure.llm.providers.mimo_provider import MimoProvider


class Registry:
    def definitions(self):
        return []


class Executor:
    def execute(self, *_):
        raise AssertionError("No tool expected")


def fake_request(method, url):
    return SimpleNamespace(method=method, url=url)


def fake_response(status_code, *, request):
    return SimpleNamespace(status_code=status_code, request=request, headers={})


def response():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="done", tool_calls=None,
        ))],
        usage=None,
    )


class Completions:
    def __init__(self, error):
        self.error = error
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            raise self.error
        return response()


@patch.dict("os.environ", {"MIMO_API_KEY": "placeholder-for-tests"}, clear=True)
class MimoResilienceTests(unittest.TestCase):
    def provider(self, completions):
        provider = MimoProvider(
            api_key="test", base_url="https://example.test/v1", model="test",
        )
        self.assertEqual(provider.client.max_retries, 0)
        provider.client.close()
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        return provider

    def test_connection_rate_limit_and_server_failures_are_retryable(self):
        request = fake_request("POST", "https://example.test/v1")
        failures = [
            APIConnectionError(request=request),
            APIStatusError(
                "rate limit", response=fake_response(429, request=request), body=None,
            ),
            APIStatusError(
                "server failure", response=fake_response(503, request=request),
                body=None,
            ),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                completions = Completions(failure)
                runner = AgentRunner(
                    self.provider(completions), Registry(), Executor(),
                    policy=RetryPolicy(TimeoutPolicy(timeout_seconds=30)),
                )
                result = runner.run("test", context=ToolContext("run-sdk"))
                self.assertEqual(result.output, "done")
                self.assertEqual(len(completions.requests), 2)
                first, second = [item["timeout"] for item in completions.requests]
                self.assertGreater(first, 0)
                self.assertLessEqual(first, 30)
                self.assertLessEqual(second, first)

    def test_authentication_failure_is_not_retried(self):
        request = fake_request("POST", "https://example.test/v1")
        error = APIStatusError(
            "private auth detail", response=fake_response(401, request=request),
            body=None,
        )
        completions = Completions(error)
        runner = AgentRunner(
            self.provider(completions), Registry(), Executor(), policy=RetryPolicy(),
        )
        with self.assertRaises(APIStatusError) as raised:
            runner.run("test", context=ToolContext("run-sdk"))
        self.assertIs(raised.exception, error)
        self.assertEqual(len(completions.requests), 1)

    def test_sdk_timeout_is_classified(self):
        request = fake_request("POST", "https://example.test/v1")
        provider = self.provider(Completions(APITimeoutError(request=request)))
        with self.assertRaises(LLMTimeoutError):
            provider.generate([{"role": "user", "content": "test"}])

    def test_failed_stream_is_closed_and_not_replayed(self):
        class Stream:
            closed = False

            def __iter__(self):
                yield SimpleNamespace(
                    usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(
                        content="partial", tool_calls=None,
                    ))],
                )
                raise APIConnectionError(request=fake_request(
                    "POST", "https://example.test",
                ))

            def close(self):
                self.closed = True

        stream = Stream()
        requests = []

        def create(**kwargs):
            requests.append(kwargs)
            return stream

        provider = self.provider(SimpleNamespace(create=create))
        timeline = RunTimeline()
        runner = AgentRunner(provider, Registry(), Executor(), policy=RetryPolicy())
        with self.assertRaises(TransientModelError):
            runner.run("test", context=ToolContext("run-sdk"), events=timeline)
        self.assertTrue(stream.closed)
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            [event.text for event in timeline.of_type(TokenChunk)], ["partial"],
        )


if __name__ == "__main__":
    unittest.main()
