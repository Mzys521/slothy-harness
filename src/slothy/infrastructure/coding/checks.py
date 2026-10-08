"""固定项目检查命令；无模型 shell/参数，输出和进程等待均受限。"""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from threading import Thread
from time import monotonic

from .workspace import CodingError


CHECKS = {
    "python_unit": "Python 单元测试（tests/unit）",
    "python_integration": "Python 集成测试（tests/integration）",
    "npm_build": "npm run build",
    "npm_test": "npm test",
    "git_diff": "Git 差异空白检查",
}
OUTPUT_BYTES = 65536


def check_command(workspace, preset):
    root = workspace.path(".", directory=True)
    if preset in {"python_unit", "python_integration"}:
        folder = "tests/unit" if preset == "python_unit" else "tests/integration"
        workspace.path(folder, directory=True)
        # .venv 是生成目录但允许宿主从固定位置选解释器；模型不能读取或指定它。
        python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if python.exists():
            workspace.path(python.relative_to(root).as_posix())
        else:
            python = Path(sys.executable)
        return [str(python), "-m", "unittest", "discover", "-s", folder, "-p", "test_*.py", "-v"], root
    if preset in {"npm_build", "npm_test"}:
        # 支持仓库根目录或常用 frontend 子项目，两处都不允许重定向。
        folder = "." if (root / "package.json").is_file() else "frontend"
        cwd = workspace.path(folder, directory=True)
        workspace.path((Path(folder) / "package.json").as_posix())
        node, npm = shutil.which("node"), shutil.which("npm")
        if not node or not npm:
            raise CodingError("check_unavailable")
        candidates = (Path(npm).parent / "node_modules/npm/bin/npm-cli.js",
                      Path(node).parent / "node_modules/npm/bin/npm-cli.js")
        cli = next((path for path in candidates if path.is_file()), None)
        if cli is None:
            raise CodingError("check_unavailable")
        return [node, str(cli), *( ["run", "build"] if preset == "npm_build" else ["test"] )], cwd
    if preset == "git_diff":
        git = shutil.which("git")
        if not git or not (root / ".git").exists():
            raise CodingError("check_unavailable")
        return [git, "--no-pager", "diff", "--check", "--no-ext-diff", "--no-textconv"], root
    raise CodingError("check_not_allowed")


def child_environment():
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
    return {**{key: value for key, value in os.environ.items() if key.upper() in allowed},
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "CI": "1", "NO_COLOR": "1",
            "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def stop_process(process):
    if os.name == "nt":
        # 固定参数仅引用由本工具创建的 PID，不接受模型输入。
        killer = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/taskkill.exe"
        try:
            subprocess.run([str(killer), "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                           creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_command(command, cwd, timeout):
    output = bytearray()
    count = 0
    def drain(stream):
        nonlocal count
        try:
            while chunk := stream.read(4096):
                count += len(chunk)
                output.extend(chunk[:max(0, OUTPUT_BYTES - len(output))])
        finally:
            stream.close()
    started = monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=child_environment(), shell=False,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        start_new_session=os.name != "nt")
    reader = Thread(target=drain, args=(process.stdout,), daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_process(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    finally:
        reader.join(timeout=1)
    return {"exit_code": process.poll(), "timed_out": timed_out,
            "output": bytes(output).decode("utf-8", errors="replace"),
            "truncated": count > OUTPUT_BYTES or reader.is_alive(),
            "duration_ms": round((monotonic() - started) * 1000, 2)}
