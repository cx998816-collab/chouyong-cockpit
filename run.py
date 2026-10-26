"""守护运行：机器人意外退出后自动重启（间隔逐步加长，最长 5 分钟）。

用法：python run.py（启动机器人.bat 调用的就是它）；关闭窗口即停止。
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
delay = 5
while True:
    started = time.time()
    code = subprocess.call([sys.executable, "-u", str(HERE / "bot.py")], cwd=HERE)
    if time.time() - started > 600:  # 稳定跑过 10 分钟才算正常，重置重启间隔
        delay = 5
    print(f"[守护] 机器人退出（代码 {code}），{delay} 秒后重启", flush=True)
    time.sleep(delay)
    delay = min(delay * 2, 300)
