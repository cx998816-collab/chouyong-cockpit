"""把 App Secret 写入 config.env（输入内容不回显，也不会打印出来）。

用法：双击 设置Secret.bat，粘贴 Secret（右键或 Ctrl+V）后回车。
"""
import getpass
import re
from pathlib import Path

path = Path(__file__).with_name("config.env")
secret = getpass.getpass("请粘贴 App Secret（屏幕上不会显示），然后按回车：").strip()
if not secret:
    print("没有收到内容，config.env 未修改。")
elif secret.startswith("cli_") or not re.fullmatch(r"[A-Za-z0-9]{20,64}", secret):
    print(f"收到 {len(secret)} 个字符，不像 App Secret（应为约 32 位字母数字，且不以 cli_ 开头）。")
    print("请只复制 App Secret 那一串，不要带上 App ID 或其他文字。config.env 未修改。")
else:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    lines = [f"FEISHU_APP_SECRET={secret}" if l.strip().startswith("FEISHU_APP_SECRET") else l for l in lines]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入（{len(secret)} 个字符）。可以关闭此窗口。")
