// 飞书事件回调（Cloudflare Pages Functions，地址 https://<项目>.pages.dev/feishu/event）
// 收到 @机器人 或私聊消息时，读取站点里定时生成的 summary.json，回复摘要卡片。
// 需要在 Pages 项目里配置环境变量：FEISHU_APP_ID、FEISHU_APP_SECRET、FEISHU_VERIFICATION_TOKEN

const API = 'https://open.feishu.cn/open-apis';
const ZONES = ['十三沙', '沙河金马', '杭州'];
const STAGES = {pending: '已签待确认', agree: '已同意待签', consider: '沟通考虑中', refuse: '明确拒绝', new: '未首访', pool: '未触达', exit: '已退出'};

let tokenCache = {token: null, exp: 0};
const seen = new Set();

async function tenantToken(env) {
  if (tokenCache.token && Date.now() < tokenCache.exp) return tokenCache.token;
  const r = await fetch(`${API}/auth/v3/tenant_access_token/internal`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({app_id: env.FEISHU_APP_ID, app_secret: env.FEISHU_APP_SECRET}),
  });
  const d = await r.json();
  if (d.code !== 0) throw new Error(`获取 token 失败：${d.msg}`);
  tokenCache = {token: d.tenant_access_token, exp: Date.now() + (d.expire - 300) * 1000};
  return tokenCache.token;
}

const field = (label, value) => ({is_short: true, text: {tag: 'lark_md', content: `**${label}**\n${value}`}});
// 桌面端在飞书窗口内打开网页，而不是跳到系统浏览器
const inFeishu = url => `https://applink.feishu.cn/client/web_url/open?mode=window&url=${encodeURIComponent(url)}`;
const button = (text, url, primary) => ({tag: 'button', type: primary ? 'primary' : 'default', text: {tag: 'plain_text', content: text},
  multi_url: {url, pc_url: inFeishu(url), android_url: url, ios_url: url}});

function buildCard({summary: s, source, read_at}, site) {
  const c = s.counts;
  const zones = ZONES.map(z => `**${z}** 未签 ${s.zones[z].unsigned} 家 · 增量 ${s.zones[z].uplift} 万`).join('　');
  return {
    config: {wide_screen_mode: true},
    header: {template: 'indigo', title: {tag: 'plain_text', content: '抽佣签约驾驶舱 · 实时摘要'}},
    elements: [
      {tag: 'div', text: {tag: 'lark_md', content: `**Top800 未签 ${s.unsigned} 家**，签下后每月多收佣金 **${s.uplift} 万**，9月 GMV 在途 **${s.gmv_unsigned} 万**`}},
      {tag: 'hr'},
      {tag: 'div', fields: [
        field(STAGES.agree, `${c.agree} 家`), field(STAGES.consider, `${c.consider} 家`),
        field(`${STAGES.refuse} / ${STAGES.new} / ${STAGES.pool}`, `${c.refuse} / ${c.new} / ${c.pool} 家`),
        field(STAGES.pending, `${c.pending} 家`), field('近 30 天拜访', `${s.visits_30d} 次`), field(STAGES.exit, `${c.exit} 家`),
      ]},
      {tag: 'hr'},
      {tag: 'div', text: {tag: 'lark_md', content: `**战区（Top800 未签）**\n${zones}`}},
      {tag: 'note', elements: [{tag: 'plain_text', content: `拜访数据截至 ${s.as_of} · 读取于 ${read_at.slice(5)} · 来源：${source}`}]},
      {tag: 'action', actions: [button('打开完整驾驶舱', site + '/', true), ...ZONES.map(z => button(z, `${site}/#zone=${encodeURIComponent(z)}`))]},
    ],
  };
}

async function reply(env, messageId, msgType, content) {
  const r = await fetch(`${API}/im/v1/messages/${messageId}/reply`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', Authorization: `Bearer ${await tenantToken(env)}`},
    body: JSON.stringify({msg_type: msgType, content: JSON.stringify(content)}),
  });
  const d = await r.json();
  if (d.code !== 0) console.log('回复失败', d.code, d.msg);
}

async function answer(env, message, site) {
  try {
    const r = await env.ASSETS.fetch(new Request(`${site}/summary.json`));
    if (!r.ok) throw new Error(`summary.json ${r.status}`);
    await reply(env, message.message_id, 'interactive', buildCard(await r.json(), site));
  } catch (e) {
    console.log('生成卡片失败', e.message);
    await reply(env, message.message_id, 'text', {text: `驾驶舱数据读取失败：${e.message}`});
  }
}

export async function onRequestPost({request, env, waitUntil}) {
  const body = await request.json().catch(() => ({}));
  // 飞书在后台保存「请求地址」时会先发一次校验
  if (body.type === 'url_verification') {
    if (body.token !== env.FEISHU_VERIFICATION_TOKEN) return new Response('forbidden', {status: 403});
    return Response.json({challenge: body.challenge});
  }
  if (body.header?.token !== env.FEISHU_VERIFICATION_TOKEN) return new Response('forbidden', {status: 403});
  // 先立即返回 200 让飞书确认收到（否则会重推），回复放在后台完成；同一事件重推时跳过
  if (body.header.event_type === 'im.message.receive_v1' && !seen.has(body.header.event_id)) {
    seen.add(body.header.event_id);
    if (seen.size > 500) seen.delete(seen.values().next().value);
    waitUntil(answer(env, body.event.message, new URL(request.url).origin));
  }
  return Response.json({ok: true});
}

export const onRequestGet = () => new Response('抽佣驾驶舱机器人事件地址（仅接收飞书推送）');
