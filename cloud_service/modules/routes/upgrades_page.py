"""HTML for upgrades page - 4 tabs matching local ColorEditor."""


def upgrades_html():
    return CSS + HTML + JS


CSS = '<style>.ut{display:flex;gap:6px;margin-bottom:16px;border-bottom:2px solid #e0e4e8;padding-bottom:6px;flex-wrap:wrap}.ut button{background:none;border:none;color:#7f8c8d;padding:8px 16px;cursor:pointer;font-weight:700;font-size:14px;border-bottom:3px solid transparent}.ut button.active{color:#2c3e50;border-bottom-color:#3498db;background:#f0f4f8;border-radius:6px 6px 0 0}.up{display:none}.up.act{display:block}.utbl{width:100%;border-collapse:collapse}.utbl th{padding:8px 10px;text-align:right;background:#f8f9fa;border-bottom:1px solid #e0e4e8;font-size:13px;color:#2c3e50}.utbl td{padding:8px 10px;border-bottom:1px solid #f0f2f4;color:#2c3e50}.erow{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid #f0f2f4}.erow>span{min-width:150px;text-align:right;font-weight:600;color:#2c3e50}.erow input[type=text]{flex:1;padding:6px 10px;border:1px solid #ccd0d5;border-radius:6px;color:#2c3e50}</style>'

HTML = """
<div style="max-width:950px;margin:0 auto;">
<h2 style="color:#fff">&#127925; צלילים, צבעים ומטבעות</h2>
<p style="color:rgba(255,255,255,0.6);margin-bottom:14px;font-size:14px">הגדרות תצוגת העמדה הציבורית</p>
<div class="ut">
  <button class="active" onclick="utab('ranges',this)">&#127912; צלילים וצבעים</button>
  <button onclick="utab('coins',this)">&#129689; מטבעות ויהלומים</button>
  <button onclick="utab('goals',this)">&#127919; יעדים</button>
  <button onclick="utab('events',this)">&#128266; צלילי אירועים</button>
</div>

<div id="up-ranges" class="up act"><div class="card" style="padding:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h3 style="margin:0">טווחי צבעים וצלילים</h3>
    <button class="green" onclick="addRange()" style="padding:5px 12px">+ טווח</button>
  </div>
  <table class="utbl"><thead><tr>
    <th>מינימום</th><th>מקסימום</th><th>שם</th><th>צבע</th><th>צליל</th><th>פעולות</th>
  </tr></thead><tbody id="rng-body"></tbody></table>
</div></div>

<div id="up-coins" class="up"><div class="card" style="padding:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h3 style="margin:0">מטבעות ויהלומים</h3>
    <button class="green" onclick="addCoin()" style="padding:5px 12px">+ חדש</button>
  </div>
  <table class="utbl"><thead><tr>
    <th>סוג</th><th>סכום</th><th>שם</th><th>צבע</th><th>פעולות</th>
  </tr></thead><tbody id="coin-body"></tbody></table>
</div></div>

<div id="up-goals" class="up"><div class="card" style="padding:14px">
  <h3 style="margin:0 0 14px 0">יעד נקודות (פס התקדמות)</h3>
  <div style="margin-bottom:12px">
    <label style="display:flex;align-items:center;gap:8px;font-weight:600">
      <input type="checkbox" id="g-en" style="width:18px;height:18px"> הפעל פס יעד
    </label>
  </div>
  <div style="margin-bottom:10px">
    <label style="font-weight:600;display:block;margin-bottom:4px">סוג יעד</label>
    <select id="g-mode" style="padding:6px 10px;border:1px solid #ccd0d5;border-radius:6px;width:100%">
      <option value="absolute">יעד מוחלט</option>
      <option value="relative">יעד יחסי</option>
      <option value="relative_class">יעד יחסי לכיתה</option>
      <option value="max_points_possible">מקסימום נקודות אפשרי</option>
    </select>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
    <div><label style="font-weight:600;display:block;margin-bottom:4px">יעד מוחלט (נקודות)</label>
      <input type="number" id="g-abs" value="100" style="width:100%;padding:6px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box"></div>
    <div><label style="font-weight:600;display:block;margin-bottom:4px">יעד יחסי (%)</label>
      <input type="number" id="g-rel" value="80" style="width:100%;padding:6px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box"></div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px">
    <div><label style="font-weight:600;display:block;margin-bottom:4px">צבע מילוי</label>
      <input type="color" id="g-fc" value="#2ecc71" style="width:100%;height:36px;border:1px solid #ccd0d5;border-radius:6px"></div>
    <div><label style="font-weight:600;display:block;margin-bottom:4px">צבע רקע</label>
      <input type="color" id="g-ec" value="#ecf0f1" style="width:100%;height:36px;border:1px solid #ccd0d5;border-radius:6px"></div>
    <div><label style="font-weight:600;display:block;margin-bottom:4px">צבע מסגרת</label>
      <input type="color" id="g-bc" value="#2c3e50" style="width:100%;height:36px;border:1px solid #ccd0d5;border-radius:6px"></div>
  </div>
  <label style="display:flex;align-items:center;gap:8px;font-weight:600;margin-bottom:14px">
    <input type="checkbox" id="g-pct" style="width:18px;height:18px"> הצג אחוז התקדמות
  </label>
  <button class="green" onclick="saveGoals()" style="padding:8px 18px">שמירה</button>
</div></div>

<div id="up-events" class="up"><div class="card" style="padding:14px">
  <h3 style="margin:0 0 14px 0">צלילים לאירועים בעמדה הציבורית</h3>
  <p style="color:#7f8c8d;font-size:13px;margin-bottom:14px">בחר צליל לכל אירוע. אם לא מוגדר – תישאר ברירת מחדל.</p>
  <div id="ev-list"></div>
  <button class="green" onclick="saveEvents()" style="padding:8px 18px;margin-top:14px">שמירה</button>
</div></div>

<button class="green" onclick="saveAll()" style="padding:10px 24px;margin-top:18px;font-size:15px">💾 שמור הכל</button>
</div>
"""
JS = """
<script>
let D={color_ranges:[],coins:[],goal:{},event_sounds:{}};
const EV_KEYS=[
  ['unknown_card','כרטיס לא מזוהה'],
  ['swipe_ok','תיקוף רגיל'],
  ['teacher_bonus','בונוס מורה'],
  ['special_bonus','בונוס מיוחד (מאסטר)'],
  ['first_swipe','מתקף ראשון'],
  ['time_bonus','בונוס זמנים'],
  ['tier_up_first_time','דרגה חדשה (פעם ראשונה)']
];
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function utab(id,btn){
  document.querySelectorAll('.up').forEach(e=>e.classList.remove('act'));
  document.getElementById('up-'+id).classList.add('act');
  document.querySelectorAll('.ut button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}
async function loadAll(){
  try{
    const r=await fetch('/api/settings/color_settings');
    const d=await r.json();
    D.color_ranges=Array.isArray(d.color_ranges)?d.color_ranges:(Array.isArray(d.ranges)?d.ranges:[]);
    D.coins=Array.isArray(d.coins)?d.coins:[];
    D.goal=d.goal||{};
    D.event_sounds=d.event_sounds||{};
  }catch(e){console.error(e)}
  renderRanges();renderCoins();renderGoals();renderEvents();
}
function renderRanges(){
  const tb=document.getElementById('rng-body');
  if(!D.color_ranges.length){tb.innerHTML='<tr><td colspan="6" style="padding:16px;text-align:center;color:#888">אין טווחים</td></tr>';return}
  tb.innerHTML=D.color_ranges.map((r,i)=>`<tr>
    <td>${r.min||0}</td><td>${r.max||'∞'}</td><td>${esc(r.name||'')}</td>
    <td><span style="display:inline-block;width:20px;height:20px;background:${r.color||'#ccc'};border:1px solid #aaa;border-radius:4px;vertical-align:middle"></span> ${esc(r.color||'')}</td>
    <td>${esc(r.sound||'-')}</td>
    <td><button onclick="editRange(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">✏️</button>
        <button onclick="delRange(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">🗑️</button></td>
  </tr>`).join('');
}
function addRange(){
  const mn=prompt('מינימום נקודות:','0');if(mn===null)return;
  const mx=prompt('מקסימום נקודות:','999999');if(mx===null)return;
  const nm=prompt('שם הטווח:','');
  const cl=prompt('צבע (hex):','#3498db');if(!cl)return;
  const snd=prompt('צליל (שם קובץ, ריק=ברירת מחדל):','');
  D.color_ranges.push({min:parseInt(mn)||0,max:parseInt(mx)||999999,name:nm||'',color:cl,sound:snd||''});
  D.color_ranges.sort((a,b)=>(a.min||0)-(b.min||0));
  renderRanges();
}
function editRange(i){
  const r=D.color_ranges[i];
  const mn=prompt('מינימום:',r.min);if(mn===null)return;
  const mx=prompt('מקסימום:',r.max);if(mx===null)return;
  const nm=prompt('שם:',r.name||'');
  const cl=prompt('צבע:',r.color);if(!cl)return;
  const snd=prompt('צליל:',r.sound||'');
  D.color_ranges[i]={min:parseInt(mn)||0,max:parseInt(mx)||999999,name:nm||'',color:cl,sound:snd||''};
  D.color_ranges.sort((a,b)=>(a.min||0)-(b.min||0));
  renderRanges();
}
function delRange(i){if(!confirm('למחוק?'))return;D.color_ranges.splice(i,1);renderRanges()}
function renderCoins(){
  const tb=document.getElementById('coin-body');
  if(!D.coins.length){tb.innerHTML='<tr><td colspan="5" style="padding:16px;text-align:center;color:#888">אין מטבעות</td></tr>';return}
  tb.innerHTML=D.coins.map((c,i)=>`<tr>
    <td>${c.kind==='diamond'?'💎 יהלום':'🪙 מטבע'}</td>
    <td>${c.amount||0}</td><td>${esc(c.name||'')}</td>
    <td><span style="display:inline-block;width:20px;height:20px;background:${c.color||'#f1c40f'};border:1px solid #aaa;border-radius:50%;vertical-align:middle"></span></td>
    <td><button onclick="editCoin(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">✏️</button>
        <button onclick="delCoin(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">🗑️</button></td>
  </tr>`).join('');
}
function addCoin(){
  const kind=prompt('סוג (coin / diamond):','coin');if(!kind)return;
  const amt=prompt('סכום נקודות:','10');if(amt===null)return;
  const nm=prompt('שם (רשות):','');
  const cl=prompt('צבע:','#f1c40f');
  D.coins.push({kind:kind,amount:parseInt(amt)||0,name:nm||'',color:cl||'#f1c40f'});
  renderCoins();
}
function editCoin(i){
  const c=D.coins[i];
  const kind=prompt('סוג (coin/diamond):',c.kind||'coin');if(!kind)return;
  const amt=prompt('סכום:',c.amount);if(amt===null)return;
  const nm=prompt('שם:',c.name||'');
  const cl=prompt('צבע:',c.color||'#f1c40f');
  D.coins[i]={kind:kind,amount:parseInt(amt)||0,name:nm||'',color:cl||'#f1c40f'};
  renderCoins();
}
function delCoin(i){if(!confirm('למחוק?'))return;D.coins.splice(i,1);renderCoins()}
function renderGoals(){
  const g=D.goal||{};
  document.getElementById('g-en').checked=!!g.enabled;
  document.getElementById('g-mode').value=g.mode||'absolute';
  document.getElementById('g-abs').value=g.absolute_points||100;
  document.getElementById('g-rel').value=g.relative_percent||80;
  document.getElementById('g-fc').value=g.filled_color||'#2ecc71';
  document.getElementById('g-ec').value=g.empty_color||'#ecf0f1';
  document.getElementById('g-bc').value=g.border_color||'#2c3e50';
  document.getElementById('g-pct').checked=g.show_percent!==false;
}
function readGoals(){
  D.goal={
    enabled:document.getElementById('g-en').checked,
    mode:document.getElementById('g-mode').value,
    absolute_points:parseInt(document.getElementById('g-abs').value)||100,
    relative_percent:parseFloat(document.getElementById('g-rel').value)||80,
    filled_color:document.getElementById('g-fc').value,
    empty_color:document.getElementById('g-ec').value,
    border_color:document.getElementById('g-bc').value,
    show_percent:document.getElementById('g-pct').checked
  };
}
function saveGoals(){readGoals();saveAll()}
function renderEvents(){
  const el=document.getElementById('ev-list');
  el.innerHTML=EV_KEYS.map(([k,lbl])=>`<div class="erow">
    <span>${lbl}</span>
    <input type="text" id="ev-${k}" value="${esc((D.event_sounds||{})[k]||'')}" placeholder="שם קובץ צליל (ריק=ברירת מחדל)">
  </div>`).join('');
}
function readEvents(){
  D.event_sounds={};
  EV_KEYS.forEach(([k])=>{
    const v=(document.getElementById('ev-'+k)||{}).value||'';
    if(v.trim()) D.event_sounds[k]=v.trim();
  });
}
function saveEvents(){readEvents();saveAll()}
async function saveAll(){
  readGoals();readEvents();
  try{
    await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:'color_settings',value:{
        color_ranges:D.color_ranges,coins:D.coins,goal:D.goal,event_sounds:D.event_sounds
      }})
    });
    alert('נשמר בהצלחה');
  }catch(e){alert('שגיאה: '+e)}
}
loadAll();
</script>
"""
