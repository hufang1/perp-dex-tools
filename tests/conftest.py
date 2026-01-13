"""
Pytest配置文件

设置测试环境路径，使spread模块可以被导入
"""

import sys
from pathlib import Path

# 将项目根目录添加到sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 将spread目录添加到sys.path
spread_dir = project_root / "spread"
sys.path.insert(0, str(spread_dir))
