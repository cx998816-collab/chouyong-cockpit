"""查看本地 Excel 的结构：每个工作表的行列数、表头和前 2 行。

用法：python inspect_xlsx.py <xlsx 路径>
"""
import sys

import openpyxl


def main(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        ws.reset_dimensions()  # 飞书导出的文件尺寸信息不准，重新扫描
        rows = ws.iter_rows(max_row=3, values_only=True)
        n = sum(1 for _ in ws.iter_rows(values_only=True))
        print(f"## {ws.title}（{n} 行）")
        for i, row in enumerate(rows):
            cells = ["" if c is None else str(c)[:30] for c in row]
            while cells and not cells[-1]:
                cells.pop()
            print(("  表头：" if i == 0 else f"  样例{i}：") + " | ".join(cells))
        print()


if __name__ == "__main__":
    main(sys.argv[1])
