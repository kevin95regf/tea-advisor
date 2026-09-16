"""从请求头里取用户自带的 API Key。

只做一件事：把 `Authorization: Bearer <key>` 解析成裸 Key。

单独成模块有两个理由：
1. 可脱离 FastAPI 单测（回归测试见 tests/test_key_handling.py）；
2. 把"绝不记录 Key"这条规则集中在一处，好审计。

安全约定（硬规则）
------------------
* 本模块**不写任何日志**，也不会把 Key 放进异常信息。
* 调用方不得把返回值写进日志、响应体或错误详情。
* 请求头本身绝不进入日志 —— uvicorn 只记录方法/路径/状态码，本项目也不得添加
  会打印 header 的中间件。
"""

from __future__ import annotations

import re

# Bearer 前缀大小写不敏感；Key 内部不允许出现空白
_BEARER_RE = re.compile(r"^\s*bearer\s+(\S+)\s*$", re.IGNORECASE)

# 只做"长度合理"的宽松校验。真正的有效性由模型服务方返回 401 决定。
_MAX_KEY_LEN = 256


def extract_api_key(authorization: str | None) -> str | None:
    """从 Authorization 头解析 Bearer Key。

    返回 `None` 表示"没有可用 Key"，调用方应回退到服务端兜底 Key。

    格式不对（缺少 Bearer 前缀、含空白、超长）时也返回 `None`，不抛异常：
    宁可回退，也不要让用户拿到一个难懂的 500。
    这种情况下 `meta.key_source` 会是 `server`，前端会把
    「本次使用服务端 Key」显示出来 —— 用户因此能看出自己填的 Key 没生效。
    """
    if not authorization:
        return None

    match = _BEARER_RE.match(authorization)
    if not match:
        return None

    key = match.group(1).strip()
    if not key or len(key) > _MAX_KEY_LEN:
        return None
    return key
