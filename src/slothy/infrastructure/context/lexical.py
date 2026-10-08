"""可复用的中文/标识符词项，索引与查询采用同一规则。"""

import re


def terms(text):
    tokens = re.findall(r"[A-Za-z0-9_]+(?:[-.:][A-Za-z0-9_]+)*|[\u3400-\u9fff]", text.lower())
    tokens.extend(text[i:i + 2] for i in range(len(text) - 1)
                  if all("\u3400" <= c <= "\u9fff" for c in text[i:i + 2]))
    return tokens
