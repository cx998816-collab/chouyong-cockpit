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
from summary import STAGES, ZONES, build_summary

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


def build_card(s, source, read_at):
    c = s["counts"]
    head = (f"**Top800 未签 {s['unsigned']} 家**，签下后每月多收佣金 **{s['uplift']} 万**，"
            f"9月 GMV 在途 **{s['gmv_unsigned']} 万**")
    fields = [
        field(STAGES["agree"], f"{c['agree']} 家"),
        field(STAGES["consider"], f"{c['consider']} 家"),
        field(f"{STAGES['refuse']} / {STAGES['new']} / {STAGES['pool']}",
              f"{c['refuse']} / {c['new']} / {c['pool']} 家"),
        field(STAGES["pending"], f"{c['pending']} 家"),
        field("近 30 天拜访", f"{s['visits_30d']} 次"),
        field(STAGES["exit"], f"{c['exit']} 家"),
    ]
    zones = "　".join(f"**{z}** 未签 {s['zones'][z]['unsigned']} 家 · 增量 {s['zones'][z]['uplift']} 万" for z in ZONES)
    url = web_server.public_url() or cfg["DASHBOARD_URL"]

    def button(text, link, primary=False):
        return {"tag": "button", "type": "primary" if primary else "default", "text": {"tag": "plain_text", "content": text},
                "multi_url": {"url": link, "pc_url": open_in_feishu(link), "android_url": link, "ios_url": link}}

    zone_link = (lambda z: f"{url}#zone={quote(z)}") if web_server.public_url() else (lambda z: url)
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "indigo",
                   "title": {"tag": "plain_text", "content": "抽佣签约驾驶舱 · 实时摘要"}},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": head}},
            {"tag": "hr"},
            {"tag": "div", "fields": fields},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**战区（Top800 未签）**\n{zones}"}},
            {"tag": "note", "elements": [{"tag": "plain_text",
             "content": f"拜访数据截至 {s['as_of']} · 读取于 {read_at:%m-%d %H:%M}（每 10 分钟更新）· 来源：{source}"}]},
            {"tag": "action", "actions": [button("打开完整驾驶舱", url, primary=True)]
             + [button(z, zone_link(z)) for z in ZONES]},
        ],
    }


def refresh_loop():
    while True:
        try:
            tables, source = load_tables()
            now = datetime.now()
            _cache["card"] = (build_summary(tables), source, now)  # 卡片在回复时再生成，按钮用当时的网址
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
    web_server.start()
    threading.Thread(target=refresh_loop, daemon=True).start()
    lark.ws.Client(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"],
                   event_handler=handler, log_level=lark.LogLevel.DEBUG if os.environ.get("DEBUG") else lark.LogLevel.INFO).start()
