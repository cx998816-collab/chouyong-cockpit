"""从签约进度表算出卡片上的摘要指标，口径与「抽佣签约驾驶舱」一致。

输入是表名 → 记录列表（[{表头: 值}]），需要两张表：
- 总未签约明细：未签商家池，每行一家
- 拜访记录明细：每次拜访一行，按商家 id 关联

阶段判定（同驾驶舱页脚口径）：
1. 预估谈判时间写明退出 / 暂停 → 已退出
2. 有拜访记录 → 取最近一次拜访结论；表格写「已同意签约」而拜访尚未体现的仍算已同意
3. 无拜访 → 取「10月后攻坚拜访状态」，其次「商家拜访状态」
   （状态为「未拜访」的记为未首访）
4. 既无拜访也无状态 → 未触达
"""
import re
from datetime import datetime, timedelta

UNSIGNED_SHEET = "总未签约明细"
VISIT_SHEET = "拜访记录明细"
TOP800_TIERS = {"top100", "top101-top200", "top201-top300", "top301-top500", "top501-top800"}

STAGES = {
    "pending": "已签待确认",
    "agree": "已同意待签",
    "consider": "沟通考虑中",
    "refuse": "明确拒绝",
    "new": "未首访",
    "pool": "未触达",
    "exit": "已退出",
}


def _visit_stage(result):
    r = str(result or "")
    if "已签约" in r or "转合同" in r:
        return "pending"
    if "同意" in r:
        return "agree"
    if "拒绝" in r:
        return "refuse"
    if "考虑" in r:
        return "consider"
    return None


def _table_stage(status):
    s = str(status or "")
    if "同意" in s:
        return "agree"
    if "拒绝" in s:
        return "refuse"
    if "考虑" in s:
        return "consider"
    if "未拜访" in s:
        return "new"
    return None


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _date(v, today=None):
    """解析日期：datetime、2026-10-23、2026/10/23、Excel 序列号，或飞书显示格式「10月23日」（无年份，取不晚于今天的最近一年）。"""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return datetime(1899, 12, 30) + timedelta(days=float(v))
    s = str(v).strip()
    m = re.match(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", s)
    if m:
        return datetime(*map(int, m.groups()))
    m = re.match(r"(\d{1,2})月(\d{1,2})日?", s)
    if m:
        today = today or datetime.now()
        d = datetime(today.year, int(m.group(1)), int(m.group(2)))
        return d if d <= today else d.replace(year=today.year - 1)
    return None


def _id(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


ZONES = ("十三沙", "沙河金马", "杭州")


def zone_of(group):
    """大市场分配：按业绩归属（组别）归到三个战区，其余为「其他」（与驾驶舱网页一致）。"""
    g = str(group or "")
    if "十三行" in g:
        return "十三沙"
    if "金马" in g:
        return "沙河金马"
    if g.startswith("6") or "杭州" in g:
        return "杭州"
    return "其他"


def merchant_stages(unsigned, visits):
    """返回 [(商家记录, 阶段)]。"""
    latest = {}
    for v in visits:
        mid, d = _id(v.get("商家id")), _date(v.get("拜访时间"))
        if mid is None or d is None:
            continue
        if mid not in latest or d >= latest[mid][0]:
            latest[mid] = (d, v.get("商家状态"))
    out = []
    for m in unsigned:
        mid = _id(m.get("商家ID"))
        if mid is None:
            continue
        table = _table_stage(m.get("10月后攻坚拜访状态")) or _table_stage(m.get("商家拜访状态"))
        est = str(m.get("预估谈判时间") or "")
        if "退出" in est or "暂停" in est:
            stage = "exit"
        elif mid in latest and _visit_stage(latest[mid][1]):
            stage = _visit_stage(latest[mid][1])
            if table == "agree" and stage in ("consider", "refuse"):
                stage = "agree"
        elif table:
            stage = table
        else:
            stage = "pool"
        out.append((m, stage))
    return out


def build_summary(tables, today=None):
    unsigned, visits = tables[UNSIGNED_SHEET], tables[VISIT_SHEET]
    today = today or datetime.now()
    staged = merchant_stages(unsigned, visits)
    focus = [(m, s) for m, s in staged if str(m.get("商家分层") or "").strip() in TOP800_TIERS]
    counts = {k: 0 for k in STAGES}
    for _, s in focus:
        counts[s] += 1
    live = [(m, s) for m, s in focus if s not in ("pending", "exit")]
    gmv = sum(_num(m.get("9月销售额")) for m, _ in live) / 1e4
    uplift = sum(_num(m.get("9月销售额")) * max(_num(m.get("后续抽佣比例")) - _num(m.get("当前抽佣比例")), 0)
                 for m, _ in live) / 1e4
    zones = {z: {"unsigned": 0, "uplift": 0.0} for z in ZONES}
    for m, _ in live:
        z = zones.get(zone_of(m.get("业绩归属")))
        if z:
            z["unsigned"] += 1
            z["uplift"] += _num(m.get("9月销售额")) * max(_num(m.get("后续抽佣比例")) - _num(m.get("当前抽佣比例")), 0) / 1e4
    for z in zones.values():
        z["uplift"] = round(z["uplift"], 1)
    since = today - timedelta(days=30)
    dates = [_date(v.get("拜访时间")) for v in visits]
    visit_dates = [d for d in dates if d]
    return {
        "as_of": max(visit_dates).strftime("%m-%d") if visit_dates else "—",
        "pool_total": len(staged),
        "focus_total": len(focus),
        "unsigned": len(live),
        "gmv_unsigned": round(gmv, 1),
        "uplift": round(uplift, 1),
        "counts": counts,
        "zones": zones,
        "visits_30d": sum(1 for d in visit_dates if d >= since),
    }
