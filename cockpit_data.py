"""从签约进度表生成驾驶舱网页数据（merchants / signed / visits / summary），口径同驾驶舱页脚。

输入是表名 → 记录列表（[{表头: 值}]），用到四张表：总未签约明细、拜访记录明细、商家名单总表、签约商家。
"""
import re
from datetime import datetime

from summary import STAGES, UNSIGNED_SHEET, VISIT_SHEET, _date, _id, _num, merchant_stages

ALL_SHEET = "商家名单总表"
CONTRACT_SHEET = "签约商家"
TOP300_SHEET = "top300未签约"  # 市场标签、未签约原因
SHEETS = [UNSIGNED_SHEET, VISIT_SHEET, ALL_SHEET, CONTRACT_SHEET, TOP300_SHEET]

REGION = {"广州": "华南", "深圳": "华南", "东莞": "华南", "杭州": "华东", "濮院": "华东", "海宁": "华东",
          "上海": "华东", "青岛": "华北", "北京": "华北"}
TOP300 = {"top100", "top101–200", "top201–300"}
# 卡点：按反馈文字关键词归类，一家可有多个；文字取自以下列 + 该商家所有拜访记录与未签约原因
BLOCKER_FIELDS = ("拜访记录", "谈判空间-供给")
BLOCKER_TOP300_FIELDS = ("原因分类",)
BLOCKERS = [
    ("税务", ("税", "营业执照", "发票", "开票")),
    ("利润", ("利润", "点位", "佣金", "抽佣", "成本", "扣点", "点数", "赚")),
    ("老板决策", ("老板", "汇报", "合伙人", "商量", "考虑", "决定", "股东")),
    ("退出风险", ("退出", "不合作", "不做", "暂停", "撤", "关店", "倒闭")),
    ("平台机制", ("平台", "规则", "机制", "流量", "罚", "治理", "位置", "大会")),
    ("增长乏力", ("下滑", "增长", "业绩差", "没量", "销量", "生意不好")),
]


def _s(v):
    s = "" if v is None else str(v).strip()
    return "" if s.startswith("#") and s.isupper() or s in ("#N/A", "#VALUE!", "#REF!") else s


def _tier(v):
    """top101-top200 → top101–200，与驾驶舱筛选项一致。"""
    s = _s(v)
    m = re.fullmatch(r"top(\d+)-top(\d+)", s)
    return f"top{m.group(1)}–{m.group(2)}" if m else s


def _w(v, nd=1):
    """元 → 万元。"""
    return round(_num(v) / 1e4, nd)


def _pct(v):
    return round(_num(v) * 100, 1) if _s(v) else 0.0


def _split(name):
    name = _s(name)
    if "-" in name:
        stall, brand = name.rsplit("-", 1)
        return (stall.strip(), brand.strip()) if brand.strip() else (stall.strip(), name)
    return "", name


def _ymd(v):
    d = _date(v)
    return d.strftime("%Y-%m-%d") if d else ""


def _blockers(text):
    return "、".join(k for k, words in BLOCKERS if any(w in text for w in words))


def _form(v):
    s = _s(v)
    return "线上拜访" if s.startswith("线上") else s


def build(tables, today=None):
    unsigned, visits_raw = tables[UNSIGNED_SHEET], tables[VISIT_SHEET]
    all_rows, contracts = tables[ALL_SHEET], tables[CONTRACT_SHEET]
    top300 = {_id(r.get("商家ID")): r for r in tables[TOP300_SHEET]}

    # 拜访：按日期排序后编号，按商家归集
    visits = []
    for v in visits_raw:
        mid = _id(v.get("商家id"))
        if mid is None or not _ymd(v.get("拜访时间")):  # 没填日期的拜访无法归到某一天，网页图表也画不了
            continue
        person = _s(v.get("拜访人员"))
        visits.append({"id": mid, "date": _ymd(v.get("拜访时间")), "person": person,
                       "people": re.sub(r"[+➕]", "、", person),
                       "form": _form(v.get("拜访形式")), "topic": _s(v.get("谈判类型")),
                       "result": _s(v.get("商家状态")), "reason": _s(v.get("未签约原因")),
                       "note": _s(v.get("拜访记录"))})
    visits.sort(key=lambda r: r["date"] or "9999")
    by_mid = {}
    for i, r in enumerate(visits, 1):
        r["vid"] = i
        by_mid.setdefault(r["id"], []).append(r)

    pool = {}
    merchants = []
    for m, stage in merchant_stages(unsigned, visits_raw):
        mid = _id(m.get("商家ID"))
        stall, brand = _split(m.get("商家"))
        tier = _tier(m.get("商家分层"))
        city = _s(m.get("城市"))
        vs = [r for r in by_mid.get(mid, []) if r["date"]]
        last = vs[-1] if vs else None
        t3 = top300.get(mid, {})
        notes = " ".join([_s(m.get(k)) for k in BLOCKER_FIELDS] + [_s(t3.get(k)) for k in BLOCKER_TOP300_FIELDS]
                         + [r["note"] + " " + r["reason"] for r in vs])
        cur, nxt = _pct(m.get("当前抽佣比例")), _pct(m.get("后续抽佣比例"))
        gmv_sep = _w(m.get("9月销售额"))
        prog = _s(m.get("谈判完成度"))
        rec = {
            "id": mid, "name": _s(m.get("商家")), "brand": brand, "stall": stall, "tier": tier,
            "top300": tier in TOP300, "owner": _s(m.get("商务人员名单")), "city": city,
            "region": REGION.get(city, "其他"), "market": _s(m.get("大市场")), "sub_market": _s(m.get("一级市场")),
            "group": _s(m.get("业绩归属")), "attr": _s(m.get("商家属性")) or "未标注",
            "status": _s(m.get("商家状态")), "type": _s(m.get("商家类型")),
            "stage": stage, "stage_label": STAGES[stage],
            "progress": round(_num(prog) * 100) if prog else None,
            "cur_rate": cur, "next_rate": nxt, "uplift": round(max(nxt - cur, 0) / 100 * gmv_sep, 2),
            "supply_view": _s(m.get("谈判空间-供给")), "est_month": _s(m.get("预估谈判时间")),
            "batch": _s(m.get("谈判空间-招商")), "label": " ".join(_s(t3.get("市场标签")).split()), "buyer": _s(m.get("买手")),
            "gmv_may": _w(m.get("5月销售额")), "gmv_jun": _w(m.get("6月销售额")), "gmv_jul": _w(m.get("7月销售额")),
            "gmv_aug": _w(m.get("8月销售额")), "gmv_sep": gmv_sep,
            "gmv_2025": _w(m.get("25年业绩")), "gmv_2026": _w(m.get("26年累计")),
            "blockers": _blockers(notes), "visits": len(vs),
            "last_visit": last["date"] if last else "", "last_result": last["result"] if last else "",
            "last_by": last["person"] if last else "",
            "latest_note": _s(m.get("拜访记录")) or (last["note"] if last else "") or _s(m.get("拜访说明")),
        }
        pool[mid] = rec
        merchants.append(rec)

    for r in visits:
        p = pool.get(r["id"])
        r.update(name=p["name"] if p else "", tier=p["tier"] if p else "", market=p["market"] if p else "",
                 in_pool=bool(p))

    # 已签：商家名单总表中不在未签池的商家；签约日期优先取拜访登记「已签约」，其次合同签署时间
    sign_visit = {}
    for r in visits:
        if ("已签约" in r["result"] or "转合同" in r["result"]) and r["date"]:
            sign_visit.setdefault(r["id"], r["date"])
    sign_contract = {}
    for c in contracts:
        mid, d = _id(c.get("商家ID")), _ymd(c.get("合同签署时间"))
        if mid is not None and d and "签署" in _s(c.get("合同状态")):
            sign_contract[mid] = min(d, sign_contract.get(mid, d))
    signed = []
    for a in all_rows:
        mid = _id(a.get("商家ID"))
        if mid is None or mid in pool:
            continue
        stall, brand = _split(a.get("商家"))
        tier, city = _tier(a.get("商家分层")), _s(a.get("城市"))
        date, src = (sign_visit[mid], "拜访登记") if mid in sign_visit else \
            (sign_contract[mid], "合同") if mid in sign_contract else ("", "早前已签")
        signed.append({"id": mid, "name": _s(a.get("商家")), "brand": brand, "tier": tier, "top300": tier in TOP300,
                       "owner": _s(a.get("商务")) or "招商全体", "city": city, "region": REGION.get(city, "其他"),
                       "market": _s(a.get("大市场")), "group": _s(a.get("业绩归属")),
                       "gmv_sep": _w(a.get("9月销售额")), "gmv_2026": _w(a.get("26年累计")),
                       "sign_date": date, "sign_src": src})

    dates = [r["date"] for r in visits if r["date"]]
    return {"merchants": merchants, "signed": signed, "visits": visits,
            "summary": [{"as_of": max(dates) if dates else "", "top300_total": sum(1 for x in merchants if x["top300"])
                         + sum(1 for x in signed if x["top300"]), "pool_note": UNSIGNED_SHEET,
                         "built_at": (today or datetime.now()).strftime("%Y-%m-%d %H:%M")}]}
