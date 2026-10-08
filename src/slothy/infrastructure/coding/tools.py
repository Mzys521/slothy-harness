"""受控 Coding 能力；校验、宿主配置、单次授权和执行在执行器中完成。"""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError

from slothy.core.tools import ToolDefinition, ToolExecutor, ToolResult, ReplaySafety, ProgressReport

from .checks import CHECKS, check_command, run_command
from .workspace import CodingError, ScopedWorkspace, canonical_root


DEFAULT_SETTINGS = {"workspace_root": None, "allow_edits": True,
                    "allowed_checks": list(CHECKS), "check_timeout_seconds": 60}


class CodingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_root: StrictStr | None = Field(default=None, max_length=1000)
    allow_edits: StrictBool = True
    allowed_checks: list[Literal["python_unit", "python_integration", "npm_build", "npm_test", "git_diff"]] = Field(default_factory=lambda: list(CHECKS), max_length=5)
    check_timeout_seconds: StrictInt = Field(default=60, ge=1, le=120)


def validate_settings(value):
    try:
        settings = CodingSettings.model_validate(value).model_dump()
    except ValidationError:
        raise CodingError("invalid_coding_settings") from None
    settings["allowed_checks"] = list(dict.fromkeys(settings["allowed_checks"]))
    root = settings["workspace_root"]
    if root and root.strip():
        settings["workspace_root"], settings["root_identity"] = canonical_root(root)
    else:
        settings["workspace_root"] = None
    return settings


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListFiles(Arguments):
    path: StrictStr = Field(default=".", max_length=512)
    recursive: StrictBool = False
    limit: StrictInt = Field(default=200, ge=1, le=500)


class ReadFile(Arguments):
    path: StrictStr = Field(min_length=1, max_length=512)
    start_line: StrictInt = Field(default=1, ge=1)
    max_lines: StrictInt = Field(default=200, ge=1, le=500)


class SearchCode(Arguments):
    query: StrictStr = Field(min_length=1, max_length=200)
    path: StrictStr = Field(default=".", max_length=512)
    max_matches: StrictInt = Field(default=50, ge=1, le=100)


class WriteFile(Arguments):
    path: StrictStr = Field(min_length=1, max_length=512)
    content: StrictStr = Field(max_length=262144)
    expected_sha256: StrictStr | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class EditFile(Arguments):
    path: StrictStr = Field(min_length=1, max_length=512)
    old_text: StrictStr = Field(min_length=1, max_length=65536)
    new_text: StrictStr = Field(max_length=65536)
    expected_sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")


class RunChecks(Arguments):
    preset: Literal["python_unit", "python_integration", "npm_build", "npm_test", "git_diff"]


def _controlled_only(**kwargs):
    raise CodingError("controlled_executor_required")


def coding_tools(settings):
    entries = [
        ("list_files", "查看工作目录内的目录和文件，跳过密钥、依赖与生成目录。", ListFiles, False),
        ("read_file", "按行读取 UTF-8 文件，返回完整文件 SHA256；大结果用 get_result 分页。", ReadFile, False),
        ("search_code", "在工作目录内逐行检索字面文本，返回相对路径和行号。", SearchCode, False),
    ]
    if settings["allow_edits"]:
        entries += [("edit_file", "单次人工批准后精确替换唯一文本。必须提供 read_file 的 SHA256，文件变化则拒绝。", EditFile, True),
                    ("write_file", "单次人工批准后创建或更新 UTF-8 文件。更新必须提供原文件 SHA256。", WriteFile, True)]
    if settings["allowed_checks"]:
        entries += [("run_checks", "单次人工批准后执行设置中启用的固定项目检查；无任意命令或参数。", RunChecks, True)]
    definitions = []
    for name, description, model, mutates in entries:
        schema = model.model_json_schema()
        if name == "run_checks":
            schema["properties"]["preset"]["enum"] = list(settings["allowed_checks"])
        definitions.append(ToolDefinition(name, description, schema, model, _controlled_only,
            settings["check_timeout_seconds"] if name == "run_checks" else None,
            ReplaySafety.UNVERIFIABLE if mutates else ReplaySafety.IDEMPOTENT, "coding-v1"))
    return tuple(definitions)


class CodingToolExecutor(ToolExecutor):
    def __init__(self, registry, base, settings):
        self.registry, self.base, self.settings = registry, base, deepcopy(settings)
        self.workspace = ScopedWorkspace(settings["workspace_root"], settings["root_identity"])
        self.definitions = {tool.name: tool for tool in coding_tools(settings)}

    def _arguments(self, call):
        allowed = self.definitions[call.name]
        registered = self.registry.get_tool(call.name)
        if registered is None or registered.handler is not allowed.handler or registered.args_model is not allowed.args_model or registered.execution_version != allowed.execution_version or registered.replay_safety != allowed.replay_safety:
            raise CodingError("tool_not_allowed")
        return allowed.args_model.model_validate(call.arguments)

    def validate(self, call):
        if call.name not in self.definitions:
            validate = getattr(self.base, "validate", None)
            return validate(call) if callable(validate) else None
        try:
            args = self._arguments(call)
            if call.name == "run_checks":
                if args.preset not in self.settings["allowed_checks"]:
                    raise CodingError("check_not_allowed")
                check_command(self.workspace, args.preset)
            elif call.name in {"list_files", "search_code"}:
                self.workspace.path(args.path, directory=True)
            elif call.name == "read_file":
                self.workspace.path(args.path)
            elif call.name == "edit_file":
                text, digest, _ = self.workspace.read(args.path)
                if digest != args.expected_sha256:
                    raise CodingError("file_changed")
                if text.count(args.old_text) != 1:
                    raise CodingError("edit_match_not_unique")
            else:
                path = self.workspace.path(args.path, missing=True)
                if path.exists():
                    _, digest, _ = self.workspace.read(args.path)
                    if args.expected_sha256 != digest:
                        raise CodingError("file_changed")
                elif args.expected_sha256 is not None:
                    raise CodingError("file_changed")
        except ValidationError:
            return ToolResult({"code": "invalid_tool_arguments"}, True)
        except CodingError as error:
            return ToolResult({"code": error.code}, True)
        except (OSError, ValueError):
            return ToolResult({"code": "path_unavailable"}, True)
        return None

    def execute(self, call, context, on_progress=None):
        invalid = self.validate(call)
        if invalid is not None:
            return invalid
        if call.name not in self.definitions:
            return self.base.execute(call, context, on_progress)
        try:
            args = self._arguments(call)
            if self.definitions[call.name].replay_safety is ReplaySafety.UNVERIFIABLE and not context.approval_id:
                raise CodingError("approval_required")
            if call.name == "read_file":
                text, digest, _ = self.workspace.read(args.path)
                lines = text.splitlines(keepends=True)
                end = min(len(lines), args.start_line - 1 + args.max_lines)
                output = {"path": args.path, "sha256": digest, "content": "".join(lines[args.start_line - 1:end]),
                          "start_line": args.start_line, "line_count": len(lines), "next_line": end + 1 if end < len(lines) else None}
            elif call.name == "list_files":
                items, truncated = [], False
                for path, kind in self.workspace.walk(args.path, recursive=args.recursive):
                    if len(items) == args.limit:
                        truncated = True
                        break
                    items.append({"path": path, "kind": kind})
                output = {"entries": sorted(items, key=lambda item: item["path"]), "truncated": truncated}
            elif call.name == "search_code":
                matches, scanned, total_bytes, truncated = [], 0, 0, False
                for path, kind in self.workspace.walk(args.path):
                    if kind != "file":
                        continue
                    if scanned >= 500 or total_bytes >= 8 * 1024 * 1024:
                        truncated = True
                        break
                    scanned += 1
                    try:
                        text, _, _ = self.workspace.read(path)
                    except CodingError:
                        continue
                    total_bytes += len(text.encode("utf-8"))
                    for number, line in enumerate(text.splitlines(), 1):
                        if args.query in line:
                            matches.append({"path": path, "line": number, "text": line[:1000]})
                            if len(matches) >= args.max_matches:
                                truncated = True
                                break
                    if truncated:
                        break
                output = {"matches": matches, "files_scanned": scanned, "truncated": truncated}
            elif call.name == "edit_file":
                text, _, _ = self.workspace.read(args.path)
                if text.count(args.old_text) != 1:
                    raise CodingError("edit_match_not_unique")
                output = self.workspace.write(args.path, text.replace(args.old_text, args.new_text, 1), args.expected_sha256)
            elif call.name == "write_file":
                output = self.workspace.write(args.path, args.content, args.expected_sha256)
            else:
                command, cwd = check_command(self.workspace, args.preset)
                if on_progress:
                    on_progress(ProgressReport(0, 1, "运行项目检查"))
                output = {"preset": args.preset, **run_command(command, cwd,
                    min(self.settings["check_timeout_seconds"], context.timeout_seconds or float("inf")))}
                if on_progress:
                    on_progress(ProgressReport(1, 1, "项目检查结束"))
                return ToolResult(output, output["timed_out"] or output["exit_code"] != 0)
            return ToolResult(output)
        except CodingError as error:
            return ToolResult({"code": error.code}, True)
        except OSError:
            return ToolResult({"code": "coding_io_error"}, True)
