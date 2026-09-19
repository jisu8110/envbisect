'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = '', selected = localStorage.getItem('envbisect-run') || '', active = null, current = null, signature = '', busy = false, formRun = '', formDirty = false, localNodeDir = '';
for(const id of ['backend','planner','budget']) $(id).addEventListener('change',()=>{formDirty=true;});
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
    if(event.event==='world_phase' && worlds.has(d.world_id)) Object.assign(worlds.get(d.world_id),d);
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
  return `<article class="world ${state.toLowerCase()}"><div class="world-top"><span class="world-id">${esc(w.world_id)}</span>${badge(state)}</div><div class="world-body"><div class="intervention">${esc(label)}</div><div class="fixed">Node ${esc(f.node)} · ${esc(f.size)} bytes<br>${esc(f.allocation)} / ${esc(f.length)} / Uint${esc(f.width)}</div><div class="lifecycle">${esc(metadata.backend==='local'?'LOCAL PROCESS':w.phase||'RECORDED EXECUTION')} · ${esc(clean)}${o?`<br>backingLength=${esc(o.evidence?.backingLength??'—')} · ${Number(o.duration_seconds).toFixed(2)}s`:''}</div><details id="detail-${esc(w.world_id)}"><summary>증거와 실행 출처 보기</summary><pre>${esc(JSON.stringify({based_on:w.based_on,changed_factors:changes,fixed_factors:Object.fromEntries(Object.entries(f).filter(([k])=>!changes.includes(k))),sandbox_id:w.sandbox_id,sandbox_name:w.sandbox_name,auto_destroy_at:w.auto_destroy_at,command:w.command,exit_code:o?.exit_code,evidence:o?.evidence,cleanup:o?.deleted,validation_error:w.validation_error},null,2))}</pre></details></div></article>`;
}
function render(data){
  current=data; const s=collect(data), m=s.metadata, rows=[...s.worlds.values()], valid=rows.filter(w=>w.valid), isRules=m.planner==='rules';
  if(formRun!==data.run_id && m.backend){if(!formDirty){$('backend').value=m.backend;$('planner').value=m.planner;$('budget').value=m.limits?.max_worlds||80;}formRun=data.run_id;}
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
  $('next-action').innerHTML=`<span class="tiny">${isRules?'RULES · NOT AI':'PLANNER DECISION'}${s.waiting&&data.active?' · THINKING':''}</span><strong>${action?esc(action.action+(action.factor?.length?' : '+String(action.factor):'')):'Waiting for evidence'}</strong><p>${action?esc(action.reason):'아직 다음 실험이 선택되지 않았습니다.'}</p>${search?`<p>고정 조건: ${esc(JSON.stringify(search.fixed))}</p>`:''}`;
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
  $('reproduce').disabled=Boolean(active)||!data.summary||!fail; $('copy').disabled=!data.summary||!fail;
  $('copy').dataset.world=fail?.world_id||''; $('reproduce').dataset.world=fail?.world_id||'';
}
async function poll(){
  if(busy)return; busy=true;
  try{const status=await api('/api/status');token=status.csrf;active=status.active_id;$('connection').textContent='LOCAL SERVER CONNECTED';
    $('backend').querySelector('[value="local"]').disabled=!status.local_available;localNodeDir=status.local_node_dir||'';
    $('start').disabled=Boolean(active);$('start').innerHTML=active?'실험 진행 중':(selected?'같은 입력으로 새 실행 ↗':'실험 시작 ↗');$('stop').disabled=!active;
    $('backend').disabled=Boolean(active);$('planner').disabled=Boolean(active);$('budget').disabled=Boolean(active);
    if(!selected && active){selected=active;localStorage.setItem('envbisect-run',selected);}
    const historyKey=status.history.map(r=>r.id+r.status).join('|');
    if($('history').dataset.key!==historyKey){$('history').innerHTML='<option value="">새 실험 준비</option>'+status.history.map(r=>`<option value="${esc(r.id)}">${esc(r.id)} · ${esc(r.status)}</option>`).join('');$('history').dataset.key=historyKey;}
    $('history').value=selected;
    if(selected){const data=await api('/api/run?id='+encodeURIComponent(selected));const sig=data.run_id+data.events.length+data.status+Boolean(data.summary)+(data.active?Math.floor(Date.now()/5000):'');if(sig!==signature){signature=sig;render(data);}}
  }catch(e){$('connection').textContent='SERVER DISCONNECTED';notice('서버 연결을 확인해 주세요. '+e.message+' · 새로고침은 새 실험을 시작하지 않습니다.');}
  finally{busy=false;}
}
$('start').addEventListener('click',async()=>{try{$('start').disabled=true;const d=await api('/api/start',{backend:$('backend').value,planner:$('planner').value,max_worlds:Number($('budget').value),seconds:900});selected=d.run_id;formDirty=false;localStorage.setItem('envbisect-run',selected);signature='';await poll();}catch(e){notice(e.message);$('start').disabled=false;}});
$('stop').addEventListener('click',async()=>{if(!active)return;try{await api('/api/stop',{run_id:active});selected=active;localStorage.setItem('envbisect-run',selected);signature='';await poll();}catch(e){notice(e.message);}});
$('history').addEventListener('change',()=>{selected=$('history').value;formDirty=false;localStorage.setItem('envbisect-run',selected);signature='';if(!selected){location.reload();return;}poll();});
$('download').addEventListener('click',()=>{if(selected)location.href='/api/evidence?id='+encodeURIComponent(selected);});
$('reproduce').addEventListener('click',async()=>{try{const d=await api('/api/start',{backend:current.summary.backend,planner:'rules',source_run:selected,source_world:$('reproduce').dataset.world,max_worlds:2,seconds:300});selected=d.run_id;localStorage.setItem('envbisect-run',selected);signature='';poll();}catch(e){notice(e.message);}});
$('copy').addEventListener('click',async()=>{const dir=current.summary.local_node_dir||localNodeDir;const suffix=current.summary.backend==='local'&&dir?` --node-dir "${dir}"`:'';const command=`.venv\\Scripts\\python demo.py --reproduce ${selected} --world ${$('copy').dataset.world}${suffix}`;try{await navigator.clipboard.writeText(command);$('copy').textContent='복사 완료';setTimeout(()=>$('copy').textContent='재현 명령 복사',1800);}catch{notice('데모 폴더에서 실행할 명령:\n'+command);}});
poll();setInterval(poll,1200);
