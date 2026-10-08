"""桌面 Context 投影只导出已知展示字段与有效计数。"""

import unittest

from slothy.application.dto.inspection import context_inspection, counters


class DesktopInspectionTests(unittest.TestCase):
    def test_projection_excludes_unknown_fields_and_does_not_share_mutable_state(self):
        context = {
            "task_state": {
                "task_id": "task", "goal": "goal", "plan": ["one"],
                "completed_steps": [], "todo_list": ["two"],
                "entities": {"order": "A-123", "object": {"internal": "hidden"}},
                "internal": "hidden",
            },
            "config": {"model_window": 8192, "output_reserve": 1024, "internal": "hidden"},
            "active": [{"role": "user", "content": "raw input"}],
        }
        report = {
            "input_tokens": 100, "input_budget": 7168,
            "layer_tokens": {"working_memory": 80, "internal": 20},
            "actions": ["truncate_observation", "internal", {"value": "hidden"}],
            "internal": "hidden",
        }
        state, projection, config = context_inspection(context, report,
            run_id="fallback", user_input="fallback")
        self.assertEqual(set(state), {"task_id", "goal", "plan", "completed_steps", "todo_list", "entities"})
        self.assertEqual(state["entities"], {"order": "A-123"})
        self.assertEqual(projection, {"input_tokens": 100, "input_budget": 7168,
            "layer_tokens": {"working_memory": 80}, "actions": ["truncate_observation"]})
        self.assertEqual(config, {"model_window": 8192, "output_reserve": 1024})
        state["plan"].append("local")
        self.assertEqual(context["task_state"]["plan"], ["one"])

    def test_invalid_optional_fields_fall_back_without_exporting_invalid_counters(self):
        self.assertEqual(counters({"count": True, "negative": -1, "fraction": 1.5},
            ("count", "negative", "fraction")), {})
        state, report, config = context_inspection(None, {"actions": None},
            run_id="task", user_input="goal")
        self.assertEqual(state["goal"], "goal")
        self.assertEqual(state["task_id"], "task")
        self.assertEqual(report, {"layer_tokens": {}, "actions": []})
        self.assertIsNone(config)


if __name__ == "__main__":
    unittest.main()
