(function(){
'use strict';
const $=id=>document.getElementById(id), esc=window.escapeHTML, batch=window.REVIEW_BATCH;
let rows=[],fields={},selected=null,busy=false,dirty=false,page=1,counts={},total=0;
const basic=['date','time','barangay','vehicle_involved','collision_type','cause','damage_injury','severity'];
const optional=['at_user','latitude','longitude','incident_id'];
const derived=['year','month','day','hour','minute','time_period'];
const internal=['record_id','record_revision','needs_manual_review','review_notes','source_file','imported_at','preprocessing_version','_source_row'];
const states={ready:'Ready to approve',needs_review:'Needs checking',duplicate:'Possible duplicate',conflict:'Existing record changed',approved:'Approved',skipped:'Not included',skip:'Will not be included'};
const label=k=>fields[k]||k.replaceAll('_',' ');
async function request(url,body){const r=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Could not complete the request. Please try again.');return d;}
function message(text,error=false){$('review-message').textContent=text;$('review-message').className=error?'upload-result-box error':'upload-result-box success';}
function leave(){return !dirty||confirm('You have unsaved changes. Leave this record without saving?');}
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
function list(){
 $('review-count').textContent=`${counts.ready||0} ready · ${counts.pending||0} awaiting approval`;
 $('draft-list').innerHTML=rows.map((d,i)=>`<button class="draft-choice ${d.id===selected?'selected':''}" aria-pressed="${d.id===selected}" data-id="${d.id}"><strong>${esc(d.cleaned.date||d.raw.date||'Date needed')} · ${esc(d.cleaned.barangay||'Unknown')}</strong><span>${esc(d.cleaned.vehicle_involved||'Unknown')}</span><span class="record-state ${d.state==='ready'?'is-ready':''}">${esc(states[d.state]||d.state)}</span></button>`).join('')||'<div class="empty-state"><strong>All done in this group</strong><p>Choose All records to see completed reviews, or return to Data.</p><a href="/data">Back to Data</a></div>';
 $('draft-list').querySelectorAll('button').forEach(b=>b.onclick=()=>{if(busy||!leave())return;dirty=false;selected=b.dataset.id;list();editor();});
 $('approve-ready').disabled=busy||dirty||!(counts.ready||counts.skip);
 $('approve-ready').textContent=counts.ready?`Approve ${counts.ready} ready record${counts.ready===1?'':'s'}`:counts.skip?'Apply exclusions':'Approve ready records';
 $('approval-help').textContent=dirty?'Save your changes before approval.':counts.ready?'Approval adds checked records to analysis. Unresolved records stay here.':counts.skip?'Apply your decisions to leave excluded records out of analysis.':'Check a record, tick the confirmation, and save your review to enable approval.';
}
function field(k,value){
 if(k==='severity')return `<label>${esc(label(k))}<select data-field="${k}"><option value="Unknown">Choose the confirmed outcome</option>${['Fatal','Non-Fatal','Damage-to-Property'].map(v=>`<option ${v===value?'selected':''}>${v}</option>`).join('')}</select></label>`;
 return `<label>${esc(label(k))}${k==='damage_injury'?`<textarea data-field="${k}" rows="3">${esc(value??'')}</textarea>`:`<input data-field="${esc(k)}" value="${esc(value??'')}" ${k==='date'?'type="date"':''}>`}</label>`;
}
function editor(){
 const d=rows.find(d=>d.id===selected);if(!d){$('draft-editor').innerHTML='<div class="empty-state"><h2>No records to check</h2><p>Use the filter to view completed records.</p></div>';return;}
 const extras=Object.keys(d.raw).filter(k=>![...basic,...optional,...derived,...internal].includes(k));
 const keys=[...basic,...optional,...extras];
 const comparisons=[...(d.duplicates||[])];if(d.existing)comparisons.unshift({record:d.existing,reason:'Current approved version'});
 const needsDecision=comparisons.length>0||d.decision;
 const values=ks=>ks.map(k=>field(k,d.cleaned[k]??d.raw[k])).join('');
 const changes=Object.keys(d.cleaned).filter(k=>!internal.includes(k)&&!derived.includes(k)&&String(d.original[k]??'')!==String(d.cleaned[k]??''));
 $('draft-editor').innerHTML=`
 <div class="table-toolbar"><h2>Check this record</h2><span class="record-state ${d.state==='ready'?'is-ready':''}">${esc(states[d.state]||d.state)}</span></div>
 <section class="cleaning-card" aria-label="Automatic preparation results"><h3>Automatically prepared</h3><p>Values are cleaned and checked. The fields below show the prepared record for your correction.</p><div class="derived-values">${derived.filter(k=>d.cleaned[k]!=null).map(k=>`<span>${esc(label(k))}<b>${esc(d.cleaned[k])}</b></span>`).join('')}</div>${d.suggestion?`<p class="severity-suggestion"><strong>Suggested severity: ${esc(d.suggestion)}.</strong> Check this against the injury description and confirm the final outcome below.</p>`:''}<details><summary>See what changed (${changes.length})</summary>${changes.length?`<div class="preview-scroll"><table class="preview-table"><thead><tr><th>Field</th><th>In your file</th><th>Prepared value</th></tr></thead><tbody>${changes.map(k=>`<tr><td>${esc(label(k))}</td><td>${esc(d.original[k]??'Empty')}</td><td>${esc(d.cleaned[k]??'Empty')}</td></tr>`).join('')}</tbody></table></div>`:'<p>No value changes were needed.</p>'}</details></section>
 ${d.issues.length?`<section class="attention-card"><h3>Please check</h3><ul class="review-issues">${d.issues.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></section>`:''}
 <form id="draft-form"><h3>Accident details</h3><div class="record-form-grid">${values(basic)}</div>
 <details class="optional-fields"><summary>Location and additional information</summary><div class="record-form-grid">${values([...optional,...extras])}</div><p class="hint">Extra information is kept with the record. It does not automatically become a new analysis factor.</p></details>
 ${comparisons.length?`<section class="attention-card"><h3>Check against existing records</h3><p>Compare the details before deciding whether this is another person involved or the same record.</p>${comparisons.map(c=>`<details class="duplicate-comparison"><summary>${esc(c.reason)} · ${esc(c.record.date)} · ${esc(c.record.barangay)}</summary><div class="preview-scroll"><table class="preview-table"><thead><tr><th>Field</th><th>This record</th><th>Existing record</th></tr></thead><tbody>${basic.map(k=>`<tr><td>${esc(label(k))}</td><td>${esc(d.cleaned[k]??'—')}</td><td>${esc(c.record[k]??'—')}</td></tr>`).join('')}</tbody></table></div></details>`).join('')}</section>`:''}
 <details class="record-options" ${needsDecision?'open':''}><summary>${comparisons.length?'What should happen to this record?':'Do not include this record'}</summary><label class="decision-label">Choose an action<select id="draft-decision"><option value="">${comparisons.length?'Choose after comparing':'Include after review'}</option><option value="skip">Do not include this record</option><option value="separate">Keep as a separate record</option>${comparisons.length?'<option value="update">Correct an existing record</option>':''}</select></label><label class="decision-label" id="target-label">Record to correct<select id="draft-target"><option value="">Select a record</option>${comparisons.map(c=>`<option value="${c.record.record_id}" data-revision="${c.record.record_revision}">${esc(c.record.date)} · ${esc(c.record.barangay)} · ${esc(c.record.vehicle_involved)} · ${esc(c.record.record_id.slice(-6))}</option>`).join('')}</select></label></details>
 <details class="original-values"><summary>View original submission</summary><dl class="record-details">${Object.entries(d.original).map(([k,v])=>`<dt>${esc(label(k))}</dt><dd>${esc(v??'—')}</dd>`).join('')}</dl></details>
 <div class="review-save"><label class="check-row"><input type="checkbox" id="draft-reviewed" ${d.reviewed?'checked':''}> I checked the details and confirmed the severity.</label><p class="hint" id="save-help">Saving rechecks your corrections. Approval is the next step.</p><div class="save-actions"><button class="btn" type="submit">Save review</button><button class="btn secondary" type="submit" id="save-next">Save and next →</button></div></div></form>`;
 $('draft-decision').value=d.decision||'';$('draft-target').value=d.target_id||'';
 const toggle=()=>{$('target-label').hidden=$('draft-decision').value!=='update';};toggle();
 $('draft-form').addEventListener('input',e=>{dirty=true;if(e.target.id!=='draft-reviewed')$('draft-reviewed').checked=false;$('save-help').textContent='Unsaved changes. Save to recheck and update the calculated fields.';list();});
 $('draft-decision').onchange=toggle;
 if(d.status!=='pending')$('draft-form').querySelectorAll('input,textarea,select,button').forEach(e=>e.disabled=true);
 $('draft-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;busy=true;list();const next=e.submitter.id==='save-next';$('draft-form').querySelectorAll('button').forEach(b=>b.disabled=true);
  const raw={...d.raw};$('draft-form').querySelectorAll('[data-field]').forEach(el=>raw[el.dataset.field]=el.value);const target=$('draft-target');$('draft-form').querySelectorAll('input,select,textarea').forEach(el=>el.disabled=true);
  try{const saved=await request(`/api/review/${batch}/${d.id}`,{revision:d.revision,raw,reviewed:$('draft-reviewed').checked,decision:$('draft-decision').value,target_id:target.value,target_revision:Number(target.selectedOptions[0]?.dataset.revision)||null});dirty=false;
   message(saved.state==='ready'?'Review saved. This record is ready to approve.':saved.state==='skip'?'Review saved. Apply exclusions to leave this record out of analysis.':'Review saved. This record still needs checking before approval.');
   if(next){const i=rows.findIndex(r=>r.id===selected);const upcoming=rows.slice(i+1).find(r=>r.status==='pending');selected=upcoming?.id||null;if(!upcoming&&page*25<total)page++;}
   await load();
  }catch(err){message(err.message,true);}finally{busy=false;if(rows.find(r=>r.id===selected)?.status==='pending')$('draft-form')?.querySelectorAll('input,select,textarea,button').forEach(el=>el.disabled=false);list();}
 };
}
async function load(){const data=await request('/api/review/'+batch+'?'+new URLSearchParams({page,state:$('review-filter').value}));rows=data.rows;fields=data.fields;page=data.page;total=data.total;counts=data.counts;if(!rows.some(d=>d.id===selected))selected=rows.find(d=>d.status==='pending')?.id||rows[0]?.id;$('review-page').textContent=`Page ${page} of ${Math.max(1,Math.ceil(total/25))}`;$('review-prev').disabled=page<=1;$('review-next').disabled=page*25>=total;list();editor();}
let currentFilter=$('review-filter').value;
$('review-filter').onchange=()=>{if(busy||!leave()){$('review-filter').value=currentFilter;return;}dirty=false;currentFilter=$('review-filter').value;page=1;load().catch(e=>message(e.message,true));};
function turn(delta){if(busy||!leave())return;dirty=false;page+=delta;load().catch(e=>message(e.message,true));}
$('review-prev').onclick=()=>turn(-1);$('review-next').onclick=()=>turn(1);
$('approve-ready').onclick=async()=>{if(busy||dirty||!confirm(`Add ${counts.ready||0} checked records to analysis and apply ${counts.skip||0} exclusions? Records that need checking will stay pending.`))return;busy=true;list();try{const d=await request(`/api/review/${batch}/approve`,{approved:true});message(`${d.added} added · ${d.updated} updated · ${d.skipped} not included · ${d.pending} still pending. Analysis now uses ${d.total} records.`);try{localStorage.setItem('ccdrmc-data-updated',String(Date.now()));}catch(_){}await load();}catch(err){message(err.message,true);}finally{busy=false;list();}};
load().catch(e=>message(e.message,true));
})();
