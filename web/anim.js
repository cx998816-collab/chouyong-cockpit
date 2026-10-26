// 驾驶舱动态效果：数字滚动、滚动进场、图表展开。系统开启「减少动态效果」时全部关闭。
(() => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const css = `
  .bx-rv{opacity:0;transform:translateY(18px);transition:opacity .6s cubic-bezier(.2,.8,.2,1),transform .6s cubic-bezier(.2,.8,.2,1);transition-delay:var(--d,0ms)}
  .bx-rv.bx-in{opacity:1;transform:none}
  .bx-in svg,.bx-in .bx-track{animation:bx-wipe .9s cubic-bezier(.2,.8,.2,1) both;animation-delay:calc(var(--d,0ms) + 120ms)}
  @keyframes bx-wipe{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
  .bx-hero{background-size:200% 200%!important;animation:bx-sky 14s ease-in-out infinite alternate}
  @keyframes bx-sky{from{background-position:0% 40%}to{background-position:100% 60%}}
  .bx-ring-svg{animation:bx-pop .9s cubic-bezier(.2,.8,.2,1) both .2s}
  @keyframes bx-pop{from{opacity:0;transform:scale(.82) rotate(-20deg)}to{opacity:1;transform:none}}
  .bx-kpi,.bx-card,.bx-ask,.bx-dc,.bx-col{transition:transform .25s ease,box-shadow .25s ease}
  .bx-kpi:hover,.bx-ask:hover,.bx-dc:hover{transform:translateY(-3px);box-shadow:0 10px 28px rgba(16,24,40,.12)}
  .bx-kpi::before{animation:bx-grow 1s cubic-bezier(.2,.8,.2,1) both .3s;transform-origin:top}
  @keyframes bx-grow{from{transform:scaleY(0)}to{transform:none}}
  .bx-flash{animation:bx-flash .9s ease}
  @keyframes bx-flash{0%{color:var(--bx-gold)}100%{}}
  .bx-live{display:inline-block;width:7px;height:7px;border-radius:50%;background:#55B898;margin-right:6px;vertical-align:1px;box-shadow:0 0 0 0 rgba(85,184,152,.6);animation:bx-ping 2s infinite}
  @keyframes bx-ping{70%{box-shadow:0 0 0 8px rgba(85,184,152,0)}100%{box-shadow:0 0 0 0 rgba(85,184,152,0)}}
  .bx-hit{transition:background .2s,opacity .3s}
  `;
  document.head.appendChild(Object.assign(document.createElement('style'), {textContent: css}));

  // 实时小绿点
  const eb = document.querySelector('.bx-eyebrow');
  if (eb) eb.prepend(Object.assign(document.createElement('span'), {className: 'bx-live'}));

  // 滚动进场：同一行的卡片依次错开出现
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('bx-in'); io.unobserve(e.target); }
  }), {threshold: .12});
  const reveal = () => document.querySelectorAll('.bx-kpi,.bx-card,.bx-ask,.bx-col,.bx-sec,.bx-band,.bx-alert,.bx-dc,.bx-dhead')
    .forEach(n => {
      if (n.classList.contains('bx-rv')) return;
      const sib = [...n.parentElement.children].filter(c => c.classList.contains(n.classList[0]));
      n.style.setProperty('--d', Math.min(sib.indexOf(n), 6) * 80 + 'ms');
      n.classList.add('bx-rv'); io.observe(n);
    });

  // 数字滚动：按数字所在元素记状态，页面重绘换掉文本节点也能接着从旧值滚到新值
  const NUM = /\d[\d,]*(\.\d+)?/;
  const st = new WeakMap(); // 元素 → {val: 上次的终值, mine: 动画写入的文本, raf}
  const fmt = (v, src) => {
    const dec = (src.split('.')[1] || '').length;
    return src.includes(',') ? v.toLocaleString('en-US', {minimumFractionDigits: dec, maximumFractionDigits: dec}) : v.toFixed(dec);
  };
  const firstNum = h => {
    const w = document.createTreeWalker(h, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) { const m = w.currentNode.nodeValue.match(NUM); if (m) return [w.currentNode, m[0]]; }
    return [];
  };
  // 下一帧：优先 requestAnimationFrame，页面在后台不刷新时用定时器兜底，保证数字最终落到真实值
  const tick = f => { let done = false; const g = () => { if (!done) { done = true; f(performance.now()); } };
    requestAnimationFrame(g); setTimeout(g, 50); };
  const roll = h => {
    const s = st.get(h) || {val: 0, run: 0};
    if (h.textContent === s.mine) return; // 动画自己写的，忽略
    const [node, raw] = firstNum(h);
    if (!node) return;
    const to = parseFloat(raw.replace(/,/g, ''));
    st.set(h, s);
    // 目标值没变（页面连续重绘同一结果）：正在跑的动画改写到新文本节点上继续
    if (to === s.val) { if (s.active) Object.assign(s, {node, raw, txt: node.nodeValue}); return; }
    const from = s.active ? s.cur : s.val, run = ++s.run, t0 = performance.now(), dur = 900;
    Object.assign(s, {val: to, node, raw, txt: node.nodeValue, active: true, cur: from});
    h.classList.remove('bx-flash');
    const step = now => {
      if (run !== s.run) return; // 已被新一轮重绘取代
      const k = Math.min((now - t0) / dur, 1), e = 1 - Math.pow(1 - k, 3);
      s.cur = from + (to - from) * e;
      s.node.nodeValue = k < 1 ? s.txt.replace(s.raw, fmt(s.cur, s.raw)) : s.txt;
      s.mine = h.textContent;
      if (k >= 1) s.active = false;
      if (k < 1) tick(step);
      else { void h.offsetWidth; h.classList.add('bx-flash'); }
    };
    tick(step);
  };
  const SEL = '.bx-kv,.bx-dc .v,.bx-ring-t .big,.bx-ask .nums b';
  const scan = () => document.querySelectorAll(SEL).forEach(roll);
  new MutationObserver(() => { reveal(); scan(); })
    .observe(document.querySelector('.bx') || document.body, {subtree: true, childList: true, characterData: true});
  reveal(); scan();
})();
