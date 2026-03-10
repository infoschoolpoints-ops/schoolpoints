"""Purchases page - 3 tabs, DB-backed API (/api/products, /api/product-categories)."""


def purchases_html():
    return CSS + BODY + MODALS + JS


MODALS = """
<!-- Product Modal -->
<div id="pm-overlay" class="mo" onclick="if(event.target===this)closePM()"><div class="mb">
  <h3 id="pm-title">מוצר חדש</h3><input type="hidden" id="pm-id">
  <div class="mf"><label>שם פנימי *</label><input id="pm-name"></div>
  <div class="mf"><label>שם תצוגה</label><input id="pm-display"></div>
  <div class="mf"><label>קטגוריה</label><select id="pm-cat"><option value="">-- ללא --</option></select></div>
  <div class="mf"><label>מחיר (נקודות)</label><input type="number" id="pm-price" min="0" value="0"></div>
  <div class="mf"><label>מלאי (ריק=אינסופי)</label><input type="number" id="pm-stock" min="0"></div>
  <div class="mf"><label>כיתות מורשות (פסיק)</label><input id="pm-classes" placeholder="א,ב,ג"></div>
  <div class="mf"><label>סף נקודות</label><input type="number" id="pm-minpts" min="0" value="0"></div>
  <div class="mf"><label>מקס לתלמיד (0=ללא)</label><input type="number" id="pm-maxs" min="0" value="0"></div>
  <div class="mf"><label>מקס לכיתה (0=ללא)</label><input type="number" id="pm-maxc" min="0" value="0"></div>
  <div class="mf"><label>סדר מיון</label><input type="number" id="pm-sort" min="0" value="0"></div>
  <div class="mf"><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="pm-active" checked> פעיל</label></div>
  <div class="mf"><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="pm-deduct" checked> ניכוי נקודות</label></div>
  <div class="mf"><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="pm-voucher"> שובר מרוכז</label></div>
  <div class="mbtn"><button class="green" onclick="savePM()">שמירה</button><button onclick="closePM()" style="background:#95a5a6;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer">ביטול</button></div>
</div></div>
<!-- Category Modal -->
<div id="cm-overlay" class="mo" onclick="if(event.target===this)closeCM()"><div class="mb">
  <h3 id="cm-title">קטגוריה חדשה</h3><input type="hidden" id="cm-id">
  <div class="mf"><label>שם *</label><input id="cm-name"></div>
  <div class="mf"><label>סדר</label><input type="number" id="cm-sort" min="0" value="0"></div>
  <div class="mf"><label>סף נקודות</label><input type="number" id="cm-minpts" min="0" value="0"></div>
  <div class="mf"><label>מקס לתלמיד (0=ללא)</label><input type="number" id="cm-maxs" min="0" value="0"></div>
  <div class="mf"><label>מקס לכיתה (0=ללא)</label><input type="number" id="cm-maxc" min="0" value="0"></div>
  <div class="mf"><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="cm-active" checked> פעיל</label></div>
  <div class="mf"><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="cm-catalog" checked> הצג בקטלוג</label></div>
  <div class="mbtn"><button class="green" onclick="saveCM()">שמירה</button><button onclick="closeCM()" style="background:#95a5a6;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer">ביטול</button></div>
</div></div>
"""


CSS = '<style>' \
'.pt{display:flex;gap:6px;margin-bottom:16px;border-bottom:2px solid #e0e4e8;padding-bottom:6px;flex-wrap:wrap}' \
'.pt button{background:none;border:none;color:#7f8c8d;padding:8px 16px;cursor:pointer;font-weight:700;font-size:14px;border-bottom:3px solid transparent}' \
'.pt button.active{color:#2c3e50;border-bottom-color:#3498db;background:#f0f4f8;border-radius:6px 6px 0 0}' \
'.pp{display:none}.pp.act{display:block}' \
'.ptbl{width:100%;border-collapse:collapse}' \
'.ptbl th{padding:8px 10px;text-align:right;background:#f8f9fa;border-bottom:1px solid #e0e4e8;font-size:13px;color:#2c3e50;white-space:nowrap}' \
'.ptbl td{padding:8px 10px;border-bottom:1px solid #f0f2f4;color:#2c3e50}.ptbl tr:hover{background:#f5f7fa}' \
'.mo{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:999;align-items:flex-start;justify-content:center;padding-top:40px}' \
'.mo.show{display:flex}' \
'.mb{background:#fff;border-radius:12px;padding:24px;min-width:380px;max-width:520px;width:90%;max-height:80vh;overflow-y:auto;direction:rtl}' \
'.mb h3{margin:0 0 16px;color:#2c3e50}' \
'.mf{margin-bottom:10px}.mf label{display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e}' \
'.mf input,.mf select{width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box}' \
'.mf input[type=checkbox]{width:18px;height:18px}' \
'.mbtn{display:flex;gap:8px;justify-content:flex-start;margin-top:16px}' \
'</style>'

BODY = """
<div style="max-width:1100px;margin:0 auto;">
<h2 style="color:#fff">&#128722; ניהול קופה</h2>
<div class="pt">
  <button class="active" onclick="ptab('products',this)">&#128717; מוצרים</button>
  <button onclick="ptab('categories',this)">&#128193; קטגוריות</button>
  <button onclick="ptab('settings',this)">&#9881; הגדרות קופה</button>
</div>
<div id="pp-products" class="pp act"><div class="card" style="padding:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h3 style="margin:0">מוצרים</h3>
    <button class="green" onclick="openPM()" style="padding:5px 12px">+ מוצר חדש</button>
  </div>
  <div style="overflow-x:auto"><table class="ptbl"><thead><tr>
    <th>פעיל</th><th>שם</th><th>תצוגה</th><th>קטגוריה</th><th>מחיר</th><th>מלאי</th><th>ניכוי</th><th>שובר</th><th>כיתות</th><th>סף</th><th>מקס/ת</th><th>פעולות</th>
  </tr></thead><tbody id="prod-body"></tbody></table></div>
</div></div>
<div id="pp-categories" class="pp"><div class="card" style="padding:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h3 style="margin:0">קטגוריות</h3>
    <button class="green" onclick="openCM()" style="padding:5px 12px">+ קטגוריה</button>
  </div>
  <table class="ptbl"><thead><tr>
    <th>שם</th><th>פעיל</th><th>קטלוג</th><th>סדר</th><th>מקס/ת</th><th>מקס/כ</th><th>סף</th><th>פעולות</th>
  </tr></thead><tbody id="cat-body"></tbody></table>
</div></div>
<div id="pp-settings" class="pp"><div class="card" style="padding:14px">
  <h3 style="margin:0 0 14px 0">הגדרות קופה</h3>
  <div style="margin-bottom:12px"><label style="display:flex;align-items:center;gap:8px;font-weight:600">
    <input type="checkbox" id="ps-enabled" style="width:18px;height:18px"> חנות פעילה</label></div>
  <div style="margin-bottom:10px"><label style="font-weight:600;display:block;margin-bottom:4px">מינימום נקודות</label>
    <input type="number" id="ps-min" min="0" value="0" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box"></div>
  <div style="margin-bottom:10px"><label style="font-weight:600;display:block;margin-bottom:4px">מקסימום רכישות ליום (0=ללא)</label>
    <input type="number" id="ps-maxday" min="0" value="0" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box"></div>
  <div style="margin-bottom:12px"><label style="display:flex;align-items:center;gap:8px;font-weight:600">
    <input type="checkbox" id="ps-voucher" style="width:18px;height:18px"> שוברים מרוכזים</label></div>
  <button class="green" onclick="savePurchaseSettings()" style="padding:8px 18px">שמירה</button>
</div></div>
</div>
"""

JS = """
<script>
let prods=[],cats=[];
const E=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
function ptab(id,btn){
  document.querySelectorAll('.pp').forEach(e=>e.classList.remove('act'));
  document.getElementById('pp-'+id).classList.add('act');
  document.querySelectorAll('.pt button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}
async function loadProds(){
  try{const r=await fetch('/api/products');const d=await r.json();prods=d.items||[];}catch(e){console.error(e)}
  renderProds();
}
async function loadCats(){
  try{const r=await fetch('/api/product-categories');const d=await r.json();cats=d.items||[];}catch(e){console.error(e)}
  renderCats();
}
async function loadSettings(){
  try{const r=await fetch('/api/settings/purchases_data');const d=await r.json();const s=d.settings||d||{};
    document.getElementById('ps-enabled').checked=!!s.enabled;
    document.getElementById('ps-min').value=s.min_points||0;
    document.getElementById('ps-maxday').value=s.max_per_day||0;
    document.getElementById('ps-voucher').checked=!!s.allow_vouchers;
  }catch(e){}
}
function catName(id){const c=cats.find(x=>x.id==id);return c?E(c.name):'';}
function renderProds(){
  const tb=document.getElementById('prod-body');
  if(!prods.length){tb.innerHTML='<tr><td colspan="12" style="padding:16px;text-align:center;color:#888">אין מוצרים</td></tr>';return;}
  tb.innerHTML=prods.map(p=>`<tr>
    <td>${p.is_active?'<span style="color:#2ecc71">V</span>':'<span style="color:#e74c3c">X</span>'}</td>
    <td>${E(p.name)}</td><td>${E(p.display_name||'')}</td>
    <td>${catName(p.category_id)}</td><td>${p.price_points||0}</td>
    <td>${p.stock_qty==null?'&#8734;':p.stock_qty}</td>
    <td>${p.deduct_points?'V':''}</td>
    <td>${p.consolidated_voucher?'V':''}</td>
    <td>${E(p.allowed_classes||'')}</td>
    <td>${p.min_points_required||0}</td>
    <td>${p.max_per_student||0}</td>
    <td><button onclick="openPM(${p.id})" style="background:none;border:none;cursor:pointer;font-size:15px" title="ערוך">&#9998;</button>
        <button onclick="delProd(${p.id})" style="background:none;border:none;cursor:pointer;font-size:15px" title="מחק">&#128465;</button></td>
  </tr>`).join('');
}
function renderCats(){
  const tb=document.getElementById('cat-body');
  if(!cats.length){tb.innerHTML='<tr><td colspan="8" style="padding:16px;text-align:center;color:#888">אין קטגוריות</td></tr>';return;}
  tb.innerHTML=cats.map(c=>`<tr>
    <td>${E(c.name)}</td>
    <td>${c.is_active?'<span style="color:#2ecc71">V</span>':'<span style="color:#e74c3c">X</span>'}</td>
    <td>${c.show_in_catalog?'V':''}</td>
    <td>${c.sort_order||0}</td>
    <td>${c.max_items_per_student||0}</td>
    <td>${c.max_items_per_class||0}</td>
    <td>${c.min_points_required||0}</td>
    <td><button onclick="openCM(${c.id})" style="background:none;border:none;cursor:pointer;font-size:15px">&#9998;</button>
        <button onclick="delCat(${c.id})" style="background:none;border:none;cursor:pointer;font-size:15px">&#128465;</button></td>
  </tr>`).join('');
}
function fillCatSelect(){
  const sel=document.getElementById('pm-cat');
  sel.innerHTML='<option value="">-- ללא --</option>'+cats.map(c=>`<option value="${c.id}">${E(c.name)}</option>`).join('');
}
function openPM(id){
  fillCatSelect();
  const p=id?prods.find(x=>x.id===id):null;
  document.getElementById('pm-title').textContent=p?'עריכת מוצר':'מוצר חדש';
  document.getElementById('pm-id').value=p?p.id:'';
  document.getElementById('pm-name').value=p?p.name:'';
  document.getElementById('pm-display').value=p?p.display_name||'':'';
  document.getElementById('pm-cat').value=p?p.category_id||'':'';
  document.getElementById('pm-price').value=p?p.price_points||0:0;
  document.getElementById('pm-stock').value=p&&p.stock_qty!=null?p.stock_qty:'';
  document.getElementById('pm-classes').value=p?p.allowed_classes||'':'';
  document.getElementById('pm-minpts').value=p?p.min_points_required||0:0;
  document.getElementById('pm-maxs').value=p?p.max_per_student||0:0;
  document.getElementById('pm-maxc').value=p?p.max_per_class||0:0;
  document.getElementById('pm-sort').value=p?p.sort_order||0:0;
  document.getElementById('pm-active').checked=p?!!p.is_active:true;
  document.getElementById('pm-deduct').checked=p?!!p.deduct_points:true;
  document.getElementById('pm-voucher').checked=p?!!p.consolidated_voucher:false;
  document.getElementById('pm-overlay').classList.add('show');
}
function closePM(){document.getElementById('pm-overlay').classList.remove('show');}
async function savePM(){
  const nm=document.getElementById('pm-name').value.trim();
  if(!nm){alert('שם פנימי חובה');return;}
  const body={name:nm,
    display_name:document.getElementById('pm-display').value.trim()||nm,
    category_id:parseInt(document.getElementById('pm-cat').value)||null,
    price_points:parseInt(document.getElementById('pm-price').value)||0,
    stock_qty:document.getElementById('pm-stock').value===''?null:parseInt(document.getElementById('pm-stock').value),
    allowed_classes:document.getElementById('pm-classes').value.trim(),
    min_points_required:parseInt(document.getElementById('pm-minpts').value)||0,
    max_per_student:parseInt(document.getElementById('pm-maxs').value)||0,
    max_per_class:parseInt(document.getElementById('pm-maxc').value)||0,
    sort_order:parseInt(document.getElementById('pm-sort').value)||0,
    is_active:document.getElementById('pm-active').checked?1:0,
    deduct_points:document.getElementById('pm-deduct').checked?1:0,
    consolidated_voucher:document.getElementById('pm-voucher').checked?1:0};
  const pid=document.getElementById('pm-id').value;
  if(pid)body.id=parseInt(pid);
  try{await fetch('/api/products/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    closePM();await loadProds();
  }catch(e){alert('שגיאה: '+e);}
}
async function delProd(id){
  if(!confirm('למחוק מוצר?'))return;
  await fetch('/api/products/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})});
  await loadProds();
}
function openCM(id){
  const c=id?cats.find(x=>x.id===id):null;
  document.getElementById('cm-title').textContent=c?'עריכת קטגוריה':'קטגוריה חדשה';
  document.getElementById('cm-id').value=c?c.id:'';
  document.getElementById('cm-name').value=c?c.name:'';
  document.getElementById('cm-sort').value=c?c.sort_order||0:0;
  document.getElementById('cm-minpts').value=c?c.min_points_required||0:0;
  document.getElementById('cm-maxs').value=c?c.max_items_per_student||0:0;
  document.getElementById('cm-maxc').value=c?c.max_items_per_class||0:0;
  document.getElementById('cm-active').checked=c?!!c.is_active:true;
  document.getElementById('cm-catalog').checked=c?!!c.show_in_catalog:true;
  document.getElementById('cm-overlay').classList.add('show');
}
function closeCM(){document.getElementById('cm-overlay').classList.remove('show');}
async function saveCM(){
  const nm=document.getElementById('cm-name').value.trim();
  if(!nm){alert('שם חובה');return;}
  const body={name:nm,
    sort_order:parseInt(document.getElementById('cm-sort').value)||0,
    min_points_required:parseInt(document.getElementById('cm-minpts').value)||0,
    max_items_per_student:parseInt(document.getElementById('cm-maxs').value)||0,
    max_items_per_class:parseInt(document.getElementById('cm-maxc').value)||0,
    is_active:document.getElementById('cm-active').checked?1:0,
    show_in_catalog:document.getElementById('cm-catalog').checked?1:0};
  const cid=document.getElementById('cm-id').value;
  if(cid)body.id=parseInt(cid);
  try{await fetch('/api/product-categories/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    closeCM();await loadCats();fillCatSelect();
  }catch(e){alert('שגיאה: '+e);}
}
async function delCat(id){
  if(!confirm('למחוק קטגוריה?'))return;
  await fetch('/api/product-categories/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})});
  await loadCats();
}
async function savePurchaseSettings(){
  const s={enabled:document.getElementById('ps-enabled').checked,
    min_points:parseInt(document.getElementById('ps-min').value)||0,
    max_per_day:parseInt(document.getElementById('ps-maxday').value)||0,
    allow_vouchers:document.getElementById('ps-voucher').checked};
  try{await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:'purchases_data',value:{settings:s}})});
    alert('נשמר');
  }catch(e){alert('שגיאה: '+e);}
}
loadCats().then(()=>loadProds());loadSettings();
</script>
"""
