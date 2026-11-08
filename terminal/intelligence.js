// ATLAS V4: read-only, non-execution intelligence. Every metric states its provenance.
// These diagnostics must never alter scanner trade plans or trigger exchange orders.
const JSON_HEADERS={'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
const reply=(v,status=200)=>new Response(JSON.stringify(v),{status,headers:JSON_HEADERS});
const n=v=>v===null||v===undefined||v===''?null:(Number.isFinite(Number(v))?Number(v):null);
const avg=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null;
const median=a=>{if(!a.length)return null;const x=[...a].sort((a,b)=>a-b),m=x.length>>1;return x.length%2?x[m]:(x[m-1]+x[m])/2};
const rounded=(x,d=2)=>x===null||!Number.isFinite(x)?null:Number(x.toFixed(d));
const ageMinutes=t=>t&&Number.isFinite(Date.parse(t))?Math.max(0,(Date.now()-Date.parse(t))/60000):null;
const safeParse=(s,fallback)=>{try{return JSON.parse(s??'')}catch{return fallback}};
const viable=rows=>(Array.isArray(rows)?rows:[]).filter(x=>x&&typeof x.symbol==='string'&&n(x.price)>0&&n(x.changePct)!==null);

export function marketRegime(items,scanner={},scannerAge=null){
 const rows=viable(items),returns=rows.map(x=>n(x.changePct)),pct=returns.length?returns.filter(x=>x>0).length/returns.length:null;
 const btc=rows.find(x=>x.symbol==='BTC_USDT'),eth=rows.find(x=>x.symbol==='ETH_USDT');
 const br=btc?n(btc.changePct):null,er=eth?n(eth.changePct):null;
 const liquid=rows.filter(x=>n(x.turnover)>0).sort((a,b)=>b.turnover-a.turnover).slice(0,100);
 const medAbs=median(liquid.map(x=>Math.abs(n(x.changePct)||0)));
 const scannerBias=scannerAge!==null&&scannerAge<=45?scanner.regime:null;
 let regime='INSUFFICIENT_DATA';
 if(rows.length>=30&&br!==null&&er!==null){
  if(pct>=.6&&br>0&&er>0)regime='BULL_TREND_PROXY';
  else if(pct<=.4&&br<0&&er<0)regime='BEAR_TREND_PROXY';
  else regime='MIXED_OR_RANGE';
 }
 const highVol=medAbs!==null&&medAbs>=8;
 return {regime,highVolatility24h:highVol,breadthPositivePct:rounded(pct===null?null:100*pct,1),
  btcChange24hPct:br,ethChange24hPct:er,liquidTop100MedianAbsChange24hPct:rounded(medAbs),
  scannerBias:scannerBias||'UNVERIFIED_OR_STALE',scannerAgeMinutes:rounded(scannerAge,1),instruments:rows.length,
  method:'24h cross-sectional price breadth + BTC/ETH changes; scanner bias only when fresh',
  caveat:'Regime is descriptive, not trained AI, not a trade direction or a forecast.'};
}
export function anomalyRadar(items,limit=12){
 const rows=viable(items).filter(x=>n(x.turnover)>0);
 const liquidMedian=median(rows.map(x=>n(x.turnover)));
 const movementMedian=median(rows.map(x=>Math.abs(n(x.changePct))));
 if(rows.length<30||!liquidMedian||movementMedian===null)return {items:[],coverage:rows.length,ready:false};
 const picks=rows.filter(x=>x.turnover>=liquidMedian&&Math.abs(x.changePct)>=Math.max(7,2.2*movementMedian))
  .map(x=>({symbol:x.symbol,change24hPct:rounded(x.changePct),turnover24h:x.turnover,
   relativeTurnover:rounded(x.turnover/liquidMedian,1),
   anomalyScore:rounded(Math.abs(x.changePct)/Math.max(1,movementMedian),1)}))
  .sort((a,b)=>b.anomalyScore-a.anomalyScore).slice(0,Math.min(20,limit));
 return {items:picks,coverage:rows.length,ready:true,method:'24h absolute change vs cross-sectional median among above-median turnover contracts',
 note:'Not a real-time breakout, liquidation or manipulation detector.'};
}
const GROUPS={
 'Layer 1':['BTC','ETH','SOL','ADA','AVAX','NEAR','SUI','APT','TRX','TON','DOT','ATOM','ALGO','XRP','BNB'],
 'DeFi':['UNI','AAVE','CRV','COMP','MKR','LDO','DYDX','SNX','PENDLE','JUP','RUNE'],
 'Memes':['DOGE','SHIB','PEPE','WIF','BONK','FLOKI','BRETT'],
 'AI / Data':['FET','RENDER','RNDR','TAO','ARKM','GRT','WLD'],
 'Infrastructure':['LINK','FIL','AR','OP','ARB','INJ','TIA','IMX']
};
export function sectorRotation(items){
 const rows=viable(items),data=[];
 for(const [sector,symbols] of Object.entries(GROUPS)){
  const present=rows.filter(x=>symbols.includes(x.symbol.replace(/_USDT$/,'')));
  const changes=present.map(x=>n(x.changePct)).filter(x=>x!==null);
  if(changes.length>=3)data.push({sector,count:changes.length,meanChange24hPct:rounded(avg(changes)),positivePct:rounded(100*changes.filter(x=>x>0).length/changes.length,1)});
 }
 return {groups:data.sort((a,b)=>b.meanChange24hPct-a.meanChange24hPct),
  classifiedSymbols:Object.values(GROUPS).flat().length,coverage:'curated groups only',
  caveat:'Limited hand-curated classification; cross-sectional 24h rotation proxy, not institutional capital flows.'};
}
export function fundingRadar(items){
 const rows=viable(items).filter(x=>n(x.funding)!==null&&n(x.turnover)>0);
 const liquid=rows.sort((a,b)=>b.turnover-a.turnover).slice(0,150);
 return {coverage:rows.length,positiveFundingPct:rounded(liquid.length?100*liquid.filter(x=>x.funding>0).length/liquid.length:null,1),
  highAbsoluteFunding:liquid.map(x=>({symbol:x.symbol,fundingRate:x.funding,change24hPct:n(x.changePct)}))
    .sort((a,b)=>Math.abs(b.fundingRate)-Math.abs(a.fundingRate)).slice(0,8),
  openInterestAvailable:false,liquidationsAvailable:false,
  caveat:'Funding is a snapshot from MEXC and may be interval-specific. No OI/taker-flow/large-player inference.'};
}
export function signalLab(monitors=[],publications=[]){
 const valid=(monitors||[]).filter(x=>x&&x.id);
 const ambiguous=valid.filter(x=>['AMBIGUOUS','AMBIGUOUS_POST_TP1','DATA_GAP'].includes(x.status)||['AMBIGUOUS','DATA_GAP'].includes(x.outcome_quality));
 const clean=valid.filter(x=>!ambiguous.includes(x));
 const tp=clean.filter(x=>x.tp1_observed_at);
 const sl=clean.filter(x=>x.status==='SL_OBSERVED'&&!x.tp1_observed_at);
 const denominator=tp.length+sl.length;
 const groups={};
 for(const x of clean){
  const source=String(x.source||'unknown').slice(0,80),g=groups[source]??={source,tracked:0,tp1First:0,slFirst:0};
  g.tracked++;if(x.tp1_observed_at)g.tp1First++;else if(x.status==='SL_OBSERVED')g.slFirst++;
 }
 return {totalPublications:publications.length,tracked:valid.length,tp1ObservedFirst:tp.length,slObservedFirst:sl.length,
  ambiguousOrGapped:ambiguous.length,unambiguousResolved:denominator,
  tp1FirstRatePct:denominator?rounded(100*tp.length/denominator,1):null,
  bySource:Object.values(groups).map(g=>({...g,sampleSufficient:g.tp1First+g.slFirst>=30})),
  statisticallySufficient:denominator>=30,
  note:'Candle-observed TP1-first vs SL-first only; not actual fills, win probability, R, PnL or forward-tested strategy promotion.'};
}
export function signalReadiness(monitors=[]){
 const now=Date.now();
 return (monitors||[]).filter(x=>x&&x.id).slice(0,25).map(x=>{
  const score=n(x.score),age=Number.isFinite(Date.parse(x.created_at))?(now-Date.parse(x.created_at))/60000:null;
  const ready=['WAIT_ENTRY','ENTRY_OBSERVED','TP1_OBSERVED'].includes(x.status);
  return {symbol:x.symbol,source:x.source,direction:x.direction,status:x.status,
   score:score===null?null:rounded(score,1),grade:score===null?'UNRATED':score>=80?'A':score>=65?'B':'C',
   fresh:age!==null&&age>=0&&age<=120,monitorId:x.id,
   note:ready?'Monitoring price levels; not an open exchange position':'Historical observation'};
 });
}
export function riskPreview(p){
 const equity=n(p.equity),entry=n(p.entry),stop=n(p.stop),riskPct=n(p.riskPct),maxExposurePct=n(p.maxExposurePct??100);
 const direction=String(p.direction||'LONG').toUpperCase();
 if(![equity,entry,stop,riskPct,maxExposurePct].every(x=>x!==null)||equity<=0||entry<=0||stop<=0||riskPct<=0||riskPct>5||maxExposurePct<=0||maxExposurePct>100||!['LONG','SHORT'].includes(direction)||
 (direction==='LONG'&&stop>=entry)||(direction==='SHORT'&&stop<=entry))
  return {error:'Invalid equity/entry/stop/direction or riskPct (0–5%)/maxExposurePct (0–100%).',valid:false};
 const maxRisk=equity*riskPct/100,unitRisk=Math.abs(entry-stop);
 const uncappedQty=maxRisk/unitRisk,exposureQty=equity*maxExposurePct/100/entry,quantity=Math.min(uncappedQty,exposureQty);
 return {valid:true,equity,entry,stop,direction,riskPct,maxExposurePct,
  maxRiskAmount:rounded(maxRisk),units:rounded(quantity,8),notional:rounded(quantity*entry),
  modeledStopLoss:rounded(quantity*unitRisk),stopDistancePct:rounded(100*unitRisk/entry,3),
  exposureCapped:uncappedQty>exposureQty,method:'simple linear quantity with exposure cap',
  note:'Hypothetical calculation only; excludes fees, slippage, funding, gaps, liquidation and exchange contract multipliers. No order placement.'};
}
export function healthAudit({snapshotAt,scannerAt,outcomeAt,macroAt}={}){
 const sources={market:{ageMinutes:rounded(ageMinutes(snapshotAt),1),maxAgeMinutes:15},
  scanner:{ageMinutes:rounded(ageMinutes(scannerAt),1),maxAgeMinutes:45},
  outcomes:{ageMinutes:rounded(ageMinutes(outcomeAt),1),maxAgeMinutes:30},
  macro:{ageMinutes:rounded(ageMinutes(macroAt),1),maxAgeMinutes:45}};
 const failures=[];
 for(const [k,v] of Object.entries(sources)){v.status=v.ageMinutes===null?'UNKNOWN':v.ageMinutes>v.maxAgeMinutes?'STALE':'OK';if(v.status!=='OK')failures.push(k);}
 return {status:failures.length?'DEGRADED':'OK',sources,failures,note:'Fresh timestamps are necessary but do not prove successful scanner run, Telegram delivery or trade fills.'};
}
export function buildIntelligence(input={}){
 const items=safeParse(input.snapshot?.items_json,[]),scanner=safeParse(input.scanner?.market_context_json,{}),
  monitors=input.monitors||[],publications=input.publications||[];
 const scannerAge=ageMinutes(input.scanner?.source_updated_at);
 const health=healthAudit({snapshotAt:input.snapshot?.fetched_at,scannerAt:input.scanner?.source_updated_at,
  outcomeAt:input.outcome?.last_success_at,macroAt:input.macro?.checked_at});
 const data={version:'4.0.0-research',generatedAt:new Date().toISOString(),
  provenance:{market:'MEXC 24h REST snapshot in D1; periodically refreshed',signals:'Verified publications and D1 candle-level monitors',
   regime:'Cross-sectional 24h snapshot with fresh scanner benchmark context',timeZone:'UTC ISO'},
  health,marketRegime:marketRegime(items,scanner,scannerAge),anomalies:anomalyRadar(items),
  funding:fundingRadar(items),rotation:sectorRotation(items),strategyLab:signalLab(monitors,publications),
  signalReadiness:signalReadiness(monitors),
  volatility:{type:'24h observed range only',symbols:viable(items).filter(x=>['BTC_USDT','ETH_USDT','SOL_USDT'].includes(x.symbol))
   .map(x=>({symbol:x.symbol,observedRangePct:rounded(n(x.high)>0&&n(x.low)>0?100*(x.high-x.low)/x.price:null)})),
   forecastAvailable:false},
  limitations:['No open-interest or liquidation heatmap feed','Signal score is NOT calibrated win probability',
   'No execution/position tracking or account PnL','Sector coverage is intentionally limited','No automatic strategy changes or orders']};
 data.capabilities=[
  ['Market Regime','PROXY'],['Smart Money','FUNDING_ONLY'],['Signal Confidence','UNCALIBRATED'],
  ['Strategy Lab','OBSERVATIONAL'],['Risk Sizing','HYPOTHETICAL'],
  ['Liquidity Map','NEEDS_DATA'],['Cross-Asset','EXISTING_PAIR_API'],['Macro Impact','EXISTING_MACRO_API'],
  ['Anomaly Radar','PROXY'],['Sector Rotation','CURATED_PROXY'],['AI Copilot','NOT_ENABLED'],
  ['Strategy Tournament','NEEDS_OOS_DATA'],['Signal Replay','EXISTING_PUBLICATION_JOURNAL'],
  ['Predictive Volatility','OBSERVED_RANGE_ONLY'],['Self Audit','DATA_FRESHNESS_ONLY']
 ].map(([name,status])=>({name,status}));
 return data;
}
export async function intelligenceApi(env){
 const safe=async(p,fallback)=>{try{return await p}catch{return fallback}};
 const [snapshot,scanner,mon,outcome,macro,pubs]=await Promise.all([
  safe(env.DB.prepare('SELECT fetched_at,items_json FROM snapshots WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT source_updated_at,market_context_json FROM scanner_snapshots WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT id,source,symbol,direction,status,score,created_at,tp1_observed_at,outcome_quality FROM signal_monitors ORDER BY created_at DESC LIMIT 300').all(),{results:[]}),
  safe(env.DB.prepare('SELECT last_success_at FROM outcome_health WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT checked_at FROM macro_engine_health WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT id FROM signal_publications ORDER BY sent_at DESC LIMIT 300').all(),{results:[]})
 ]);
 const data=buildIntelligence({snapshot,scanner,monitors:mon.results||[],outcome,macro,publications:pubs.results||[]});
 return reply(data,snapshot?200:503);
}
export function riskApi(url){
 const q=url.searchParams;
 const r=riskPreview({equity:q.get('equity'),entry:q.get('entry'),stop:q.get('stop'),riskPct:q.get('riskPct'),
  maxExposurePct:q.get('maxExposurePct')??100,direction:q.get('direction')||'LONG'});
 return reply(r,r.valid?200:400);
}
