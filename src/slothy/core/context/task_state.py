"""宿主维护的任务状态；检索、摘要和模型文本不能隐式改写它。"""

from copy import deepcopy
from dataclasses import dataclass, field
from json import dumps

from .contracts import ContextError


@dataclass(frozen=True)
class TaskState:
    task_id: str = "unbound"
    goal: str = ""
    plan: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    todo_list: list[str] = field(default_factory=list)
    entities: dict[str, str] = field(default_factory=dict)

    def to_dict(self):
        return deepcopy({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def parse(cls, value):
        keys = set(cls.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) != keys:
            raise ContextError("任务状态字段不匹配")
        if any(not isinstance(value[k], str) for k in ("task_id", "goal")) or not value["task_id"]:
            raise ContextError("任务标识和目标必须是字符串")
        if any(not isinstance(value[k], list) or any(not isinstance(i, str) for i in value[k])
               for k in ("plan", "completed_steps", "todo_list")):
            raise ContextError("任务步骤必须是字符串列表")
        if not isinstance(value["entities"], dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value["entities"].items()):
            raise ContextError("任务实体必须是字符串映射")
        dumps(value, allow_nan=False)
        return cls(**deepcopy(value))
