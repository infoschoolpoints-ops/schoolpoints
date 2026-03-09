"""HTML for purchases page - 3 tabs matching local app's purchases manager."""


def purchases_html():
    return CSS + HTML + JS


CSS = """<style>
.pt{display:flex;gap:6px;margin-bottom:16px;border-bottom:2px solid #e0e4e8;padding-bottom:6px;flex-wrap:wrap}
.pt button{background:none;border:none;color:#7f8c8d;padding:8px 16px;cursor:pointer;font-weight:700;font-size:14px;border-bottom:3px solid transparent}
.pt button.active{color:#2c3e50;border-bottom-color:#3498db;background:#f0f4f8;border-radius:6px 6px 0 0}
.pp{display:none}.pp.act{display:block}
.ptbl{width:100%;border-collapse:collapse}
.ptbl th{padding:8px 10px;text-align:right;background:#f8f9fa;border-bottom:1px solid #e0e4e8;font-size:13px;color:#2c3e50}
.ptbl td{padding:8px 10px;border-bottom:1px solid #f0f2f4;color:#2c3e50}
</style>"""

HTML = """
<div style="max-width:1000px;margin:0 auto;">
<h2 style="color:#fff">&#128722; ניהול קופה</h2>
<div class="pt">
  <button class="active" onclick="ptab('products',this)">&#128717; מוצרים</button>
  <button onclick="ptab('categories',this)">&#128193; קטגוריות</button>
  <button onclick="ptab('settings',this)">&#9881; הגדרות קופה</button>
</div>

<div id="pp-products" class="pp act"><div class="card" style="padding:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h3 style="margin:0">מוצרים</h3>
    <button class="green" onclick="addProduct()" style="padding:5px 12px">+ מוצר חדש</button>
  </div>
  <div style="overflow-x:auto">
  <table class="ptbl"><thead><tr>
    <th>סוג</th><th>פעיל</th><th>שם פנימי</th><th>שם תצוגה</th><th>קטגוריה</th><th>מחיר</th><th>מלאי</th><th>שובר</th><th>פעולות</th>
  </tr></thead><tbody id="prod-body"></tbody></table>
  </div>
</div></div>

<div id="pp-categories" class="pp"><div class="card" style="padding:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <h3 style="margin:0">קטגוריות</h3>
    <button class="green" onclick="addCat()" style="padding:5px 12px">+ קטגוריה</button>
  </div>
  <table class="ptbl"><thead><tr>
    <th>שם</th><th>פעיל</th><th>סדר</th><th>פעולות</th>
  </tr></thead><tbody id="cat-body"></tbody></table>
</div></div>

<div id="pp-settings" class="pp"><div class="card" style="padding:14px">
  <h3 style="margin:0 0 14px 0">הגדרות קופה</h3>
  <div style="margin-bottom:12px">
    <label style="display:flex;align-items:center;gap:8px;font-weight:600">
      <input type="checkbox" id="ps-enabled" style="width:18px;height:18px"> חנות פעילה
    </label>
  </div>
  <div style="margin-bottom:10px">
    <label style="font-weight:600;display:block;margin-bottom:4px">מינימום נקודות לרכישה</label>
    <input type="number" id="ps-min" min="0" value="0" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box">
  </div>
  <div style="margin-bottom:10px">
    <label style="font-weight:600;display:block;margin-bottom:4px">מקסימום רכישות ליום לתלמיד (0=ללא)</label>
    <input type="number" id="ps-maxday" min="0" value="0" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box">
  </div>
  <div style="margin-bottom:12px">
    <label style="display:flex;align-items:center;gap:8px;font-weight:600">
      <input type="checkbox" id="ps-voucher" style="width:18px;height:18px"> אפשר שוברים מרוכזים
    </label>
  </div>
  <button class="green" onclick="saveSettings()" style="padding:8px 18px">שמירה</button>
</div></div>
</div>
"""
JS = """
<script>
let products=[],categories=[],pSettings={};
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function ptab(id,btn){
  document.querySelectorAll('.pp').forEach(e=>e.classList.remove('act'));
  document.getElementById('pp-'+id).classList.add('act');
  document.querySelectorAll('.pt button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}
async function loadAll(){
  try{
    const r=await fetch('/api/settings/purchases_data');
    const d=await r.json();
    products=Array.isArray(d.products)?d.products:[];
    categories=Array.isArray(d.categories)?d.categories:[];
    pSettings=d.settings||{};
  }catch(e){console.error(e)}
  renderProducts();renderCategories();renderSettings();
}
function renderProducts(){
  const tb=document.getElementById('prod-body');
  if(!products.length){tb.innerHTML='<tr><td colspan="9" style="padding:16px;text-align:center;color:#888">אין מוצרים</td></tr>';return}
  tb.innerHTML=products.map((p,i)=>`<tr>
    <td>${p.type==='challenge'?'&#9201; אתגר':'&#128717; מוצר'}</td>
    <td>${p.is_active?'<span style="color:#2ecc71">כן</span>':'<span style="color:#e74c3c">לא</span>'}</td>
    <td>${esc(p.name)}</td><td>${esc(p.display_name||'')}</td>
    <td>${esc(p.category||'')}</td><td>${p.price||0}</td>
    <td>${p.stock===null||p.stock===undefined?'&#8734;':p.stock}</td>
    <td>${p.consolidated?'&#10003;':''}</td>
    <td><button onclick="editProduct(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">&#9998;&#65039;</button>
        <button onclick="delProduct(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">&#128465;&#65039;</button></td>
  </tr>`).join('');
}
function addProduct(){
  const nm=prompt('שם פנימי:');if(!nm)return;
  const dn=prompt('שם תצוגה:',nm);
  const cat=prompt('קטגוריה (ריק=ללא):','');
  const pr=prompt('מחיר (נקודות):','10');
  const st=prompt('מלאי (ריק=אינסופי):','');
  products.push({name:nm,display_name:dn||nm,category:cat||'',price:parseInt(pr)||0,
    stock:st===''?null:parseInt(st),is_active:true,consolidated:false,type:'product'});
  renderProducts();
}
function editProduct(i){
  const p=products[i];
  const nm=prompt('שם פנימי:',p.name);if(!nm)return;
  const dn=prompt('שם תצוגה:',p.display_name||'');
  const cat=prompt('קטגוריה:',p.category||'');
  const pr=prompt('מחיר:',p.price||0);
  const st=prompt('מלאי (ריק=אינסופי):',p.stock===null?'':p.stock);
  const act=confirm('פעיל?');
  const con=confirm('שובר מרוכז?');
  products[i]={...p,name:nm,display_name:dn||nm,category:cat||'',price:parseInt(pr)||0,
    stock:st===''?null:parseInt(st),is_active:act,consolidated:con};
  renderProducts();
}
function delProduct(i){if(!confirm('למחוק מוצר?'))return;products.splice(i,1);renderProducts()}
function renderCategories(){
  const tb=document.getElementById('cat-body');
  if(!categories.length){tb.innerHTML='<tr><td colspan="4" style="padding:16px;text-align:center;color:#888">אין קטגוריות</td></tr>';return}
  tb.innerHTML=categories.map((c,i)=>`<tr>
    <td>${esc(c.name)}</td>
    <td>${c.is_active?'<span style="color:#2ecc71">כן</span>':'<span style="color:#e74c3c">לא</span>'}</td>
    <td>${c.sort_order||0}</td>
    <td><button onclick="editCat(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">&#9998;&#65039;</button>
        <button onclick="delCat(${i})" style="background:none;border:none;cursor:pointer;font-size:15px">&#128465;&#65039;</button></td>
  </tr>`).join('');
}
function addCat(){
  const nm=prompt('שם קטגוריה:');if(!nm)return;
  const ord=prompt('סדר (מספר):','0');
  categories.push({name:nm,is_active:true,sort_order:parseInt(ord)||0});
  renderCategories();
}
function editCat(i){
  const c=categories[i];
  const nm=prompt('שם:',c.name);if(!nm)return;
  const ord=prompt('סדר:',c.sort_order||0);
  const act=confirm('פעיל?');
  categories[i]={...c,name:nm,sort_order:parseInt(ord)||0,is_active:act};
  renderCategories();
}
function delCat(i){if(!confirm('למחוק קטגוריה?'))return;categories.splice(i,1);renderCategories()}
function renderSettings(){
  document.getElementById('ps-enabled').checked=!!pSettings.enabled;
  document.getElementById('ps-min').value=pSettings.min_points||0;
  document.getElementById('ps-maxday').value=pSettings.max_per_day||0;
  document.getElementById('ps-voucher').checked=!!pSettings.allow_vouchers;
}
function readSettings(){
  pSettings={
    enabled:document.getElementById('ps-enabled').checked,
    min_points:parseInt(document.getElementById('ps-min').value)||0,
    max_per_day:parseInt(document.getElementById('ps-maxday').value)||0,
    allow_vouchers:document.getElementById('ps-voucher').checked
  };
}
async function saveSettings(){
  readSettings();
  await saveAll();
}
async function saveAll(){
  readSettings();
  try{
    await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:'purchases_data',value:{products:products,categories:categories,settings:pSettings}})
    });
    alert('נשמר בהצלחה');
  }catch(e){alert('שגיאה: '+e)}
}
loadAll();
</script>
"""
