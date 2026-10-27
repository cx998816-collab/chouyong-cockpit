"""抽佣驾驶舱机器人：群里 @机器人 或私聊发消息时，回复摘要卡片；同时提供驾驶舱网页。

整表读取约需两分钟，所以后台每 10 分钟预先读一次，同时更新卡片数据和网页数据，收到消息时直接用最近一次的结果回复。
用法：python bot.py（保持窗口运行；使用飞书长连接，不需要公网 IP）
"""
import json
import os
import threading
import time
from datetime import datetime
from urllib.parse import quote

import lark_oapi as lark
from lark_oapi.api.im.v1 import (P2ImMessageReceiveV1, ReplyMessageRequest,
                                 ReplyMessageRequestBody)

import cockpit_data
import web_server
from feishu_sheet import FeishuSheet, load_config, xlsx_tables
from daily import build_daily, track_totals
from summary import ZONES, build_summary

cfg = load_config()
sheet_api = FeishuSheet(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])
client = lark.Client.builder().app_id(cfg["FEISHU_APP_ID"]).app_secret(cfg["FEISHU_APP_SECRET"]).build()

_cache = {"card": None, "error": None}
REFRESH_SECONDS = 600


def load_tables():
    if cfg.get("LOCAL_XLSX"):  # 测试用：读本地导出的 Excel，而不是知识库表格
        return xlsx_tables(cfg["LOCAL_XLSX"], cockpit_data.SHEETS), "本地 Excel"
    token = sheet_api.spreadsheet_token(cfg["WIKI_TOKEN"])
    return sheet_api.tables(token, cockpit_data.SHEETS), "知识库表格"


def open_in_feishu(url):
    """飞书内打开网页的 applink（桌面端在飞书窗口内打开，而非系统浏览器）。"""
    return f"https://applink.feishu.cn/client/web_url/open?mode=window&url={quote(url, safe='')}"


def field(label, value):
    return {"is_short": True, "text": {"tag": "lark_md", "content": f"**{label}**\n{value}"}}


SPARK = "▁▂▃▄▅▆▇█"


def _names(items, limit=6):
    """[(商家, 拜访人)] → 「ALLIN、SEMICOLONS（石头）」，按拜访人归组，太多时截断。"""
    if not items:
        return "—"
    groups = {}
    for brand, who in items:
        groups.setdefault(who or "—", []).append(brand)
    parts, shown = [], 0
    for who, brands in groups.items():
        take = brands[:max(limit - shown, 0)]
        if take:
            parts.append(f"{'、'.join(take)}（{who}）")
            shown += len(take)
    more = len(items) - shown
    return "；".join(parts) + (f" 等 {len(items)} 家" if more > 0 else "")


def _delta(v, unit="", good_down=False):
    """较前一日的变化，绿色为向好、红色为变差。"""
    if not v:
        return "（持平）"
    up = v > 0
    color = "green" if (v < 0) == good_down else "red"
    return f"（<font color='{color}'>{'+' if up else ''}{v:g}{unit}</font>）"


def build_card(s, d, delta, source, read_at):
    c = s["counts"]
    url = web_server.public_url() or cfg["DASHBOARD_URL"]
    elements = []
    if d:
        ev = d["events"]
        chg = d["visits"] - d["visits_prev"]
        vs = f"（较 {d['prev_day']} {'+' if chg >= 0 else ''}{chg}）" if d["prev_day"] else ""
        elements += [
            {"tag": "div", "text": {"tag": "lark_md", "content":
                f"**{d['day']}（周{d['weekday']}）拜访 {d['visits']} 次**{vs}\n"
                f"新签约 **{len(ev['signed'])}** · 新同意 **{len(ev['agree'])}** · 阶段推进 **{len(ev['advance'])}** · "
                f"新增拒绝 **{len(ev['refuse'])}** · 首访 **{len(ev['first'])}**"}},
            {"tag": "div", "text": {"tag": "lark_md", "content":
                f"🎉 **新签约**：{_names(ev['signed'])}\n"
                f"✅ **新同意**：{_names(ev['agree'])}\n"
                f"📈 **阶段推进**：{_names(ev['advance'])}\n"
                f"⚠️ **新增拒绝**：{_names(ev['refuse'])}"}},
            {"tag": "div", "fields": [field(z, f"拜访 {d['zones'].get(z, {}).get('visits', 0)} · 签约 "
                                               f"{d['zones'].get(z, {}).get('signed', 0)} · 同意 {d['zones'].get(z, {}).get('agree', 0)}")
                                      for z in ZONES]},
        ]
        top = max([n for _, n in d["week"]] + [1])
        spark = "".join(SPARK[min(7, round(n / top * 7))] for _, n in d["week"])
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content":
            f"**当日拜访人**：{' · '.join(f'{p} {n}' for p, n in d['people'][:8]) or '—'}\n"
            f"**近 7 天拜访** {spark}　{' / '.join(str(n) for _, n in d['week'])}（{d['week'][0][0]}~{d['week'][-1][0]}）"
            + (f"\n<font color='orange'>另有 {len(d['undated'])} 条拜访没填「拜访时间」，没算进上面：{_names(d['undated'])}</font>"
               if d.get("undated") else "")}})
    else:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "表格里还没有拜访记录。"}})
    dl = delta or {}
    since = f"较 {dl['since']}" if delta else "明日起显示较前一日变化"
    elements += [
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content":
            f"**总盘（Top800）**　{since}\n"
            f"未签 **{s['unsigned']}** 家{_delta(dl.get('unsigned'), good_down=True) if delta else ''} · "
            f"待收增量 **{s['uplift']}** 万/月{_delta(dl.get('uplift'), good_down=True) if delta else ''} · "
            f"已同意待签 **{c['agree']}**{_delta(dl.get('agree')) if delta else ''} · "
            f"已签待确认 **{c['pending']}**{_delta(dl.get('pending')) if delta else ''}"}},
        {"tag": "note", "elements": [{"tag": "plain_text", "content":
            f"拜访数据截至 {s['as_of']}" + ("（之后的拜访尚未录入表格）" if s['as_of'] < f"{read_at:%m-%d}" else "")
            + f" · 读取于 {read_at:%m-%d %H:%M} · 来源：{source}"}]},
    ]

    def button(text, link, primary=False):
        return {"tag": "button", "type": "primary" if primary else "default", "text": {"tag": "plain_text", "content": text},
                "multi_url": {"url": link, "pc_url": open_in_feishu(link), "android_url": link, "ios_url": link}}

    zone_link = (lambda z: f"{url}#zone={quote(z)}") if web_server.public_url() else (lambda z: url)
    elements.append({"tag": "action", "actions": [button("打开完整驾驶舱", url, primary=True)]
                     + [button(z, zone_link(z)) for z in ZONES]})
    signed_today = d and d["events"]["signed"]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "green" if signed_today else "indigo",
                   "title": {"tag": "plain_text", "content": f"抽佣签约 · 每日战报｜{d['day']}" if d else "抽佣签约 · 每日战报"}},
        "elements": elements,
    }


def refresh_loop():
    while True:
        try:
            tables, source = load_tables()
            now = datetime.now()
            s = build_summary(tables)
            # 卡片在回复时再生成，按钮用当时的网址
            _cache["card"] = (s, build_daily(tables), track_totals(s, f"{now:%Y-%m-%d}"), source, now)
            web_server.write_data(cockpit_data.build(tables, now))
            _cache["error"] = None
            web_server.write_health(ok=True, source=source, rows={k: len(v) for k, v in tables.items()})
            lark.logger.info("驾驶舱数据已刷新")
        except Exception as e:  # 刷新失败时保留上一次的卡片
            _cache["error"] = e
            web_server.write_health(ok=False, error=str(e))
            lark.logger.exception("刷新驾驶舱数据失败")
        time.sleep(REFRESH_SECONDS)


def reply(message_id, msg_type, content):
    req = ReplyMessageRequest.builder().message_id(message_id).request_body(
        ReplyMessageRequestBody.builder().msg_type(msg_type).content(json.dumps(content, ensure_ascii=False)).build()
    ).build()
    resp = client.im.v1.message.reply(req)
    if not resp.success():
        lark.logger.error(f"回复失败 code={resp.code} msg={resp.msg}")


_seen = set()


def on_message(data: P2ImMessageReceiveV1) -> None:
    msg = data.event.message
    # 处理慢了飞书会重推同一条消息，按 message_id 去重
    if msg.message_id in _seen:
        return
    _seen.add(msg.message_id)
    lark.logger.info(f"收到消息 chat_type={msg.chat_type} message_id={msg.message_id}")
    # 立即返回让飞书确认收到，回复放到后台线程里发
    threading.Thread(target=answer, args=(msg,), daemon=True).start()


def answer(msg):
    # 群聊里只有 @机器人 的消息会推送过来（权限决定），私聊任意消息都回复
    if _cache["card"]:
        reply(msg.message_id, "interactive", build_card(*_cache["card"]))
    elif _cache["error"]:  # 读表失败时告诉用户，而不是没反应
        reply(msg.message_id, "text", {"text": f"驾驶舱数据读取失败：{_cache['error']}"})
    else:
        reply(msg.message_id, "text", {"text": "驾驶舱数据正在加载，大约需要 1 分钟，请稍后再发一次。"})


handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(on_message).build()

if __name__ == "__main__":
    web_server.start(cfg.get("PUBLIC_URL"))  # 服务器上填 PUBLIC_URL=http://<公网IP>，本机留空则走隧道
    threading.Thread(target=refresh_loop, daemon=True).start()
    lark.ws.Client(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"],
                   event_handler=handler, log_level=lark.LogLevel.DEBUG if os.environ.get("DEBUG") else lark.LogLevel.INFO).start()
