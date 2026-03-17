from __future__ import annotations

"""兼容聚合入口。

说明：
- 历史 `legacy_agent.py` 已拆分到多个子模块：
  - core_utils.py
  - sources_and_llm.py
  - rendering.py
  - workflow.py
- 对外仍保持 `run_once/build_parser/main` 等符号可从本模块导入。
"""

from app.paper_digest.workflow import *  # noqa: F401,F403

