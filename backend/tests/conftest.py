"""pytest 配置：确保 app 包可被导入，并把输出编码固定为 UTF-8。

Windows 控制台默认 GBK，中文输出会乱码，这里在收集阶段就修好。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 控制台 UTF-8（Python 3.7+ 支持 reconfigure）
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass
