"""拿到凭证后先运行一次：列出表格里的所有工作表、表头和前 3 行，写入 表格结构.txt。

用法：python inspect_sheet.py
"""
from pathlib import Path

from feishu_sheet import FeishuSheet, load_config


def main():
    cfg = load_config()
    fs = FeishuSheet(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
    token = fs.spreadsheet_token(cfg["WIKI_TOKEN"])
    lines = [f"电子表格 token：{token}", ""]
    for sh in fs.sheets(token):
        g = sh["grid_properties"]
        mark = "  ← 链接指向的工作表" if sh["sheet_id"] == cfg.get("SHEET_ID") else ""
        lines.append(f"## {sh['title']}（sheet_id={sh['sheet_id']}，{g['row_count']} 行 × {g['column_count']} 列）{mark}")
        for i, row in enumerate(fs.values(token, sh, max_rows=4)):
            lines.append(("表头：" if i == 0 else f"样例{i}：") + " | ".join("" if c is None else str(c) for c in row))
        lines.append("")
    out = Path(__file__).with_name("表格结构.txt")
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
