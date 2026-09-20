"""pytest 配置：确保 app 包可被导入，并把输出编码固定为 UTF-8。

Windows 控制台默认 GBK，中文输出会乱码，这里在收集阶段就修好。
"""

from __future__ import annotations

import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# 测试源码树时显式加入独立问卷子包。生产运行不走这条路径：要使用网页版问卷需把
# tcm-constitution-questionnaire 正常安装进同一虚拟环境；缺失时问卷 API 返回 501。
QUESTIONNAIRE_DIR = Path(__file__).resolve().parents[2] / "tcm-constitution-questionnaire"
if str(QUESTIONNAIRE_DIR) not in sys.path:
    sys.path.insert(0, str(QUESTIONNAIRE_DIR))

# 控制台 UTF-8（Python 3.7+ 支持 reconfigure）
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001, S110 - 编码调整失败不影响测试逻辑
        pass
