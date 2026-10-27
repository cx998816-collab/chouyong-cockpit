"""每日战报：按拜访记录还原「最近一个有拜访的日子」发生了什么变化。

口径（与驾驶舱「每日变化」一致的思路）：
- 当日拜访：拜访时间为该日的记录数，与前一个有拜访的日子对比
- 每家当日拜访过的商家，比较「当日最后一次拜访结论」与「当日之前最近一次拜访结论」：
  新签约（已签约/转合同）、新同意、阶段推进、新增拒绝；之前从未拜访的算首访
- 合同签署时间为该日的商家也算新签约
"""
import json
from datetime import timedelta
from pathlib import Path

from summary import _date, _id, _visit_stage, zone_of

ALL_SHEET = "商家名单总表"
CONTRACT_SHEET = "签约商家"
VISIT_SHEET = "拜访记录明细"
RANK = {"refuse": 0, None: 1, "consider": 2, "agree": 3, "pending": 4}
HISTORY = Path(__file__).with_name("web") / "history.json"


def _brand(name):
    name = str(name or "").strip()
    head, _, tail = name.rpartition("-")
    return tail.strip() or name


def build_daily(tables):
    info = {}
    for a in tables.get(ALL_SHEET, []):
        mid = _id(a.get("商家ID"))
        if mid is not None:
            info[mid] = {"brand": _brand(a.get("商家")), "owner": str(a.get("商务") or "").strip(),
                         "zone": zone_of(a.get("业绩归属"))}

    visits, undated = [], []
    for v in tables[VISIT_SHEET]:
        mid, d = _id(v.get("商家id")), _date(v.get("拜访时间"))
        if mid is not None and d:
            visits.append((d.date(), mid, v))
        elif mid is not None:  # 填了商家但没填拜访时间：归不到某一天，单独提示补录
            undated.append((info.get(mid, {}).get("brand") or _brand(v.get("商家名称")), str(v.get("拜访人员") or "").strip()))
    if not visits:
        return None
    visits.sort(key=lambda x: x[0])
    days = sorted({d for d, _, _ in visits})
    day = days[-1]
    prev_day = days[-2] if len(days) > 1 else None
    week = [day - timedelta(days=i) for i in range(6, -1, -1)]
    per_day = {d: 0 for d in week}
    for d, _, _ in visits:
        if d in per_day:
            per_day[d] += 1

    events = {"signed": [], "agree": [], "advance": [], "refuse": [], "first": []}
    people = {}
    zones = {}
    today = [(mid, v) for d, mid, v in visits if d == day]
    for mid, v in today:
        for p in str(v.get("拜访人员") or "").replace("➕", "+").replace("＋", "+").replace("、", "+").split("+"):
            if p.strip():
                people[p.strip()] = people.get(p.strip(), 0) + 1
    seen = set()
    for mid, v in today:
        if mid in seen:
            continue
        seen.add(mid)
        before = [x for d, m, x in visits if m == mid and d < day]
        prev = _visit_stage(before[-1].get("商家状态")) if before else None
        last = [x for m, x in today if m == mid][-1]
        now = _visit_stage(last.get("商家状态"))
        m = info.get(mid, {"brand": str(last.get("商家名称") or mid), "owner": "", "zone": "其他"})
        z = zones.setdefault(m["zone"], {"visits": 0, "signed": 0, "agree": 0})
        z["visits"] += sum(1 for mm, _ in today if mm == mid)
        tag = (m["brand"], str(last.get("拜访人员") or m["owner"]).strip())
        if now == "pending" and prev != "pending":
            events["signed"].append(tag); z["signed"] += 1
        elif now == "agree" and prev != "agree":
            events["agree"].append(tag); z["agree"] += 1
        elif now == "refuse" and prev != "refuse":
            events["refuse"].append(tag)
        elif RANK.get(now, 1) > RANK.get(prev, 1):
            events["advance"].append(tag)
        if not before:
            events["first"].append(tag)
    signed_ids = {mid for mid, v in today if _visit_stage(v.get("商家状态")) == "pending"}
    for c in tables.get(CONTRACT_SHEET, []):
        mid, d = _id(c.get("商家ID")), _date(c.get("合同签署时间"))
        if mid is not None and d and d.date() == day and mid not in signed_ids and "签署" in str(c.get("合同状态") or ""):
            signed_ids.add(mid)
            m = info.get(mid, {"brand": _brand(c.get("商家名称")), "owner": "", "zone": "其他"})
            events["signed"].append((m["brand"], m["owner"]))
            zones.setdefault(m["zone"], {"visits": 0, "signed": 0, "agree": 0})["signed"] += 1

    return {
        "day": day.strftime("%m-%d"), "weekday": "一二三四五六日"[day.weekday()],
        "prev_day": prev_day.strftime("%m-%d") if prev_day else None,
        "visits": len(today), "visits_prev": sum(1 for d, _, _ in visits if d == prev_day) if prev_day else 0,
        "week": [[d.strftime("%m-%d"), per_day[d]] for d in week],
        "events": events, "zones": zones, "undated": undated,
        "people": sorted(people.items(), key=lambda x: -x[1]),
    }


def track_totals(summary, date_str):
    """记录每天最后一次的总盘数字，返回与之前最近一天相比的变化（没有历史时为 None）。"""
    hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {}
    hist[date_str] = {"unsigned": summary["unsigned"], "uplift": summary["uplift"],
                      "agree": summary["counts"]["agree"], "pending": summary["counts"]["pending"]}
    for k in sorted(hist)[:-60]:  # 只留最近 60 天
        hist.pop(k)
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    earlier = [k for k in sorted(hist) if k < date_str]
    if not earlier:
        return None
    base = hist[earlier[-1]]
    return {"since": earlier[-1][5:], **{k: round(hist[date_str][k] - base[k], 1) for k in base}}
