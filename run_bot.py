#!/usr/bin/env python3
"""
套利机器人启动脚本

在项目根目录运行此脚本来启动机器人
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

# 导入并运行主函数
if __name__ == "__main__":
    import asyncio
    from spread_arb_bot import main

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
