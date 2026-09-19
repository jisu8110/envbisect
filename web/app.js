'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = '', selected = localStorage.getItem('envbisect-run') || '', active = null, current = null, signature = '', busy = false, formRun = '', formDirty = false;
$('budget').addEventListener('change',()=>{formDirty=true;});
const statusName = {RUNNING:'실험 진행 중',STOPPING:'중단 요청됨 · 진행 중 호출과 삭제를 기다립니다',CANCELLED:'사용자 중단',INCONCLUSIVE:'결론 보류',VERIFIED_FAILURE_CONDITION:'실패 조건 검증 완료',BASELINE_VERIFIED:'Baseline 확인 완료',REPRODUCED:'단일 world 재현 완료',ERROR:'실행 오류',UNATTACHED:'종료 기록 없음 · 다른 프로세스 실행 여부와 정리 확인 필요'};
function notice(text=''){ $('notice').textContent=text; $('notice').hidden=!text; }
async function api(path, body){
  const response=await fetch(path, body===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-EnvBisect-Token':token},body:JSON.stringify(body)});
  const data=await response.json(); if(!response.ok) throw new Error(data.error || `HTTP ${response.status}`); return data;
}
function badge(status){const cls=status==='PASS'?'pass':status==='FAIL'?'fail':['ERROR','CLEANUP_FAILED'].includes(status)?'error':['RUNNING','EXECUTING','EXECUTING_LOCAL'].includes(status)?'live':'neutral'; return `<span class="badge ${cls}">${esc(status)}</span>`;}
function collect(data){
  const worlds=new Map(), actions=[], groups=[], brackets=[]; let metadata={}, boundary=null, waiting=false;
  for(const event of data.events){const d=event.data;
    if(event.event==='run_started') metadata=d;
    if(event.event==='worlds_submitted'){groups.push({label:d.label,ids:d.worlds.map(w=>w.world_id)}); for(const w of d.worlds) worlds.set(w.world_id,{...w,phase:'QUEUED',based_on:d.based_on||'baseline-bad'});}
    if(event.event==='world_phase' && worlds.has(d.world_id)){const w=worlds.get(d.world_id);w.phases=[...(w.phases||[]),d.phase];Object.assign(w,d);}
    if(event.event==='world_completed' && worlds.has(d.world_id)) Object.assign(worlds.get(d.world_id),{observation:d.observation,valid:d.valid,validation_error:d.validation_error});
    if(event.event==='observations') for(const o of d.observations) if(worlds.has(o.world_id)){const w=worlds.get(o.world_id); if(w.valid===undefined) w.valid=['PASS','FAIL'].includes(o.status)&&o.deleted&&!o.error; w.observation=o;}
    if(event.event==='planner_waiting') waiting=true;
    if(event.event==='action'){actions.push(d);waiting=false;}
    if(event.event==='search_bracket') brackets.push(d);
    if(event.event==='verified_boundary') boundary=d;
  }
  boundary=boundary||data.summary?.boundary;
  return {worlds,actions,groups,metadata,boundary,brackets,waiting};
}
function worldCard(w, metadata){
  if(!w) return ''; const o=w.observation, f=w.factor_values, base=metadata.bundle?.bad_world?.factors||{}, changes=Object.keys(f).filter(k=>f[k]!==base[k]);
  const state=o?(w.valid?o.status:'ERROR'):w.phase==='QUEUED'?'QUEUED':current?.status==='CANCELLED'?'CANCELLED':'RUNNING';
  const label=w.world_id==='baseline-good'?'Known good 다시 실행':w.world_id==='baseline-bad'?'Reported bad 다시 실행':changes.length?changes.map(k=>`${k}: ${base[k]} → ${f[k]}`).join(' · '):'실패 조건 반복 대조';
  const clean=o?.deleted?'정리 완료':w.phase==='CLEANUP_FAILED'?'삭제 실패 · 확인 필요':w.phase==='CLEANING'?'정리 중':w.phase||'QUEUED';
  return `<article class="world ${state.toLowerCase()}"><div class="world-top"><span class="world-id">${esc(w.world_id)}</span>${badge(state)}</div><div class="world-body"><div class="intervention">${esc(label)}</div><div class="fixed">Node ${esc(f.node)} · ${esc(f.size)} bytes<br>${esc(f.allocation)} / ${esc(f.length)} / Uint${esc(f.width)}</div><div class="lifecycle">${esc(Presentation.lifecycle(w,metadata.backend))}<br>${w.sandbox_id?'ID '+esc(w.sandbox_id.slice(0,8))+' · ':''}${esc(o?.deleted?'cleanup verified':clean)}</div><details id="detail-${esc(w.world_id)}"><summary>증거와 실행 출처 보기</summary><pre>${esc(JSON.stringify({based_on:w.based_on,changed_factors:changes,fixed_factors:Object.fromEntries(Object.entries(f).filter(([k])=>!changes.includes(k))),sandbox_id:w.sandbox_id,sandbox_name:w.sandbox_name,auto_destroy_at:w.auto_destroy_at,command:w.command,exit_code:o?.exit_code,evidence:o?.evidence,cleanup:o?.deleted,validation_error:w.validation_error},null,2))}</pre></details></div></article>`;
}
function render(data){
  current=data; const s=collect(data), m=s.metadata, rows=[...s.worlds.values()], valid=rows.filter(w=>w.valid), isRules=m.planner==='rules';
  if(formRun!==data.run_id && m.backend){if(!formDirty){$('budget').value=m.limits?.max_worlds||80;}formRun=data.run_id;}
  $('view-mode').className='badge '+(data.active?'live':'neutral'); $('view-mode').textContent=`${data.mode} · ${(m.backend||'—').toUpperCase()} · ${m.smoke?'MANUAL / NO LLM':isRules?'RULES / NOT AI':m.planner==='openai'?'LLM':'—'}`;
  $('run-status').textContent=statusName[data.status]||data.status;
  const start=data.events.find(e=>e.event==='run_started')?.time;
  const elapsed=data.summary?.elapsed_seconds??(start?Math.max(0,(Date.now()-Date.parse(start))/1000):0);
  $('metrics').textContent=`${rows.length} worlds / ${m.limits?.max_worlds??'—'} · ${s.groups.length} batches · ${Math.floor(elapsed)}s`;
  const opened=[...document.querySelectorAll('details[open]')].map(e=>e.id);
  const bases=s.groups.filter(g=>g.label==='baseline').flatMap(g=>g.ids).map(id=>s.worlds.get(id));
  $('baseline').innerHTML=bases.length?bases.map(w=>worldCard(w,m)).join(''):'<div class="placeholder">Baseline 실행을 기다리고 있습니다.</div>';
  $('baseline-status').textContent=bases.length===2&&bases.every(w=>w.valid)?'REPRODUCED':bases.length?'EXECUTING':'WAITING';
  const rounds=s.groups.filter(g=>g.label.startsWith('round')||g.label==='reproduce');
  $('experiments').innerHTML=rounds.length?rounds.map(g=>{const a=s.actions.filter(a=>a.action==='COMPARE')[Number(g.label.replace('round',''))-1];return `<div class="round"><div class="round-heading"><span>${esc(g.label.toUpperCase())} / ${g.ids.length} INDEPENDENT WORLDS</span><span>${isRules?'RULE-SELECTED':'PLANNER-SELECTED'}</span></div>${a?`<p class="reason">${esc(a.reason)}</p>`:''}<div class="world-grid">${g.ids.map(id=>worldCard(s.worlds.get(id),m)).join('')}</div></div>`;}).join(''):'<div class="placeholder">실행 증거를 읽고 다음 실험을 선택하면 표시됩니다.</div>';
  const search=s.actions.find(a=>a.action==='SEARCH_BOUNDARY'), action=search||s.actions.at(-1);
  $('next-action').innerHTML=decisionHTML(data);
  const probes=s.groups.filter(g=>['expand','narrow','confirm'].includes(g.label)).flatMap(g=>g.ids).map(id=>s.worlds.get(id));
  if(probes.length){
    const b=s.boundary||s.brackets.at(-1); const points=probes.filter(w=>w.valid).map(w=>({x:Number(w.factor_values.size),status:w.observation.status,id:w.world_id}));
    const x=n=>40+Math.log10(Math.max(1,n))/5*900;
    $('boundary').innerHTML=`${b?`<div class="bracket"><div class="endpoint">${Number(b.fail).toLocaleString()}<small>관찰된 FAIL · bytes</small></div><span class="arrow">→</span><div class="endpoint">${Number(b.pass).toLocaleString()}<small>관찰된 PASS · bytes</small></div><span class="muted">${s.boundary?'각 끝점 5회 새 실행 확인':b.confirming?'인접 조건 발견 · 반복 검증 중':'실행한 probe로 좁힌 구간'}</span></div>`:'<p class="muted">실패 seed에서 범위를 확대하며 통과 조건을 찾는 중입니다.</p>'}<svg class="chart" viewBox="0 0 980 105" role="img" aria-label="실제 실행된 입력 크기와 PASS FAIL 관찰, 로그 축"><line x1="40" x2="940" y1="53" y2="53"/>${[1,10,100,1000,10000,100000].map(n=>`<line x1="${x(n)}" x2="${x(n)}" y1="48" y2="60"/><text x="${x(n)}" y="85" text-anchor="middle">${n.toLocaleString()}</text>`).join('')}${points.map(p=>`<circle class="${p.status.toLowerCase()}" cx="${x(p.x)}" cy="${p.status==='FAIL'?39:61}" r="4"><title>${esc(p.id)}: ${p.x} ${p.status}</title></circle>`).join('')}</svg><div class="legend"><span>FAIL</span><span>PASS</span><span>입력 크기 · 로그 축 / 점은 실제 관찰만 표시</span></div><div class="probe-list">${probes.map(w=>`<span class="probe ${w.valid?w.observation.status.toLowerCase():'active'}" title="${esc(w.world_id)}">${Number(w.factor_values.size).toLocaleString()} ${w.valid?w.observation.status:w.observation?'ERROR':'…'}</span>`).join('')}</div><p class="fine">관찰하지 않은 구간의 결과는 추정해서 칠하지 않습니다. 단일 전환 가정과 고정 조건 아래에서만 탐색합니다.</p>`;
  }else $('boundary').innerHTML='<div class="placeholder">숫자 축 탐색이 선택되면 실행 결과가 이곳에 나타납니다.</div>';
  const b=s.boundary; $('result-title').textContent=b?'확인된 실패 조건과 실행 증거':data.active?'검증이 진행 중입니다.':'검증 가능한 결과를 남깁니다.';
  $('result-badge').textContent=b?'FAILURE CONDITION VERIFIED':data.status==='REPRODUCED'?'WORLD REPRODUCED':'NOT VERIFIED'; $('result-badge').className='badge '+(b?'pass':'neutral');
  $('result').innerHTML=b?`<div class="result-grid"><div class="result-stat"><span class="tiny">OBSERVED ADJACENT TRANSITION</span><strong>${Number(b.fail).toLocaleString()} → ${Number(b.pass).toLocaleString()}</strong><p>FAIL → PASS · bytes<br>각 끝점 ${b.fresh_repeats_per_endpoint}회 새 실행</p></div><div class="result-stat"><span class="tiny">FIXED CONDITIONS</span><p>${Object.entries(b.fixed).map(([k,v])=>`${esc(k)}: ${esc(v)}`).join('<br>')}</p></div><div class="result-stat"><span class="tiny">TRACEABLE EXECUTION</span><strong>${rows.length} worlds</strong><p>${valid.filter(w=>w.observation.deleted).length}개 결과 검증·정리 완료<br>${s.groups.length} batches · ${s.actions.length} actions</p></div></div><details id="references"><summary>반복 검증 observation ID</summary><pre>${esc(b.confirmation_world_ids.join('\n'))}</pre></details>`:`<p class="muted">${esc(data.summary?.error||'결론에 앞서 실행 증거를 수집합니다.')}</p>`;
  if(data.status==='STOPPING') notice('안전하게 중단 중입니다. 새 실험은 시작하지 않으며, 진행 중인 호출이 끝난 뒤 sandbox를 삭제합니다. 터미널을 강제 종료하지 마세요.');
  else if(['ERROR','INCONCLUSIVE','UNATTACHED','CANCELLED'].includes(data.status)) notice(data.summary?.error||'이 서버가 관리하는 활성 실행이 아니며 종료 기록이 없습니다. 다른 터미널의 실행 여부와 sandbox 정리 상태를 확인하세요.'); else notice();
  for(const id of opened){const el=$(id);if(el)el.open=true;}
  $('download').disabled=!data.events.length; const fail=valid.find(w=>w.observation.status==='FAIL'&&(!b||w.factor_values.size===b.fail));
  const remote=data.summary?.backend==='daytona';
  $('reproduce').disabled=Boolean(active)||!remote||!fail; $('copy').disabled=!remote||!fail;
  $('reproduce').title=remote?'Daytona에서 같은 조건 하나를 재실행 · LLM 호출 없음':'Local 기록은 조회만 가능합니다';
  $('copy').dataset.world=fail?.world_id||''; $('reproduce').dataset.world=fail?.world_id||'';
  renderPresentation();
}
async function poll(){
  if(busy)return; busy=true;
  try{const status=await api('/api/status');token=status.csrf;active=status.active_id;$('connection').textContent='LOCAL SERVER CONNECTED';
    $('start').disabled=Boolean(active)||starting;$('start').innerHTML=active?'실험 진행 중':starting?'시작 요청 중…':'실험 시작 ↗';$('stop').disabled=!active;
    $('present-stop').disabled=!active;
    $('budget').disabled=Boolean(active)||starting;$('issue-url').disabled=Boolean(active)||starting;
    if(!selected && active){selected=active;localStorage.setItem('envbisect-run',selected);}
    const historyKey=status.history.map(r=>r.id+r.status).join('|');
    if($('history').dataset.key!==historyKey){$('history').innerHTML='<option value="">새 실험 준비</option>'+status.history.map(r=>`<option value="${esc(r.id)}">${esc(r.id)} · ${esc(r.status)}</option>`).join('');$('history').dataset.key=historyKey;}
    $('history').value=selected;
    if(selected){const data=await api('/api/run?id='+encodeURIComponent(selected));const sig=data.run_id+data.events.length+data.status+Boolean(data.summary)+(data.active?Math.floor(Date.now()/5000):'');if(sig!==signature){signature=sig;render(data);}}
  }catch(e){$('connection').textContent='SERVER DISCONNECTED';notice('서버 연결을 확인해 주세요. '+e.message+' · 새로고침은 새 실험을 시작하지 않습니다.');}
  finally{busy=false;}
}
let starting=false;
const demoIssueUrl=$('issue-url').defaultValue;
function issueError(message=''){$('issue-error').textContent=message;$('issue-feedback').hidden=!message;$('issue-url').setAttribute('aria-invalid',String(Boolean(message)));}
$('issue-url').addEventListener('input',()=>issueError());
$('issue-reset').addEventListener('click',()=>{$('issue-url').value=demoIssueUrl;issueError();$('issue-url').focus();});
$('experiment-form').addEventListener('submit',async e=>{
  e.preventDefault();if(active||starting)return;
  const issueUrl=$('issue-url').value.trim().replace(/\/+$/,'');
  if(issueUrl!==demoIssueUrl){issueError('아직 지원하지 않는 링크입니다. 현재는 데모 이슈로 동작을 확인해 보세요.');$('issue-url').focus();return;}
  const budget=Number($('budget').value);
  if(!Number.isInteger(budget)||budget<2||budget>100){notice('최대 worlds는 2~100 사이의 정수로 입력해 주세요.');return;}
  issueError();starting=true;$('start').disabled=true;
  try{const d=await api('/api/start',{issue_url:issueUrl,max_worlds:budget,seconds:900});active=d.run_id;selected=d.run_id;formDirty=false;localStorage.setItem('envbisect-run',selected);signature='';}
  catch(error){notice(error.message);}
  finally{starting=false;$('start').disabled=Boolean(active);}
  await poll();
});
$('stop').addEventListener('click',async()=>{if(!active)return;try{await api('/api/stop',{run_id:active});selected=active;localStorage.setItem('envbisect-run',selected);signature='';await poll();}catch(e){notice(e.message);}});
$('history').addEventListener('change',()=>{selected=$('history').value;formDirty=false;localStorage.setItem('envbisect-run',selected);signature='';if(!selected){location.reload();return;}poll();});
$('download').addEventListener('click',()=>{if(selected)location.href='/api/evidence?id='+encodeURIComponent(selected);});
$('reproduce').addEventListener('click',async()=>{if(current?.summary?.backend!=='daytona')return;try{const d=await api('/api/start',{source_run:selected,source_world:$('reproduce').dataset.world,max_worlds:2,seconds:300});selected=d.run_id;localStorage.setItem('envbisect-run',selected);signature='';poll();}catch(e){notice(e.message);}});
$('copy').addEventListener('click',async()=>{if(current?.summary?.backend!=='daytona')return;const command=`.venv\\Scripts\\python demo.py --backend daytona --reproduce ${selected} --world ${$('copy').dataset.world}`;try{await navigator.clipboard.writeText(command);$('copy').textContent='복사 완료';setTimeout(()=>$('copy').textContent='재현 명령 복사',1800);}catch{notice('데모 폴더에서 실행할 명령:\n'+command);}});
let presentationMode=false, scene=0;
const scenes=['Incident','Baseline','Controlled Experiment','Next Decision','Verified Boundary','Evidence Package'];
function factorValue(factor,value){return esc(factor==='size'?Number(value).toLocaleString()+' bytes':String(value));}
function decisionHTML(data){
  const d=Presentation.decision(data.events);
  if(!d)return '<p>아직 다음 실험을 선택할 실행 증거가 없습니다.</p>';
  const a=d.action, planner=data.events.find(e=>e.event==='run_started')?.data.planner;
  let evidence=d.pair?`<div class="evidence-pair"><div>${factorValue(d.pair.factor,d.pair.fail.factors[d.pair.factor])} ${badge('FAIL')}</div><div>${factorValue(d.pair.factor,d.pair.pass.factors[d.pair.factor])} ${badge('PASS')}</div></div><p>Only ${esc(d.pair.factor)} changed. · 다른 입력 조건 동일</p>`:
    `<div class="evidence-pair">${d.cited.slice(0,2).map(o=>`<div>${esc(Object.entries(o.factors).map(([k,v])=>k+'='+v).join(' · '))} ${badge(o.status)}</div>`).join('')||'인용한 실행 증거를 원문에서 확인하세요.'}</div><p>단일 조건의 FAIL/PASS 대조는 확인되지 않았습니다.</p>`;
  return `<span class="tiny">${planner==='openai'?'LLM SELECTED':'RULES · NOT AI'}</span>${evidence}<strong>→ ${esc(a.action)}${a.factor?.length?'('+esc(String(a.factor))+')':''}</strong><details class="decision-detail"><summary>선택 근거·world ID·고정 조건</summary><pre>${esc(JSON.stringify({reason:a.reason,cited_worlds:d.cited.map(o=>o.world_id),fixed:a.fixed},null,2))}</pre></details>`;
}
function renderPresentation(){
  const data=current, s=data?collect(data):null, m=s?.metadata||{}, b=s?.boundary;
  $('present-mode').textContent=data?`${data.mode} · ${(m.backend||'unknown').toUpperCase()} · ${m.smoke?'MANUAL / NO LLM':m.planner==='openai'?'LLM':'RULES / NOT AI'}`:'NO RUN SELECTED';
  $('present-state').textContent=data?statusName[data.status]||data.status:'기록을 선택하면 실제 증거를 보여줍니다';
  $('role-strip').textContent=`${m.planner==='rules'?'Rules':'Planner'} chooses → Engine validates → ${m.backend==='local'?'Local processes execute (not sandboxed)':'Daytona executes isolated worlds'} → Oracle decides PASS / FAIL`;
  $('scene-count').textContent=`0${scene+1} / 06 · ${scenes[scene]}`;
  $('scene-prev').disabled=scene===0;$('scene-next').disabled=scene===scenes.length-1;
  let content='';
  if(scene===0) content='<div class="problem-chain"><div><span class="tiny">CI</span><h2>Something failed.</h2></div><div><span class="tiny">AI HYPOTHESIS · 설명을 위한 예시</span><h2>“Probably a runtime regression.”</h2></div><div><span class="tiny">ENGINEERING DECISION</span><h2>“아마”만으로 롤백할 수 있을까요?</h2></div></div><p class="scene-thesis">누군가는 조건을 바꿔 <em>직접 확인</em>해야 합니다.</p><p>EnvBisect는 다음 실험을 선택하고 실행해, 가설과 증거 사이를 연결합니다.</p>';
  else if(!data) content='<div class="placeholder">워크스페이스에서 실행 기록을 선택하거나 실험을 시작하세요. 결과를 미리 만들어 표시하지 않습니다.</div>';
  else if(scene===1){const worlds=[...s.worlds.values()].filter(w=>['baseline-good','baseline-bad'].includes(w.world_id));content='<p>같은 8-byte 입력, 같은 옵션. 처음 알려진 차이는 런타임 버전입니다.</p><div class="world-grid two">'+worlds.map(w=>worldCard(w,m)).join('')+'</div>';}
  else if(scene===2){
    const rows=data.summary?.observations||[...s.worlds.values()].filter(w=>w.valid).map(w=>({...w.observation,factors:w.factor_values}));
    const pairs=['width','allocation','length','size'].map(axis=>Presentation.contrast(rows,axis)).filter(Boolean);
    content='<p>결과가 달라진 비교만 요약합니다. 각 쌍은 표시된 조건 하나만 다릅니다.</p>'+(pairs.length?`<div class="contrast-grid">${pairs.map(p=>`<article class="contrast"><span class="tiny">${esc(p.factor)} CHANGED THE RESULT</span><h2>${factorValue(p.factor,p.fail.factors[p.factor])} ${badge('FAIL')} → ${factorValue(p.factor,p.pass.factors[p.factor])} ${badge('PASS')}</h2><details><summary>두 실행과 고정 조건</summary>${[p.fail,p.pass].map(o=>worldCard(s.worlds.get(o.world_id),m)).join('')}</details></article>`).join('')}</div>`:'<div class="placeholder">단일 조건 변경으로 결과가 달라진 유효한 비교가 아직 없습니다.</div>');
    const example=[...s.worlds.values()].find(w=>w.world_id.startsWith('round')&&w.observation);
    if(example)content+=`<p class="proof-ribbon">${esc(Presentation.lifecycle(example,m.backend))}${example.sandbox_id?' · ID '+esc(example.sandbox_id.slice(0,8)):''}</p>`;
  }
  else if(scene===3)content='<p class="scene-thesis">방금 얻은 증거가<br><em>다음 실험을 바꿉니다.</em></p><div class="decision spotlight">'+decisionHTML(data)+'</div><p>선택 당시 이미 존재했던 관찰만 표시합니다. 이후 탐색 결과를 과거의 근거로 사용하지 않습니다.</p>';
  else if(scene===4)content=b?`<p>LLM은 축을 고릅니다. 후보 생성과 반복 검증은 엔진이 담당합니다.</p><div class="hero-boundary"><div>${factorValue(b.factor,b.fail)}${badge('FAIL')}</div><span>→</span><div>${factorValue(b.factor,b.pass)}${badge('PASS')}</div></div><p class="scene-thesis">각 조건 <em>${Number(b.fresh_repeats_per_endpoint)}회</em> 새 실행 확인</p><p>${esc(Object.entries(b.fixed).map(([k,v])=>k+'='+v).join(' · '))}</p><p class="fine">${data.status==='VERIFIED_FAILURE_CONDITION'?'관찰한 고정 조건의 인접 경계입니다.':'경계 관찰은 있으나 실행 전체가 확정 완료된 것은 아닙니다.'} 전역 단조성이나 root cause를 증명하지 않습니다.</p>`:`<div class="placeholder"><h2>아직 검증된 경계가 없습니다.</h2><p>${esc(statusName[data.status]||data.status)}</p><p>${esc(data.summary?.error||'실제 탐색·반복 검증이 완료되면 표시됩니다.')}</p></div>`;
  else content=`<p class="scene-thesis">설명이 아니라,<br><em>다시 실행할 수 있는 증거.</em></p><div class="package-summary"><span>조건과 실행 명령</span><span>PASS / FAIL 관찰</span><span>실행 출처와 정리 상태</span><span>실험 선택 이력</span></div><p>${data.summary?.valid_observations??'진행 중'} validated observations · ${esc(data.status)}</p><button id="present-download">증거 JSON 내려받기 ↓</button><p class="fine">${m.backend==='local'?'이 기록은 로컬 실행이며 Daytona sandbox 증거가 아닙니다.':'Daytona 생성·실행·삭제 기록은 증거 파일에서 확인할 수 있습니다.'}</p>`;
  // Preserve opened provenance while live polling updates the slide.
  const opened=[...$('scene-content').querySelectorAll('details[open]')].map(e=>e.querySelector('summary')?.textContent);
  let detailNumber=0;
  $('scene-content').innerHTML=`<p class="eyebrow">${scenes[scene]}</p>${content}`.replace(/id="detail-/g,()=>`id="present-${detailNumber++}-`);
  for(const d of $('scene-content').querySelectorAll('details'))if(opened.includes(d.querySelector('summary')?.textContent))d.open=true;
  $('present-download')?.addEventListener('click',()=>{location.href='/api/evidence?id='+encodeURIComponent(selected);});
}
function setPresentation(on){presentationMode=on;document.body.classList.toggle('presenting',on);$('presentation').hidden=!on;$('workspace').hidden=on;$('presentation-toggle').setAttribute('aria-pressed',String(on));$('presentation-toggle').textContent=on?'워크스페이스로 돌아가기':'발표 모드';renderPresentation();}
$('presentation-toggle').addEventListener('click',()=>setPresentation(!presentationMode));
$('scene-prev').addEventListener('click',()=>{scene=Math.max(0,scene-1);renderPresentation();});
$('scene-next').addEventListener('click',()=>{scene=Math.min(scenes.length-1,scene+1);renderPresentation();});
document.addEventListener('keydown',e=>{if(!presentationMode||!['ArrowLeft','ArrowRight'].includes(e.key)||/INPUT|SELECT|TEXTAREA/.test(e.target.tagName))return;e.preventDefault();scene=Math.max(0,Math.min(5,scene+(e.key==='ArrowRight'?1:-1)));renderPresentation();});
$('present-stop').addEventListener('click',()=>$('stop').click());
poll();setInterval(poll,1200);
