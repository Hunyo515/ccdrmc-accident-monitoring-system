(function(){
 'use strict';
 const labels={date:'Date',time:'Time',barangay:'Barangay',vehicle_involved:'Vehicle',collision_type:'Collision type',cause:'Recorded cause',severity:'Severity',at_user:'Road user',damage_injury:'Injury / damage description',time_period:'Time period',estimated_fields:'Estimated fields',derived_severity:'Suggested outcome',supplied_severity:'Supplied outcome'};
 const internal=['record_id','record_revision','preprocessing_version','needs_manual_review','review_notes','source_fingerprint','validation_notes'];
 const derived=['year','month','day','hour','minute','time_period','accident_id','imported_at','source_file','estimated_fields','derived_severity','supplied_severity'];
 const $=id=>document.getElementById(id),esc=window.escapeHTML;
 let page=1,ticket=0,historyPage=1;
 const label=k=>labels[k]||k.replaceAll('_',' ');
 const isoDate=value=>String(value||'').replace(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/,(_,m,d,y)=>`${y}-${m.padStart(2,'0')}-${d.padStart(2,'0')}`);
 const cell=(r,k)=>`${esc(k==='date'?isoDate(r[k]):(['latitude','longitude'].includes(k)&&r[k+'_imputed']===true?'Unknown':r[k]??'—'))}${String(r.estimated_fields||'').split(', ').includes(k)?'<span class="estimated-badge">Estimated</span>':''}`;
 async function request(url,body){
   const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
   let data;try{data=await r.json();}catch(_){throw Error('The service could not complete this request. Please try again.');}
   if(!r.ok)throw Error(data.error||'Request failed.');return data;
 }
 async function load(){
   const own=++ticket;
   try{
     const p=new URLSearchParams({page,page_size:$('data-size').value,search:$('data-search').value});
     const d=await getJSON('/api/data?'+p);if(own!==ticket)return;page=d.page;
     $('data-count').textContent=`${fmt(d.total)} matching records · ${fmt(d.dataset_total)} total`;
     $('data-updated').textContent=`Analysis updated: ${new Date(d.meta.mined_at).toLocaleString()}`;
     $('data-table').innerHTML=`<thead><tr>${d.columns.map(c=>`<th>${esc(label(c))}</th>`).join('')}</tr></thead><tbody>${d.rows.length?d.rows.map(r=>`<tr class="record-open" data-id="${esc(r.record_id)}" tabindex="0" aria-label="Open record from ${esc(r.date||'unknown date')}" title="Select to view or edit record">${d.columns.map(c=>`<td>${cell(r,c)}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${d.columns.length}">No matching records.</td></tr>`}</tbody>`;
     const pages=Math.max(1,Math.ceil(d.total/d.page_size));$('data-page').textContent=`Page ${page} of ${pages}`;$('data-prev').disabled=page<=1;$('data-next').disabled=page>=pages;
     $('data-table').querySelectorAll('.record-open').forEach(b=>{b.onclick=()=>openRecord(b.dataset.id);b.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openRecord(b.dataset.id);}};});
     $('data-error').textContent='';
   }catch(e){$('data-error').textContent=e.message;}
 }
 $('data-search').addEventListener('input',debounce(()=>{page=1;load();},250));
 $('data-size').onchange=()=>{page=1;load();};$('data-prev').onclick=()=>{page--;load();};$('data-next').onclick=()=>{page++;load();};
 const dialog=$('record-dialog');$('close-record').onclick=()=>dialog.close();
 function historyValues(detail){
   const before=detail?.before?.cleaned||detail?.before||{},after=detail?.after?.cleaned||detail?.after||{};
   const keys=[...new Set([...Object.keys(before),...Object.keys(after)])].filter(k=>!internal.includes(k)&&typeof after[k]!=='object'&&String(before[k]??'')!==String(after[k]??''));
   return keys.length?`<div class="preview-scroll"><table class="preview-table"><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>${keys.map(k=>`<tr><td>${esc(label(k))}</td><td>${esc(before[k]??'—')}</td><td>${esc(after[k]??'—')}</td></tr>`).join('')}</tbody></table></div>`:'<p>No record values changed.</p>';
 }
 async function openRecord(id){
   $('record-title').textContent='Record details';$('record-body').textContent='Loading…';dialog.showModal();
   try{
     const d=await request('/api/records/'+encodeURIComponent(id));
     $('record-body').innerHTML=`<dl class="record-details">${Object.keys(d.record).filter(k=>!internal.includes(k)).map(k=>`<dt>${esc(label(k))}</dt><dd>${cell(d.record,k)}</dd>`).join('')}</dl><button class="btn" id="edit-record">Edit record</button><h3>Change history</h3>${d.history.map(h=>`<details><summary>${esc(h.action)} · ${esc(h.created_at)} · ${esc(h.actor)}</summary>${historyValues(h.detail)}</details>`).join('')}`;
     $('edit-record').onclick=()=>form(d.record);
   }catch(e){$('record-body').textContent=e.message;}
 }
 function form(record=null){
   $('record-title').textContent=record?'Edit accident record':'Enter an accident';
   const defaults=['date','time','barangay','vehicle_involved','collision_type','cause','damage_injury','severity','at_user','latitude','longitude','incident_id'];
   const keys=[...new Set([...defaults,...Object.keys(record||{})])].filter(k=>!internal.includes(k)&&!derived.includes(k)&&!k.endsWith('_imputed')&&!k.startsWith('extra_'));
   $('record-body').innerHTML=`<form id="manual-form"><div class="record-form-grid">${keys.map(k=>`<label>${esc(label(k))}${k==='severity'?`<select name="severity">${['Unknown','Fatal','Non-Fatal','Damage-to-Property'].map(v=>`<option value="${v}" ${record?.severity===v?'selected':''}>${v==='Unknown'?'Derive from description':v}</option>`).join('')}</select>`:`<input name="${esc(k)}" value="${esc(k==='date'?isoDate(record?.[k]):record?.[k]??'')}" ${k==='date'?'type="date" required':''}>`}</label>`).join('')}</div><label class="outcome-confirm"><input type="checkbox" id="outcome-verified"> I verified the selected outcome against the accident report.</label><p class="hint">Use this confirmation only when supplying a verified outcome. Other fields are checked automatically.</p><p id="manual-error" role="alert"></p><button class="btn" type="submit">${record?'Save changes':'Add record'}</button></form>`;
   if(!dialog.open)dialog.showModal();
   $('manual-form').onsubmit=async e=>{
     e.preventDefault();e.submitter.disabled=true;
     try{
       const values=Object.fromEntries(new FormData(e.target));
       if($('outcome-verified').checked&&values.severity==='Unknown')throw Error('Choose the outcome you verified.');
       await request(record?'/api/dataset/records/'+encodeURIComponent(record.record_id):'/api/dataset/manual',{record:values,revision:record?.record_revision,outcome_verified:$('outcome-verified').checked});
       dialog.close();await load();if($('import-history').open)await loadHistory();
     }catch(err){$('manual-error').textContent=err.message;e.submitter.disabled=false;}
   };
 }
 $('manual-entry').onclick=()=>form();
 async function loadHistory(){
   try{
     const d=await request('/api/dataset/history?page='+historyPage);
     $('history-content').innerHTML=d.imports.length?d.imports.map(b=>`<div class="import-receipt"><div><strong>${esc(b.name)}</strong><p>${esc(new Date(b.created_at).toLocaleString())} · ${b.added} added · ${b.duplicates} duplicates · ${b.excluded} excluded ${b.reversed?'· Undone':''}</p></div><div class="receipt-actions">${b.name!=='Manual entry'?`<a href="/api/dataset/history/${encodeURIComponent(b.id)}/original">Original file</a>`:''}${b.excluded+b.duplicates?`<a href="/api/dataset/history/${encodeURIComponent(b.id)}/excluded">Excluded rows</a>`:''}${!b.reversed?`<button class="text-button undo-import" data-id="${esc(b.id)}" data-name="${esc(b.name)}" data-count="${b.added}">Undo import</button>`:''}</div></div>`).join(''):'<p>No completed imports yet.</p>';
     $('history-count').textContent=`${d.total} imports · Page ${d.page}`;$('history-prev').disabled=historyPage<=1;$('history-next').disabled=historyPage*d.page_size>=d.total;
     $('history-content').querySelectorAll('.undo-import').forEach(button=>button.onclick=async()=>{
       if(!confirm(`Undo ${button.dataset.name}? This removes its ${button.dataset.count} imported records from analysis. Original files and history remain. Undo is blocked if records have since changed.`))return;
       button.disabled=true;
       try{await request('/api/dataset/history/'+encodeURIComponent(button.dataset.id)+'/undo',{confirm:true});await load();await loadHistory();}catch(e){$('data-error').textContent=e.message;button.disabled=false;}
     });
   }catch(e){$('history-content').textContent=e.message;}
 }
 $('import-history').ontoggle=()=>{if($('import-history').open)loadHistory();};
 $('history-prev').onclick=()=>{historyPage--;loadHistory();};$('history-next').onclick=()=>{historyPage++;loadHistory();};
 load();
})();
