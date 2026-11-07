// ATLAS Outcome Engine V3.
// Evaluates only *closed* MEXC candles in chronological order. It does not
// infer fills, actual trades or profitability from OHLC alone.
const API='https://contract.mexc.com/api/v1/contract/kline/';
const TRACK=new Set(['WAIT_ENTRY','ENTRY_OBSERVED','TP1_OBSERVED']);
const TERMINAL=new Set(['TP2_OBSERVED','SL_OBSERVED','SL_AFTER_TP1','EXPIRED',
 'UNRESOLVED_EXPIRED','TP1_ONLY_EXPIRED','AMBIGUOUS','AMBIGUOUS_POST_TP1','DATA_GAP']);
function n(x){if(x===null||x===undefined||x==='')return null;const y=Number(x);return Number.isFinite(y)?y:null;}
function event(kind,t,price,reason){return {kind,at:new Date(t).toISOString(),price,reason:reason||null};}
export function evaluateClosedCandles(m,bars,now,intervalMs){
 const created=Date.parse(m.created_at),expiry=Date.parse(m.valid_until),current=Date.parse(now);
 if(!Number.isFinite(created)||!Number.isFinite(expiry)||!Number.isFinite(current)||intervalMs<=0)throw Error('bad monitoring timestamps');
 let status=m.status,last=m.last_candle_at?Date.parse(m.last_candle_at):null;
 let quality=m.outcome_quality||null,events=[],processed=0;
 if(!TRACK.has(status))return {status,lastCandleAt:m.last_candle_at||null,quality,events,processed};
 const rows=bars.filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.h)&&Number.isFinite(x.l)&&x.h>=x.l&&Number.isFinite(x.c))
  .sort((a,b)=>a.t-b.t);
 for(const c of rows){
  // Ignore candles overlapping the publication moment; they contain pre-alert prices.
  if(c.t<created||c.t+intervalMs>current||last!==null&&c.t<=last)continue;
  if(c.t+intervalMs>expiry)break;
  // Missing a full candle means intraperiod ordering is no longer observable.
  const previous=last===null?Math.ceil(created/intervalMs)*intervalMs-intervalMs:last;
  if(c.t-previous>1.5*intervalMs){
   status='DATA_GAP';quality='missing_closed_candles';
   events.push(event('DATA_GAP',c.t,null,'Missing candle(s) in post-publication history'));
   break;
  }
  last=c.t;processed++;quality=intervalMs===60000?'closed_1m_candles':'closed_15m_candles';
  const entry=c.h>=m.entry_low&&c.l<=m.entry_high;
  const stop=m.direction==='LONG'?c.l<=m.stop:c.h>=m.stop;
  const tp1=m.direction==='LONG'?c.h>=m.tp1:c.l<=m.tp1;
  const tp2=m.tp2!==null&&m.tp2!==undefined&&(m.direction==='LONG'?c.h>=m.tp2:c.l<=m.tp2);
  if(status==='WAIT_ENTRY'){
   if(!entry)continue;
   if(stop||tp1||tp2){
    status='AMBIGUOUS';quality='same_candle_entry_and_exit';
    events.push(event('AMBIGUOUS',c.t+intervalMs,null,'Entry and target/stop in same candle: unknown intrabar ordering'));
    break;
   }
   status='ENTRY_OBSERVED';
   events.push(event('ENTRY_OBSERVED',c.t+intervalMs,m.direction==='LONG'?m.entry_low:m.entry_high,
    'Entry zone overlapped closed candle, NOT a confirmed fill'));
   continue;
  }
  if(status==='ENTRY_OBSERVED'&&stop&&(tp1||tp2)){
   status='AMBIGUOUS';quality='stop_and_target_same_candle';
   events.push(event('AMBIGUOUS',c.t+intervalMs,null,'Stop and target hit within same candle'));
   break;
  }
  if(status==='TP1_OBSERVED'&&stop&&tp2){
   status='AMBIGUOUS_POST_TP1';quality='stop_and_tp2_same_candle';
   events.push(event('AMBIGUOUS_POST_TP1',c.t+intervalMs,null,'SL and TP2 hit in same post-TP1 candle'));
   break;
  }
  if(stop){
   status=status==='TP1_OBSERVED'?'SL_AFTER_TP1':'SL_OBSERVED';
   events.push(event(status,c.t+intervalMs,m.stop));
   break;
  }
  if(tp1&&status==='ENTRY_OBSERVED'){
   status='TP1_OBSERVED';
   events.push(event('TP1_OBSERVED',c.t+intervalMs,m.tp1));
  }
  if(tp2&&(status==='TP1_OBSERVED')){
   status='TP2_OBSERVED';
   events.push(event('TP2_OBSERVED',c.t+intervalMs,m.tp2));
   break;
  }
 }
 if(TRACK.has(status)&&expiry<current){
  // Only expire when the data is current enough. Don't silently settle a stale feed.
  const requiredLast=Math.floor((expiry-intervalMs)/intervalMs)*intervalMs;
  if(last!==null&&last>=requiredLast){
   status=status==='WAIT_ENTRY'?'EXPIRED':status==='TP1_OBSERVED'?'TP1_ONLY_EXPIRED':'UNRESOLVED_EXPIRED';
   events.push(event(status,expiry,null,'No subsequent resolved price-level observation before expiry'));
  }
 }
 return {status,lastCandleAt:last===null?m.last_candle_at||null:new Date(last).toISOString(),quality,events,processed};
}
async function fetchBars(m,now){
 const ms=m.bucket==='SWING_TOP_PICK'?900000:60000;
 const interval=ms===60000?'Min1':'Min15',nowSecs=Math.floor(now/1000);
 const publishedSecs=Math.floor(Date.parse(m.created_at)/1000),lastSecs=m.last_candle_at?Math.floor(Date.parse(m.last_candle_at)/1000):null;
 const start=Math.max(0,(lastSecs??publishedSecs)-2*ms/1000);
 const limitStart=nowSecs-450*ms/1000;
 // If source data is unavailable for the full required range, mark as a gap.
 if(start<limitStart)return {gap:true,intervalMs:ms,candles:[]};
 const url=API+encodeURIComponent(m.symbol)+'?interval='+interval+'&start='+Math.floor(start)+'&end='+nowSecs;
 const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(),11500);
 try{
  const r=await fetch(url,{headers:{accept:'application/json'},signal:ctrl.signal});
  if(!r.ok)throw Error('MEXC candles HTTP '+r.status);
  const body=await r.json();
  if(body.success===false||!Array.isArray(body.data?.time))throw Error('Invalid MEXC candle data');
  const d=body.data;
  const candles=d.time.map((v,i)=>({t:Number(v)*1000,o:n(d.open?.[i]),h:n(d.high?.[i]),l:n(d.low?.[i]),c:n(d.close?.[i])}));
  return {gap:false,intervalMs:ms,candles};
 }finally{clearTimeout(timer)}
}
async function recordEvent(env,m,x){
 const id=m.id+':'+x.kind;
 await env.DB.prepare("INSERT OR IGNORE INTO signal_events(id,signal_id,kind,symbol,direction,observed_price,observed_at,details_json) VALUES(?,?,?,?,?,?,?,?)")
 .bind(id,m.id,x.kind,m.symbol,m.direction,x.price,x.at,JSON.stringify({reason:x.reason,method:'closed_candles',source:m.source,quality:'price_level_only',not_a_fill:true})).run();
}
async function persist(env,m,result,now){
 let updates=['status=?','updated_at=?','last_candle_at=?','outcome_quality=?','monitor_error=NULL'];
 let p=[result.status,now,result.lastCandleAt,result.quality];
 for(const [kind,column] of [
  ['ENTRY_OBSERVED','entry_observed_at'],['TP1_OBSERVED','tp1_observed_at'],
  ['TP2_OBSERVED','tp2_observed_at'],['SL_OBSERVED','sl_observed_at'],['SL_AFTER_TP1','sl_observed_at']
 ]){
  const found=result.events.find(e=>e.kind===kind);
  if(found){updates.push(column+'=COALESCE('+column+',?)');p.push(found.at)}
 }
 if(TERMINAL.has(result.status)){updates.push('ended_at=?');p.push(result.events.at(-1)?.at||now)}
 p.push(m.id,m.status,m.last_candle_at||'');
 const saved=await env.DB.prepare('UPDATE signal_monitors SET '+updates.join(',')+" WHERE id=? AND status=? AND COALESCE(last_candle_at,'')=?").bind(...p).run();
 if((saved.meta?.changes||0)<1)return 0;
 for(const e of result.events)await recordEvent(env,m,e);
 return result.events.length;
}
export async function runOutcomeEngine(env,{limit=18}={}){
 const now=new Date().toISOString();
 const list=await env.DB.prepare("SELECT * FROM signal_monitors WHERE status IN ('WAIT_ENTRY','ENTRY_OBSERVED','TP1_OBSERVED') ORDER BY COALESCE(last_candle_at,created_at) ASC LIMIT ?").bind(limit).all();
 let evaluated=0,scanned=0,events=0,errors=[];
 for(let i=0;i<(list.results||[]).length;i+=4){
  const chunk=list.results.slice(i,i+4);
  await Promise.all(chunk.map(async m=>{
   try{
    const d=await fetchBars(m,Date.now());
    let result;
    if(d.gap){
     result={status:'DATA_GAP',lastCandleAt:m.last_candle_at||null,quality:'insufficient_source_history',processed:0,
       events:[event('DATA_GAP',Date.now(),null,'Source historical window is insufficient')]};
    }else if(!d.candles.length){
     // Not a loss: mark source inability and retry on next iteration.
     throw Error('No candle data for '+m.symbol);
    }else result=evaluateClosedCandles(m,d.candles,now,d.intervalMs);
    events+=await persist(env,m,result,now);
    evaluated++;scanned+=result.processed;
   }catch(e){
    errors.push(m.symbol+': '+String(e).slice(0,125));
    await env.DB.prepare('UPDATE signal_monitors SET monitor_error=? WHERE id=?').bind(String(e).slice(0,180),m.id).run().catch(()=>{});
   }
  }));
 }
 const pending=await env.DB.prepare("SELECT count(*) AS n FROM signal_monitors WHERE status IN ('WAIT_ENTRY','ENTRY_OBSERVED','TP1_OBSERVED')").first();
 await env.DB.prepare("INSERT INTO outcome_health(id,last_attempt_at,last_success_at,last_error,evaluated_count,pending_count,scanned_candles) VALUES(1,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,last_success_at=COALESCE(excluded.last_success_at,outcome_health.last_success_at),last_error=excluded.last_error,evaluated_count=excluded.evaluated_count,pending_count=excluded.pending_count,scanned_candles=excluded.scanned_candles")
 .bind(now,errors.length?null:now,errors.length?errors.slice(0,4).join(' | '):null,evaluated,pending?.n||0,scanned).run();
 return {at:now,evaluated,pending:pending?.n||0,events,scanned,errors:errors.slice(0,5)};
}
export async function outcomeMetrics(env){
 const [pub,agg,sources,health]=await Promise.all([
  env.DB.prepare("SELECT count(*) AS total, sum(CASE WHEN is_trackable=1 THEN 1 ELSE 0 END) AS trackable FROM signal_publications").first(),
  env.DB.prepare("SELECT source, count(*) AS total, sum(CASE WHEN tp1_observed_at IS NOT NULL THEN 1 ELSE 0 END) AS tp1_first, sum(CASE WHEN status='SL_OBSERVED' AND tp1_observed_at IS NULL THEN 1 ELSE 0 END) AS sl_first, sum(CASE WHEN status IN ('AMBIGUOUS','AMBIGUOUS_POST_TP1','DATA_GAP') THEN 1 ELSE 0 END) AS inconclusive, sum(CASE WHEN status IN ('WAIT_ENTRY','ENTRY_OBSERVED','TP1_OBSERVED') THEN 1 ELSE 0 END) AS active, sum(CASE WHEN status IN ('EXPIRED','UNRESOLVED_EXPIRED','TP1_ONLY_EXPIRED') THEN 1 ELSE 0 END) AS expired FROM signal_monitors GROUP BY source").all(),
  env.DB.prepare("SELECT bucket,count(*) AS n FROM signal_publications GROUP BY bucket").all(),
  env.DB.prepare('SELECT * FROM outcome_health WHERE id=1').first()
 ]);
 const groups=(agg.results||[]).map(row=>({...row,decided:(row.tp1_first||0)+(row.sl_first||0),
  tp1FirstRate:(row.tp1_first||0)+(row.sl_first||0)?row.tp1_first/((row.tp1_first||0)+(row.sl_first||0)):null}));
 return new Response(JSON.stringify({publications:pub||{total:0,trackable:0},bySource:groups,
  publicationBuckets:sources.results||[],health:health||null,
  note:'TP1-first / SL-first only among price-level outcomes with unambiguous ordering. NOT filled trades, net PnL, or realized wins. Ambiguous/missing data excluded.'}),
  {headers:{'content-type':'application/json;charset=utf-8','cache-control':'no-store'}});
}
