// ─── 工具 ───
const $=(s,q=document)=>q.querySelector(s);
const $$=(s,q=document)=>[...q.querySelectorAll(s)];
const esc=t=>{if(!t)return'';const d=document.createElement('div');d.textContent=t;return d.innerHTML};
const api=p=>fetch(p).then(r=>r.json());

// ─── 路由 ───
let curPage='';
function nav(p){
  curPage=p||'';
  history.replaceState(null,'','#/'+curPage);
  $$('.sb-nav a').forEach(a=>a.classList.toggle('act',a.dataset.pg===curPage));
  render(curPage);
}

// 初始化
window.addEventListener('hashchange',()=>{
  const p=location.hash.replace('#/','').split('?')[0];
  if(p!==curPage)nav(p);
});
document.addEventListener('DOMContentLoaded',()=>{
  const p=location.hash.replace('#/','').split('?')[0];
  nav(p||'');
});

// ─── 页面渲染 ───
async function render(pg){
  const m=$('#main');
  if(pg==='library')renderLib(m);
  else if(pg==='chat')renderChat(m);
  else if(pg==='config')renderConfig(m);
  else renderHome(m);
}

// ─── 能力检测 ───
function detect(s){
  const l=s.toLowerCase();
  if(/(embedding|embed)/.test(l))return'embedding';
  if(/(reranker|rerank|bge)/.test(l))return'reranker';
  if(/(vision|vl|mmproj)/.test(l))return'vision';
  return'chat';
}
const capLbl={chat:'💬对话',vision:'🖼️视觉',embedding:'📊嵌入',reranker:'📊排序'};
const capClr={chat:'var(--green)',vision:'var(--accent)',embedding:'var(--purple)',reranker:'var(--yellow)'};
const capCls={chat:'tag-g',vision:'tag-b',embedding:'tag-p',reranker:'tag-y'};

// ─── 首页 ───
async function renderHome(el){
  el.innerHTML='<div class="loading"><div class="spin"></div><p>加载仪表盘...</p></div>';
  try{
    let [mod,sys,svc]=await Promise.all([api('/api/models'),api('/api/system'),api('/api/services')]);
    const models=mod.data||mod.models||[];
    const ok=models.filter(m=>m.online).length;
    const chatMod=models.filter(m=>detect(m.name+' '+m.model_id)=='chat'||detect(m.name+' '+m.model_id)=='vision');

    const mem=sys.memory||{};
    const memPct=mem.total?Math.round(parseInt(mem.used)/parseInt(mem.total)*100):0;
    const g0=sys.gpu?.[0]||{};
    const gvr_free=g0.vram_total?parseInt(g0.vram_total.replace(/[^0-9]/g,''))-parseInt((g0.vram_used||'0').replace(/[^0-9]/g,'')):0;
    const disk=sys.disk||{};
    const cpul=sys.cpu?.load?.slice(0,3).join(' ')||'?';
    const cpuPct=sys.cpu?.cores?Math.round((parseFloat(sys.cpu.load?.[0]||0)/parseInt(sys.cpu.cores)*100)):0;

    let h=`
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <h1 style="font-size:22px">仪表盘</h1>
      <button class="btn" onclick="refreshHome()">⟳ 刷新</button>
    </div>
    <div class="cards">
      <div class="card"><div class="n" style="color:var(--green)">${ok}</div><div class="l">在线模型</div></div>
      <div class="card"><div class="n" style="color:var(--dim)">${models.length-ok}</div><div class="l">离线模型</div></div>
      <div class="card"><div class="n">${chatMod.length}</div><div class="l">可对话模型</div></div>
      <div class="card"><div class="n">${models.length}</div><div class="l">总计</div></div>
    </div>
    <div class="sys-grid">
      <div class="sys-box">
        <h3>🧠 CPU (${sys.cpu?.cores||'?'}核)</h3>
        <div class="v">负载 ${cpul}</div>
        <div class="bar"><div class="bar-f" style="width:${cpuPct}%;background:var(--accent)"></div></div>
        <div class="sub">${cpuPct}%</div>
      </div>
      <div class="sys-box">
        <h3>💾 内存</h3>
        <div class="v">${(mem.used/1024).toFixed(1)||'?'} / ${(mem.total/1024).toFixed(1)||'?'} GB</div>
        <div class="bar"><div class="bar-f" style="width:${memPct}%;background:var(--green)"></div></div>
        <div class="sub">${memPct}% · 空闲 ${(mem.free/1024).toFixed(1)} GB</div>
      </div>
      <div class="sys-box">
        <h3>🎮 GPU ${g0.name?'— '+esc(g0.name):''}</h3>
        <div class="v">${g0.vram_used||'?'} / ${g0.vram_total||'?'}</div>
        <div class="bar"><div class="bar-f" style="width:${g0.vram_total?Math.round(gvr_free/(parseInt(g0.vram_total.replace(/[^0-9]/g,'')))*100):0}%;background:var(--purple)"></div></div>
        <div class="sub">利用率 ${g0.util||'?'}</div>
      </div>
      <div class="sys-box">
        <h3>💽 磁盘</h3>
        <div class="v">${disk.used||'?'} / ${disk.total||'?'}</div>
        <div class="bar"><div class="bar-f" style="width:${parseInt(disk['use%']||0)}%;background:var(--orange)"></div></div>
        <div class="sub">可用 ${disk.avail||'?'} · 已用 ${disk['use%']||'?'}</div>
      </div>
    </div>
    <h3 style="font-size:13px;color:var(--dim);margin-bottom:8px;font-weight:600">🔧 本地服务</h3>
    <div class="svc-wrap">${svc.map(s=>`<span class="svc"><span class="dot" style="background:${s.active?'var(--green)':'var(--red)'}"></span>${esc(s.name)}<span style="color:var(--dim)">:${s.port}</span>${s.has_mmproj?'<span style="color:var(--accent)">🖼️</span>':''}</span>`).join('')}</div>
    <h3 style="font-size:13px;color:var(--dim);margin-bottom:8px;font-weight:600">📋 模型一览</h3>
    <div class="lib-grid">${models.map(m=>{
      const c=detect(m.name+' '+m.model_id+' '+m.description);
      return `<div class="mc">
        <div class="mc-t">
          <div class="mc-n">${esc(m.name)} <span class="tag ${capCls[c]}">${capLbl[c]}</span></div>
          <span style="font-size:11px;color:var(--dim)">${m.provider}</span>
        </div>
        <div class="mc-sub">${esc(m.real_name)||''}</div>
        <div class="mc-info">🌡${m.temperature||'?'} · 📏${m.max_tokens||'?'} · <span style="color:${m.online?'var(--green)':'var(--red)'}">${m.online?'🟢 在线':'🔴 离线'}</span></div>
        <div class="mc-acts">${(c==='chat'||c==='vision')?`<a class="btn btn-p" href="#/chat?model=${encodeURIComponent(m.name)}">💬 对话</a>`:''}<button class="btn" onclick="testMod('${esc(m.name)}',this)">⟳ 测试</button></div>
      </div>`;
    }).join('')}</div>`;
    el.innerHTML=h;
  }catch(e){
    el.innerHTML=`<div style="padding:40px;text-align:center;color:var(--red)">⚠️ 加载失败: ${esc(e.message)}</div>`;
  }
}

async function refreshHome(){renderHome($('#main'))}

async function testMod(n,btn){
  btn.disabled=true;btn.textContent='...';
  const d=await api('/api/check/'+encodeURIComponent(n));
  btn.disabled=false;btn.textContent='⟳ 测试';
  alert(d.online?'🟢 在线 ('+(d.latency_ms||'?')+'ms)':'🔴 离线: '+(d.error||'未知'));
}

// ─── 模型库 ───
async function renderLib(el){
  el.innerHTML='<div class="loading"><div class="spin"></div><p>加载模型库...</p></div>';
  try{
    const lib=await api('/api/models/library');
    let h='<h1 style="font-size:22px;margin-bottom:8px">📚 模型库</h1>';

    // 可对话
    h+='<div class="lib-sec"><div class="lib-hdr">💬 可对话模型</div><div class="lib-grid">';
    for(const sub of ['local','cloud']){
      for(const m of lib.chat[sub]){
        const c=detect(m.name+' '+m.model_id);
        h+=`<div class="mc">
          <div class="mc-t">
            <div class="mc-n">${esc(m.name)} <span class="tag ${capCls[c]}">${capLbl[c]}</span></div>
            <span class="loc-t ${sub==='local'?'loc-l':'loc-c'}">${sub==='local'?'📍 本地':'☁️ 云'}</span>
          </div>
          <div class="mc-sub">${esc(m.real_name)} · ${esc(m.provider)}</div>
          <div class="mc-info">🌡${m.temperature||'?'} · 📏${m.max_tokens||'?'}</div>
          <div class="mc-acts"><a class="btn btn-p" href="#/chat?model=${encodeURIComponent(m.name)}">💬 对话</a></div>
        </div>`;
      }
    }
    h+='</div></div>';

    // 功能
    h+='<div class="lib-sec"><div class="lib-hdr">🔧 功能模型</div><div class="lib-grid">';
    for(const sub of ['local','cloud']){
      for(const m of lib.function[sub]){
        const c=detect(m.name+' '+m.model_id);
        h+=`<div class="mc">
          <div class="mc-t">
            <div class="mc-n">${esc(m.name)} <span class="tag ${capCls[c]}">${capLbl[c]}</span></div>
            <span class="loc-t ${sub==='local'?'loc-l':'loc-c'}">${sub==='local'?'📍 本地':'☁️ 云'}</span>
          </div>
          <div class="mc-sub">${esc(m.real_name)}</div>
          <div class="mc-info">${esc(m.description)||''}</div>
          <div class="mc-acts"><button class="btn" onclick="testMod('${esc(m.name)}',this)">⟳ 测试</button></div>
        </div>`;
      }
    }
    h+='</div></div>';

    el.innerHTML=h;
  }catch(e){
    el.innerHTML=`<div style="padding:40px;text-align:center;color:var(--red)">⚠️ 加载失败: ${esc(e.message)}</div>`;
  }
}

// ─── 对话 ───
let chatMod='',chatMsgs=[],chatSending=false;

async function renderChat(el){
  const p=new URLSearchParams(location.hash.split('?')[1]||'');
  const preset=p.get('model')||'';

  try{
    const mods=await api('/api/models');
    const models=(mods.data||mods.models||[]).filter(m=>{
      const c=detect(m.name+' '+m.model_id);return c==='chat'||c==='vision';
    });
    if(!chatMod||!models.find(x=>x.name===chatMod))chatMod=models[0]?.name||'';
    if(preset)chatMod=preset;

    el.innerHTML=`
    <div class="chat-wrap">
      <div class="chat-top">
        <select onchange="switchMod(this.value)">${models.map(x=>`<option value="${esc(x.name)}" ${x.name===chatMod?'selected':''}>${esc(x.name)}${x.provider==='llamacpp'?' (本地)':''}</option>`).join('')}</select>
        <span class="chat-stat" id="chat-stat">检测中...</span>
        <button class="btn" onclick="clearChat()" style="margin-left:auto">🗑 清除</button>
      </div>
      <div class="chat-msgs" id="chat-msgs">
        ${chatMsgs.length?chatMsgs.map(m=>msgHtml(m)).join(''):'<div class="empty-chat"><div class="big">💬</div><p>选择模型开始对话</p><p class="sub">输入消息并按 Enter 发送</p></div>'}
      </div>
      <div class="chat-inp">
        <textarea id="chat-inp" placeholder="输入消息..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMsg()}" rows="1"></textarea>
        <button id="chat-btn" onclick="sendMsg()">发送</button>
      </div>
    </div>`;

    updateStat();
    setTimeout(()=>$('#chat-inp')?.focus(),100);
    autoH();
  }catch(e){
    el.innerHTML=`<div style="padding:40px;text-align:center;color:var(--red)">⚠️ 加载失败: ${esc(e.message)}</div>`;
  }
}

function autoH(){
  const t=$('#chat-inp');
  if(!t)return;
  t.addEventListener('input',()=>{t.style.height='auto';t.style.height=Math.min(t.scrollHeight,120)+'px'});
}

function msgHtml(m){
  const r=m.role||'user';
  const content=esc(m.content);
  return `<div class="msg ${r==='user'?'u':'a'}"><div class="av">${r==='user'?'你':'N'}</div><div class="b">${content||(m.streaming?'...':'')}</div></div>`;
}

async function updateStat(){
  const el=$('#chat-stat');
  if(!el||!chatMod)return;
  try{
    const d=await api('/api/check/'+encodeURIComponent(chatMod));
    el.className='chat-stat '+(d.online?'on':'off');
    el.textContent=d.online?'🟢 在线 '+(d.latency_ms||'')+'ms':'🔴 '+(d.error||'离线');
  }catch(e){el.textContent='🔴 检测失败'}
}

function switchMod(n){
  chatMod=n;
  updateStat();
  setTimeout(()=>$('#chat-inp')?.focus(),100);
}

function clearChat(){
  chatMsgs=[];
  const el=$('#chat-msgs');
  if(el)el.innerHTML='<div class="empty-chat"><div class="big">💬</div><p>对话已清除</p></div>';
}

async function sendMsg(){
  const inp=$('#chat-inp');
  const btn=$('#chat-btn');
  const msgs=$('#chat-msgs');
  const text=inp.value.trim();
  if(!text||!chatMod||chatSending)return;

  inp.value='';inp.style.height='44px';
  chatSending=true;btn.disabled=true;btn.textContent='...';

  // 用户消息
  chatMsgs.push({role:'user',content:text});
  if($('.empty-chat',msgs))msgs.innerHTML='';
  msgs.innerHTML+=msgHtml({role:'user',content:text});
  msgs.scrollTop=msgs.scrollHeight;

  // 占位
  const aiIdx=chatMsgs.length;
  chatMsgs.push({role:'assistant',content:'',streaming:true});
  msgs.innerHTML+=msgHtml({role:'assistant',content:''});
  msgs.scrollTop=msgs.scrollHeight;
  const aiEl=msgs.lastElementChild?.querySelector('.b');

  try{
    const r=await fetch('/api/chat/'+encodeURIComponent(chatMod),{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text})
    });
    const d=await r.json();
    const reply=d.reply||d.content||d.message||JSON.stringify(d);
    chatMsgs[aiIdx].content=reply;
    chatMsgs[aiIdx].streaming=false;
    if(aiEl)aiEl.innerHTML=esc(reply);
    msgs.scrollTop=msgs.scrollHeight;
  }catch(e){
    chatMsgs[aiIdx].content='⚠️ 请求失败: '+e.message;
    chatMsgs[aiIdx].streaming=false;
    if(aiEl)aiEl.textContent='⚠️ 请求失败: '+e.message;
  }

  chatSending=false;btn.disabled=false;btn.textContent='发送';
  inp.focus();
}

// ─── 配置 ───
async function renderConfig(el){
  el.innerHTML='<div class="loading"><div class="spin"></div><p>加载配置...</p></div>';
  try{
    const cfg=await api('/api/config');
    const yaml=cfg.yaml||'# 无配置数据';
    const svc=await api('/api/services');

    el.innerHTML=`
    <h1 style="font-size:22px;margin-bottom:8px">⚙ 配置</h1>
    <h3 style="font-size:13px;color:var(--dim);margin-bottom:8px;font-weight:600">📄 模型配置 (YAML)</h3>
    <div class="cfg-box">${esc(yaml)}</div>
    <h3 style="font-size:13px;color:var(--dim);margin:16px 0 8px;font-weight:600">🔧 本地服务</h3>
    <div class="svc-wrap">${svc.map(s=>`<span class="svc"><span class="dot" style="background:${s.active?'var(--green)':'var(--red)'}"></span>${esc(s.name)}<span style="color:var(--dim)">:${s.port}</span>${s.has_mmproj?'<span style="color:var(--accent)">🖼️</span>':''}</span>`).join('')}</div>
    <p style="font-size:12px;color:var(--dim);margin-top:12px">配置为只读。修改请通过 CLI <code style="background:var(--surface);padding:1px 5px;border-radius:4px">arc edit</code> 或向我请求。</p>`;
  }catch(e){
    el.innerHTML=`<div style="padding:40px;text-align:center;color:var(--red)">⚠️ 加载失败: ${esc(e.message)}</div>`;
  }
}

// ─── 状态栏刷新 ───
setInterval(async()=>{
  const el=$('#sb-stat');
  if(!el)return;
  try{
    const d=await api('/api/models');
    const models=d.data||d.models||[];
    const ok=models.filter(m=>m.online).length;
    el.innerHTML=`<span class="dot" style="background:${ok>0?'var(--green)':'var(--red)'}"></span>${ok}/${models.length} 在线`;
  }catch(e){el.innerHTML=`<span class="dot" style="background:var(--red)"></span>离线`}
},10000);
