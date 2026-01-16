#!/usr/bin/env python3
"""
Spread套利机器人启动脚本

从项目根目录运行: python run_spread_bot.py
"""

import sys
from pathlib import Path

# 添加 spread 目录到 Python 路径
spread_dir = Path(__file__).parent / "spread"
if str(spread_dir) not in sys.path:
    sys.path.insert(0, str(spread_dir))

# 添加项目根目录到 Python 路径（用于导入 exchanges 模块）
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入并运行 spread_arb_bot
from spread import spread_arb_bot

if __name__ == "__main__":
    import asyncio
    asyncio.run(spread_arb_bot.main())
