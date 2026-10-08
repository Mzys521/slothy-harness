"""Context 展示字段的显式投影；不会反射导出未知状态或报告字段。"""

from copy import deepcopy


CONFIG_FIELDS = ("model_window", "output_reserve", "safety_margin", "system_prompt",
    "tool_schemas", "task_state", "long_term_memory", "working_memory", "user_input_buffer")
LAYER_FIELDS = ("system_prompt", "tool_schemas", "task_state", "long_term_memory",
    "working_memory", "user_input_buffer")


def counters(value, names):
    return {name: value[name] for name in names
            if isinstance(value, dict) and type(value.get(name)) is int and value[name] >= 0}


def context_inspection(context, report, *, run_id, user_input):
    context = context if isinstance(context, dict) else {}
    value = context.get("task_state", {})
    value = value if isinstance(value, dict) else {}
    state = {"task_id": run_id, "goal": user_input or "", "plan": [],
             "completed_steps": [], "todo_list": [], "entities": {}}
    for name in ("task_id", "goal"):
        if isinstance(value.get(name), str):
            state[name] = value[name]
    for name in ("plan", "completed_steps", "todo_list"):
        if isinstance(value.get(name), list) and all(isinstance(item, str) for item in value[name]):
            state[name] = deepcopy(value[name])
    if isinstance(value.get("entities"), dict):
        state["entities"] = {k: v for k, v in value["entities"].items() if isinstance(k, str) and isinstance(v, str)}
    projected = None
    if isinstance(report, dict):
        projected = counters(report, ("input_tokens", "input_budget", "output_reserve", "summary_failures", "memory_topk"))
        projected["layer_tokens"] = counters(report.get("layer_tokens"), LAYER_FIELDS)
        allowed_actions = {"truncate_observation", "summarize_working_memory", "summary_fallback", "reduce_memory_topk", "compress_task_state"}
        actions = report.get("actions", [])
        projected["actions"] = [item for item in actions if isinstance(item, str) and item in allowed_actions] if isinstance(actions, (list, tuple)) else []
    config = counters(context.get("config"), CONFIG_FIELDS)
    return state, projected, config or None
