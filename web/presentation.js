/* Presentation projections never invent observations or change execution policy. */
const Presentation = (() => {
  const valid = o => o && ['PASS','FAIL'].includes(o.status) && o.deleted === true && !o.error;
  const differences = (a,b) => [...new Set([...Object.keys(a),...Object.keys(b)])].filter(k=>a[k]!==b[k]);
  function contrast(rows, axis=null, fixed=null) {
    const usable=rows.filter(o=>valid(o)&&o.factors).filter(o=>!fixed||Object.entries(fixed).every(([k,v])=>o.factors[k]===v));
    for(const fail of usable.filter(o=>o.status==='FAIL')) for(const pass of usable.filter(o=>o.status==='PASS')) {
      const changed=differences(fail.factors,pass.factors);
      if(changed.length===1 && (!axis||changed[0]===axis)) return {fail,pass,factor:changed[0]};
    }
    return null;
  }
  function decision(events) {
    const observed=new Map(), specs=new Map(), checks=new Map(); let last=null;
    for(const e of events) {
      const d=e.data;
      if(e.event==='worlds_submitted') for(const w of d.worlds) specs.set(w.world_id,w.factor_values);
      if(e.event==='world_completed') checks.set(d.observation.world_id,d.valid);
      // Raw observation events do not contain factors. Join the submitted spec,
      // and require its validation event before treating it as decision evidence.
      if(e.event==='observations') for(const o of d.observations) {
        const factors=o.factors||specs.get(o.world_id);
        if(valid(o)&&factors&&checks.get(o.world_id)!==false&&(o.factors||checks.get(o.world_id)===true)) observed.set(o.world_id,{...o,factors});
      }
      if(e.event==='action') {
        const cited=[...observed.values()].filter(o=>new RegExp('(^|[^\\w-])'+o.world_id.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'($|[^\\w-])').test(d.reason||''));
        const searchRows=d.values&&d.action==='SEARCH_BOUNDARY'?cited.filter(o=>o.factors[d.factor]>=d.values.min&&o.factors[d.factor]<=d.values.max).sort((a,b)=>Number(b.factors[d.factor]===d.values.seed_observed_bad)-Number(a.factors[d.factor]===d.values.seed_observed_bad)):cited;
        const pair=d.action==='SEARCH_BOUNDARY'?contrast(searchRows,d.factor,d.fixed):contrast(cited);
        last={action:d,cited,pair};
        if(d.action==='SEARCH_BOUNDARY') return last;
      }
    }
    return last;
  }
  function eligible(data) {
    const s=data?.summary, b=s?.boundary;
    if(data?.active || !s || s.backend!=='daytona' || s.planner!=='openai' || s.status!=='VERIFIED_FAILURE_CONDITION' || !s.planner_closed_loop || !b || s.smoke) return false;
    const rows=s.observations||[], phases=(data.events||[]).filter(e=>e.event==='world_phase').map(e=>e.data);
    const destroyed=new Set(phases.filter(p=>p.phase==='DESTROYED').map(p=>p.sandbox_id));
    const created=phases.filter(p=>p.phase==='CREATED');
    const confirmations=rows.filter(o=>(b.confirmation_world_ids||[]).includes(o.world_id));
    return s.actions?.at(-1)?.action==='STOP' && rows.length===s.worlds_submitted && rows.every(valid)
      && created.length===rows.length && created.every(p=>p.sandbox_id&&destroyed.has(p.sandbox_id))
      && ['FAIL','PASS'].every(status=>confirmations.filter(o=>o.status===status && o.factors[b.factor]===b[status.toLowerCase()] && Object.entries(b.fixed).every(([k,v])=>o.factors[k]===v)).length>=5);
  }
  function lifecycle(world,backend) {
    if(backend!=='daytona') return 'LOCAL PROCESS · '+(world.observation?.deleted?'TEMP CLEANED':'IN PROGRESS')+' · NOT A SANDBOX';
    const phases=world.phases||[];
    const stages=[['CREATED','CREATED'],['OBSERVED','EXECUTED'],['OBSERVED','EVIDENCE CAPTURED'],['DESTROYED','DESTROYED']];
    return 'DAYTONA WORLD · '+stages.map(([phase,label])=>phases.includes(phase)?label:'['+label+' pending]').join(' → ');
  }
  return {valid, differences, contrast, decision, eligible, lifecycle};
})();
if(typeof module!=='undefined') module.exports=Presentation;
