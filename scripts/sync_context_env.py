"""同步环境模板的键名，保留本地值；不打印、复制或推断任何密钥。"""

from dataclasses import fields
from pathlib import Path
import re

from slothy.core.context import ContextConfig, RetrievalConfig


KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
MODEL_KEYS = (
    "DASHSCOPE_API_KEY", "DASHSCOPE_MODEL", "DASHSCOPE_CHAT_MODEL", "DASHSCOPE_RERANK_MODEL",
    "DASHSCOPE_BASE_URL", "DASHSCOPE_BASE_URL_WITH_OPENAI", "SLOTHY_CONTEXT_DB",
)


def names(text):
    return [match.group(1) for line in text.splitlines() if (match := KEY.match(line))]


def synchronize(directory):
    root = Path(directory).resolve()
    actual, example = root / ".env", root / ".env.example"
    if actual.parent != root or example.parent != root or actual.is_symlink() or example.is_symlink():
        raise ValueError("环境模板必须属于指定项目目录")
    local = actual.read_text(encoding="utf-8-sig") if actual.exists() else ""
    template = example.read_text(encoding="utf-8-sig") if example.exists() else ""
    configured = set(names(local))
    all_names = dict.fromkeys((*names(template), *names(local), *MODEL_KEYS,
                              *("SLOTHY_CONTEXT_" + f.name.upper() for f in fields(ContextConfig)),
                              *("SLOTHY_RAG_" + f.name.upper() for f in fields(RetrievalConfig))))
    missing = [name for name in all_names if name not in configured]
    if missing:
        # 仅追加空值；现有本地配置的值不被写到模板或输出。
        with actual.open("a", encoding="utf-8") as stream:
            if local and not local.endswith("\n"):
                stream.write("\n")
            stream.write("\n# Context System: blank optional values use documented defaults.\n")
            stream.writelines(name + "=\n" for name in missing)
    example.write_text("# Placeholders only. Replace required settings; leave optional values blank for defaults.\n" +
                       "# DASHSCOPE_MODEL is embedding only; text generation uses DASHSCOPE_CHAT_MODEL.\n" +
                       "".join(name + "=<YOUR_" + name + ">\n" for name in all_names), encoding="utf-8")
    if set(names(actual.read_text(encoding="utf-8-sig"))) != set(all_names):
        raise ValueError("环境模板键名同步失败")
    return {"key_count": len(all_names), "local_keys_added": len(missing), "example_placeholders_only": True}


if __name__ == "__main__":
    print(synchronize(Path(__file__).resolve().parents[1]))
