"""策略判定与内置规则的测试。"""

import unittest

from slothy.core.policy import (
    AllowlistRule,
    PolicyDecision,
    PolicyEngine,
    PolicyVerdict,
    ToolNameRule,
    ToolPolicyRequest,
)


def request(name: str = "lookup") -> ToolPolicyRequest:
    return ToolPolicyRequest(call_id="call-1", name=name, run_id="run-1")


class PolicyDecisionTests(unittest.TestCase):
    def test_default_decision_allows_without_matching(self) -> None:
        decision = PolicyDecision()

        self.assertTrue(decision.is_allow)
        self.assertFalse(decision.matched)
        self.assertEqual((decision.policy, decision.reason), ("", ""))

    def test_verdict_helpers(self) -> None:
        deny = PolicyDecision(verdict=PolicyVerdict.DENY, policy="p")
        ask = PolicyDecision(verdict=PolicyVerdict.ASK, policy="p")

        self.assertTrue(deny.is_deny)
        self.assertTrue(deny.matched)
        self.assertTrue(ask.is_ask)
        self.assertTrue(ask.matched)


class ToolNameRuleTests(unittest.TestCase):
    def test_pattern_matches_with_wildcard(self) -> None:
        rule = ToolNameRule("shell*", PolicyVerdict.DENY)

        self.assertTrue(rule.decide(request("shell_exec")).is_deny)
        self.assertTrue(rule.decide(request("read_file")).is_allow)

    def test_matching_decision_carries_rule_name_and_reason(self) -> None:
        rule = ToolNameRule("rm_*", PolicyVerdict.ASK, name="dangerous")

        decision = rule.decide(request("rm_file"))

        self.assertEqual(decision.policy, "dangerous")
        self.assertIn("rm_file", decision.reason)

    def test_custom_reason_is_used(self) -> None:
        rule = ToolNameRule("shell*", PolicyVerdict.DENY, reason="禁止命令行")

        self.assertEqual(rule.decide(request("shell")).reason, "禁止命令行")


class AllowlistRuleTests(unittest.TestCase):
    def test_only_listed_tools_are_allowed(self) -> None:
        rule = AllowlistRule(frozenset({"add", "subtract"}))

        self.assertTrue(rule.decide(request("add")).is_allow)
        self.assertTrue(rule.decide(request("shell")).is_deny)

    def test_denied_decision_names_the_rule(self) -> None:
        rule = AllowlistRule(frozenset({"add"}))

        decision = rule.decide(request("multiply"))

        self.assertEqual((decision.policy, decision.verdict.value), ("allowlist", "deny"))


class PolicyEngineTests(unittest.TestCase):
    def test_engine_without_rules_allows_everything(self) -> None:
        engine = PolicyEngine()

        self.assertTrue(engine.decide(request()).is_allow)

    def test_first_non_allow_decision_wins(self) -> None:
        engine = PolicyEngine(
            rules=(
                ToolNameRule("read_*", PolicyVerdict.ALLOW),
                AllowlistRule(frozenset({"read_file"})),
            )
        )

        self.assertTrue(engine.decide(request("read_file")).is_allow)
        self.assertTrue(engine.decide(request("write_file")).is_deny)

    def test_rule_name_is_filled_when_rule_omits_it(self) -> None:
        class AnonymousRule:
            name = "anonymous"

            def decide(self, request: ToolPolicyRequest) -> PolicyDecision:
                return PolicyDecision(verdict=PolicyVerdict.DENY)

        decision = PolicyEngine(rules=(AnonymousRule(),)).decide(request())

        self.assertEqual(decision.policy, "anonymous")

    def test_engine_does_not_mutate_the_request(self) -> None:
        engine = PolicyEngine(rules=(ToolNameRule("shell*", PolicyVerdict.DENY),))
        target = request("shell")

        engine.decide(target)

        self.assertEqual(target.name, "shell")


if __name__ == "__main__":
    unittest.main()
