"""云端生成驾驶舱站点：读知识库表格 → site/（网页 + data.json + 卡片摘要 summary.json）。

GitHub Actions 定时运行它，再由 Cloudflare Pages 发布；飞书 @机器人 时由 functions/ 里的函数读 summary.json 回卡片。
本机也可以运行（读 config.env），用于调试：python build_site.py
"""
import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cockpit_data
from feishu_sheet import FeishuSheet, load_config, xlsx_tables
from summary import build_summary

HERE = Path(__file__).parent
SITE = HERE / "site"
STATIC = ["index.html", "anim.js", "d3.min.js"]
CST = timezone(timedelta(hours=8))  # GitHub 的机器是 UTC，统一按北京时间记录

HEADERS = """/data.json
  Cache-Control: no-cache
/summary.json
  Cache-Control: no-cache
/health.json
  Cache-Control: no-cache
/
  Cache-Control: no-cache
/index.html
  Cache-Control: no-cache
/d3.min.js
  Cache-Control: public, max-age=604800
"""


def main():
    cfg = load_config()
    t0 = time.time()
    if cfg.get("LOCAL_XLSX"):
        tables, source = xlsx_tables(cfg["LOCAL_XLSX"], cockpit_data.SHEETS), "本地 Excel"
    else:
        fs = FeishuSheet(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
        tables, source = fs.tables(fs.spreadsheet_token(cfg["WIKI_TOKEN"]), cockpit_data.SHEETS), "知识库表格"
    now = datetime.now(CST).replace(tzinfo=None)
    SITE.mkdir(exist_ok=True)
    for name in STATIC:
        shutil.copy2(HERE / "web" / name, SITE / name)
    dump = lambda name, obj: (SITE / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dump("data.json", cockpit_data.build(tables, now))
    dump("summary.json", {"summary": build_summary(tables, today=now), "source": source,
                          "read_at": now.strftime("%Y-%m-%d %H:%M")})
    dump("health.json", {"ok": True, "built_at": now.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - t0),
                         "rows": {k: len(v) for k, v in tables.items()}})
    (SITE / "_headers").write_text(HEADERS, encoding="utf-8")
    print(f"站点已生成：{SITE}（读表 {round(time.time() - t0)} 秒）")


if __name__ == "__main__":
    main()
