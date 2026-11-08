// ATLAS V5 evidence-first research modules. Never places orders or changes scanner decisions.
const BASE='https://contract.mexc.com';
const JSON_HEADERS={'content-type':'application/json;charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
const respond=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:JSON_HEADERS});
const n=v=>v==null||v===''?null:(Number.isFinite(Number(v))?Number(v):null);
const r=(v,k=2)=>Number.isFinite(v)?Number(v.toFixed(k)):null;
const safeJson=(v,otherwise=[])=>{try{return JSON.parse(v??'')}catch{return otherwise}};
const liveSymbols=s=>/^[A-Z0-9]{2,25}_USDT$/.test(s||'');
const millis=t=>{const a=Date.parse(t||'');return Number.isFinite(a)?a:null};
const iso=()=>new Date().toISOString();
const timeAgo=t=>millis(t)===null?null:Math.max(0,(Date.now()-millis(t))/60000);

export function openInterestDelta(items,history=[],maxResults=15){
 const previous=new Map(),latestTime=Math.max(...history.map(x=>millis(x.captured_at)||0),0);
 for(const x of history){
  const age=(latestTime-(millis(x.captured_at)||0))/60000;
  if(age<45||age>240||n(x.open_interest_contracts)===null||n(x.open_interest_contracts)<=0)continue;
  const old=previous.get(x.symbol);
  if(!old||millis(x.captured_at)>millis(old.captured_at))previous.set(x.symbol,x);
 }
 const out=[];
 for(const x of items||[]){
  const oi=n(x.openInterestContracts),p=n(x.price),old=previous.get(x.symbol);
  if(!liveSymbols(x.symbol)||oi===null||oi<=0||!old||p===null||p<=0)continue;
  const prev=n(old.open_interest_contracts),prior=n(old.price);
  if(prev===null||prev<=0||prior===null||prior<=0)continue;
  const delta=100*(oi/prev-1),priceDelta=100*(p/prior-1);
  const interpretation=(delta>2&&priceDelta>1)?'OI_UP_PRICE_UP':
   (delta>2&&priceDelta< -1)?'OI_UP_PRICE_DOWN':
   (delta< -2&&priceDelta>1)?'OI_DOWN_PRICE_UP':
   (delta< -2&&priceDelta< -1)?'OI_DOWN_PRICE_DOWN':'MIXED';
  out.push({symbol:x.symbol,openInterestContracts:oi,oiChangePct:r(delta),priceChangePct:r(priceDelta),
   comparedWith:old.captured_at,observedAt:latestTime?new Date(latestTime).toISOString():null,
   interpretation,contractUnits:true});
 }
 return {items:out.sort((a,b)=>Math.abs(b.oiChangePct)-Math.abs(a.oiChangePct)).slice(0,maxResults),
  coverage:out.length,source:'MEXC futures ticker holdVol contract units; 45–240 minute historical comparison',
  caveat:'Contract OI is not USD notional, orders, whale positions, liquidations, or verified taker volume. Price/OI co-movement is non-causal.'};
}

export function wilsonInterval(wins,total,z=1.96){
 if(!Number.isInteger(total)||total<=0||!Number.isInteger(wins)||wins<0||wins>total)return null;
 const p=wins/total,den=1+z*z/total,mid=(p+z*z/(2*total))/den;
 const half=z*Math.sqrt((p*(1-p)+z*z/(4*total))/total)/den;
 return {n:total,observedPct:r(p*100,1),lower95Pct:r((mid-half)*100,1),upper95Pct:r((mid+half)*100,1)};
}
function resolved(rows){
 return (rows||[]).filter(x=>x?.id&&!['AMBIGUOUS','AMBIGUOUS_POST_TP1','DATA_GAP'].includes(x.status)&&
 !['AMBIGUOUS','DATA_GAP'].includes(x.outcome_quality)&&
 (x.tp1_observed_at||(x.status==='SL_OBSERVED'&&!x.tp1_observed_at)))
 .map(x=>({...x,win:!!x.tp1_observed_at,time:millis(x.created_at)}))
 .filter(x=>x.time!==null).sort((a,b)=>a.time-b.time);
}
export function strategyTournament(monitors=[]){
 const data=resolved(monitors),map=new Map(),bands=new Map();
 for(const m of data){
  const key=String(m.source||'unknown').slice(0,65),g=map.get(key)||[];g.push(m);map.set(key,g);
  const score=n(m.score),band=score===null?'UNKNOWN':score>=80?'A':score>=65?'B':'C';
  const bg=bands.get(band)||[];bg.push(m);bands.set(band,bg);
 }
 const group=arr=>{
  const cut=Math.max(1,Math.floor(arr.length*.7)),train=arr.slice(0,cut),test=arr.slice(cut);
  const nWin=a=>a.filter(x=>x.win).length;
  return {total:arr.length,development: wilsonInterval(nWin(train),train.length),
   heldOut:wilsonInterval(nWin(test),test.length),
   eligible:train.length>=20&&test.length>=10,
   reason:train.length>=20&&test.length>=10?'Provisional research-only OOS observation':'Insufficient chronological development/holdout sample (minimum 20 + 10)'};
 };
 return {sources:[...map].map(([name,x])=>({name,...group(x)})),
  scoreBands:[...bands].map(([name,x])=>({name,...group(x)})),
  reviewed:data.length,split:'First 70% vs most recent 30% per source (chronological)',
  resultProvenance:'Only closed-candle level observations of TP1-first or SL-first; not fills, strategy PnL, or unbiased prospective validation.',
  promotionAllowed:false,note:'No automatic strategy changes. Model selection on this same dataset would overfit; independent forward validation is required.'};
}
export function selfAudit({snapshot,scanner,outcome,macro,monitors=[],history=[]}={}){
 const times={market:snapshot?.fetched_at,scanner:scanner?.source_updated_at,outcomes:outcome?.last_success_at,macro:macro?.checked_at};
 const threshold={market:15,scanner:45,outcomes:30,macro:45};
 const systems=Object.fromEntries(Object.entries(times).map(([k,v])=>[k,{ageMinutes:r(timeAgo(v),1),fresh:timeAgo(v)!==null&&timeAgo(v)<=threshold[k],maxAgeMinutes:threshold[k]}]));
 const rows=safeJson(snapshot?.items_json),symbols=new Set(rows.map(x=>x.symbol));
 const errors=[];
 if(rows.length<50)errors.push('MEXC instrument count is under 50');
 if(new Set(rows.map(x=>x.symbol)).size!==rows.length)errors.push('Duplicate market ticker symbols');
 if(!symbols.has('BTC_USDT')||!symbols.has('ETH_USDT'))errors.push('Missing BTC/ETH benchmark ticker');
 if(monitors.some(x=>x?.status==='DATA_GAP'))errors.push('Candle monitoring DATA_GAP present');
 for(const [name,status] of Object.entries(systems))if(!status.fresh)errors.push(name+' source stale or unavailable');
 const ois=rows.filter(x=>n(x.openInterestContracts)>0).length;
 return {status:errors.length?'DEGRADED':'OK',issues:errors,sources:systems,instruments:rows.length,
  oiTickerCoverage:ois,historyRowsLoaded:history.length,monitorRowsLoaded:monitors.length,
  verifiedTelegramDelivery:false,verifiedAutoRecovery:false,autoStrategyTuning:false,
  safeguards:['No order endpoints','No auto tuning','No inference from unknown/stale data'],
  note:'Checks are evidence quality diagnostics; Telegram relay and Cloudflare recovery must be verified separately from source health.'};
}
export function historicalVolatility(candles,symbol){
 const data=(candles||[]).filter(x=>Number.isFinite(n(x.close))&&n(x.close)>0);
 if(data.length<35)return {available:false,symbol,samples:Math.max(0,data.length-1),reason:'Need >=35 confirmed closed hourly candles'};
 const rets=data.slice(1).map((x,i)=>Math.log(x.close/data[i].close)).filter(Number.isFinite);
 let variance=rets.slice(0,10).reduce((s,v)=>s+v*v,0)/10;
 for(const x of rets.slice(10))variance=.94*variance+.06*x*x;
 const sigma=Math.sqrt(variance),abs=rets.map(Math.abs).sort((a,b)=>a-b);
 const empirical80=abs[Math.min(abs.length-1,Math.floor(abs.length*.8))];
 const last=data.at(-1),p=last.close;
 return {available:true,symbol,latestClosedCandleAt:last.at,latestClose:p,
  horizon:'1h',samples:rets.length,ewmaLambda:.94,sigmaLogReturnPct:r(sigma*100,3),
  indicativeGaussian68Pct:[r((Math.exp(-sigma)-1)*100,3),r((Math.exp(sigma)-1)*100,3)],
  indicativeAbsolute80Pct:r((Math.exp(empirical80)-1)*100,3),
  simulatedPriceBand68:[r(p*Math.exp(-sigma),8),r(p*Math.exp(sigma),8)],
  method:'EWMA of observed squared closed 1h log returns, lambda 0.94; indicative Gaussian 1σ band, not fitted or coverage-tested',
  caveat:'Risk scenarios are NOT a calibrated forecast or guaranteed price range; heavy tails and jumps can exceed these bands.'};
}
export function orderBookSummary(raw,symbol,depth=25){
 const data=raw?.data;
 if(raw?.success===false||!data||!Array.isArray(data.bids)||!Array.isArray(data.asks))return {available:false,symbol,reason:'MEXC order book returned no usable bids/asks'};
 const clean=x=>x.slice(0,depth).map(y=>({price:n(y[0]),contracts:n(y[1]),orders:n(y[2])})).filter(y=>y.price>0&&y.contracts>0);
 const bids=clean(data.bids).sort((a,b)=>b.price-a.price),asks=clean(data.asks).sort((a,b)=>a.price-b.price);
 if(!bids.length||!asks.length||asks[0].price<=bids[0].price)return {available:false,symbol,reason:'Order book crossed or empty'};
 const bestBid=bids[0].price,bestAsk=asks[0].price,mid=(bestBid+bestAsk)/2;
 const b=bids.reduce((s,x)=>s+x.contracts,0),a=asks.reduce((s,x)=>s+x.contracts,0);
 const walls=(side,arr)=>arr.sort((x,y)=>y.contracts-x.contracts).slice(0,4).map(x=>({side,price:x.price,contracts:x.contracts,distanceMidPct:r(100*(x.price-mid)/mid,3)}));
 return {available:true,symbol,bestBid,bestAsk,spreadPct:r(100*(bestAsk-bestBid)/mid,4),
  bidDepthContracts:b,askDepthContracts:a,imbalanceRatio:r((b-a)/(b+a),3),
  topWalls:[...walls('BID',bids),...walls('ASK',asks)].sort((x,y)=>y.contracts-x.contracts),
  source:'MEXC public order-book snapshot; top '+depth+' returned levels per side',
  timestamp:data.timestamp?new Date(Number(data.timestamp)).toISOString():iso(),
  liquidationHeatmapAvailable:false,
  caveat:'Displayed quantities are contracts not USD; contract multipliers vary. These are visible limit orders that may cancel; NOT forced liquidation levels, large trades or guaranteed support/resistance.'};
}
export function ruleBasedCopilot(query,context={}){
 const q=String(query||'').trim().toLowerCase();
 if(!q||q.length>240)return {error:'Enter a question of 1–240 characters.',status:'INVALID'};
 const a=context.advanced||{},base=context.intelligence||{},health=a.selfAudit||{},macro=a.macroEvents||[];
 let answer,links=[];
 if(/(health|lỗi|trạng thái|watchdog|hoạt động)/.test(q)){
  answer='Data audit: '+(health.status||'UNKNOWN')+'. Issues: '+((health.issues||[]).join('; ')||'No source freshness exceptions in checked metrics')+'. A fresh timestamp does not prove alert delivery.';
  links=['/api/intelligence/advanced','/api/watchdog'];
 }else if(/(oi|open interest|smart.money|dòng tiền)/.test(q)){
  const row=a.smartMoney?.items?.[0];
  answer=row?'Most changed observed OI: '+row.symbol+', '+row.oiChangePct+'% vs recorded historical contracts ('+row.interpretation+'). This is not proof of whale buying/selling.':'Not enough time-separated MEXC OI snapshots yet; collection requires at least 45 minutes of history.';
  links=['/api/intelligence/advanced'];
 }else if(/(chiến lược|strategy|model|backtest|tournament|win rate)/.test(q)){
  answer='Chronological source comparison has '+(a.tournament?.reviewed||0)+' unambiguous closed-candle resolved observations. Strategy promotion is DISABLED without independent forward validation; these are not realized PnL.';
  links=['/api/intelligence/advanced','/api/outcomes'];
 }else if(/(tin|macro|cpi|fed|nfp|lãi suất)/.test(q)){
  answer=macro.length?'Next verified macro event: '+macro[0].title+' on '+macro[0].scheduled_at+' UTC. Reactions are descriptive, not proof of causality.':'No verified future macro calendar entries available in this snapshot; do not infer that there are no upcoming events.';
  links=['/api/macro','/api/macro/calendar'];
 }else if(/(btc|trend|xu hướng|thị trường)/.test(q)){
  const m=base.marketRegime||{};
  answer='Current 24h breadth regime proxy: '+(m.regime||'UNKNOWN')+', BTC 24h '+(m.btcChange24hPct??'N/A')+'%, with '+(m.breadthPositivePct??'N/A')+'% of instruments positive. This does NOT predict next price.';
  links=['/api/intelligence'];
 }else if(/(liquid|thanh khoản|orderbook|sổ lệnh)/.test(q)){
  answer='Order-book bid/ask depth is available for a requested MEXC USDT futures symbol in the Liquidity panel. A liquidation HEATMAP is not enabled without its separately licensed dataset.';
  links=['/api/intelligence/liquidity?symbol=BTC_USDT'];
 }else if(/(pair|dxy|tương quan|correlation|zec)/.test(q)){
  answer='Use the existing Pair Relationship Lab to compare two assets using aligned closed log-return series. The indicative DXY reference is not the licensed ICE DXY index.';
  links=['/api/relationship?a=BTC&b=ZEC&tf=4h'];
 }else{
  answer='Evidence-based analysis available: market regime, OI history, funding, anomaly radar, sector rotation, volatility scenarios, signal replay, observed TP1/SL stats, and macro calendar. Please ask about a specific module.';
  links=['/api/intelligence/advanced'];
 }
 return {mode:'RULE_BASED_EVIDENCE_ASSISTANT',model:'none',query:q,answer,links,
  limitations:'No generative AI or external context used. Read-only source grounded template. No trading or order placement.'};
}
async function getJson(url,timeout=10000){
 const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),timeout);
 try{const res=await fetch(url,{signal:ctl.signal,headers:{Accept:'application/json'}});if(!res.ok)throw Error('MEXC upstream HTTP '+res.status);return res.json()}finally{clearTimeout(timer)}
}
export async function collectOpenInterestHistory(env){
 const last=await env.DB.prepare('SELECT MAX(captured_at) AS latest FROM market_intel_observations').first();
 if(timeAgo(last?.latest)!==null&&timeAgo(last.latest)<14)return {skipped:'too_recent'};
 const record=await env.DB.prepare('SELECT fetched_at,items_json FROM snapshots WHERE id=1').first();
 const items=safeJson(record?.items_json);
 if(!record||timeAgo(record.fetched_at)>20||items.length<50)return {skipped:'no_fresh_snapshot'};
 const sorted=items.filter(x=>liveSymbols(x.symbol)&&n(x.openInterestContracts)>0&&n(x.price)>0).sort((a,b)=>(n(b.turnover)||0)-(n(a.turnover)||0));
 const selected=[...new Map([...sorted.slice(0,25),...['BTC_USDT','ETH_USDT','ZEC_USDT'].map(s=>sorted.find(x=>x.symbol===s)).filter(Boolean)].map(x=>[x.symbol,x])).values()];
 if(!selected.length)return {skipped:'holdvol_not_exposed'};
 const at=record.fetched_at;
 const stmts=selected.map(x=>env.DB.prepare('INSERT OR IGNORE INTO market_intel_observations(symbol,captured_at,price,open_interest_contracts,turnover24) VALUES(?,?,?,?,?)').bind(x.symbol,at,x.price,x.openInterestContracts,x.turnover||null));
 await env.DB.batch(stmts);
 // Prune once every few hours; avoid huge D1 history and avoid repeated writes.
 if(new Date().getUTCHours()%6===0&&new Date().getUTCMinutes()<5)
  await env.DB.prepare("DELETE FROM market_intel_observations WHERE captured_at < datetime('now','-7 days')").run();
 return {captured:selected.length,at};
}
export async function fetchAdvancedInputs(env){
 const safe=async(p,fallback)=>{try{return await p}catch{return fallback}};
 const [snapshot,scanner,outcome,macro,monitor,history,calendar]=await Promise.all([
  safe(env.DB.prepare('SELECT fetched_at,items_json FROM snapshots WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT source_updated_at,market_context_json FROM scanner_snapshots WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT last_success_at FROM outcome_health WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT checked_at FROM macro_engine_health WHERE id=1').first(),null),
  safe(env.DB.prepare('SELECT id,source,symbol,direction,score,status,created_at,tp1_observed_at,outcome_quality FROM signal_monitors ORDER BY created_at DESC LIMIT 500').all(),{results:[]}),
  safe(env.DB.prepare('SELECT symbol,captured_at,price,open_interest_contracts,turnover24 FROM market_intel_observations ORDER BY captured_at DESC LIMIT 1500').all(),{results:[]}),
  safe(env.DB.prepare("SELECT title,scheduled_at,kind,source_name FROM macro_calendar_events WHERE scheduled_at>datetime('now') ORDER BY scheduled_at LIMIT 8").all(),{results:[]})
 ]);
 return {snapshot,scanner,outcome,macro,monitors:monitor.results||[],history:history.results||[],calendar:calendar.results||[]};
}
export function buildAdvanced(inputs={}){
 const items=safeJson(inputs.snapshot?.items_json);
 const smartMoney=openInterestDelta(items,inputs.history),tournament=strategyTournament(inputs.monitors);
 const audit=selfAudit(inputs);
 const marketOI=items.filter(x=>n(x.openInterestContracts)>0).length;
 return {version:'5.0-evidence',generatedAt:iso(),smartMoney,tournament,selfAudit:audit,macroEvents:inputs.calendar||[],
  oiSnapshot:{coverage:marketOI,total:items.length,source:'MEXC contract ticker holdVol',units:'contracts'},
  monitoredPlans:(inputs.monitors||[]).slice(0,60).map(x=>({id:x.id,symbol:x.symbol,status:x.status,createdAt:x.created_at})),
  capabilities:[
   {name:'Market Regime AI',status:'RULE_BASED_PROXY',api:'/api/intelligence'},
   {name:'Smart Money Flow',status:smartMoney.coverage?'OI_DELTA_AVAILABLE':'OI_HISTORY_BOOTSTRAPPING',api:'/api/intelligence/advanced'},
   {name:'Signal Confidence Engine',status:'OBSERVED_WILSON_INTERVAL',api:'/api/intelligence/advanced'},
   {name:'AI Strategy Lab',status:'CHRONOLOGICAL_RESEARCH_ONLY',api:'/api/intelligence/advanced'},
   {name:'Risk & Position Sizing',status:'HYPOTHETICAL',api:'/api/intelligence/risk'},
   {name:'Liquidity & Liquidation Map',status:'ORDERBOOK_ONLY_NO_LIQUIDATION',api:'/api/intelligence/liquidity?symbol=BTC_USDT'},
   {name:'Cross-Asset Intelligence',status:'CORRELATION_AND_LAG_DIAGNOSTIC',api:'/api/relationship?a=BTC&b=ZEC&tf=4h'},
   {name:'Macro Impact Engine',status:'OFFICIAL_CALENDAR_AND_OBSERVED_REACTION',api:'/api/macro'},
   {name:'Market Anomaly Radar',status:'24H_PRICE_TURNOVER_PROXY',api:'/api/intelligence'},
   {name:'Sector Rotation Radar',status:'CURATED_GROUPS',api:'/api/intelligence'},
   {name:'AI Market Copilot',status:'RULE_BASED_NO_GENERATIVE_AI',api:'/api/intelligence/ask?q=BTC'},
   {name:'Strategy Tournament',status:'OOS_SPLIT_OBSERVATIONAL',api:'/api/intelligence/advanced'},
   {name:'Signal Replay & Journal',status:'VERIFIED_PUBLICATION_EVENT_JOURNAL',api:'/api/intelligence/replay?id=ID'},
   {name:'Predictive Volatility',status:'UNVALIDATED_EWMA_SCENARIO',api:'/api/intelligence/volatility?symbol=BTC_USDT'},
   {name:'ATLAS Self-Audit AI',status:'AUTOMATED_DATA_QUALITY_CHECKS',api:'/api/intelligence/advanced'}],
  constraints:['No liquidation heatmap subscription','No order fill or account PnL feed','Generative AI Copilot disabled to avoid public unbounded model costs','No strategy auto-promotion','Lag is descriptive not a proven lead signal']};
}
export async function advancedApi(env){const x=await fetchAdvancedInputs(env);return respond(buildAdvanced(x),x.snapshot?200:503)}
export async function copilotApi(url,env){
 const q=url.searchParams.get('q')||'';if(q.length>240||!q.trim())return respond({error:'Question length 1–240 characters'},400);
 const x=await fetchAdvancedInputs(env);
 const advanced=buildAdvanced(x),base={marketRegime:{regime:advanced.selfAudit.status}};
 const rows=safeJson(x.snapshot?.items_json),btc=rows.find(y=>y.symbol==='BTC_USDT');
 base.marketRegime={regime:safeJson(x.scanner?.market_context_json,{}).regime||'UNKNOWN_SCANNER',btcChange24hPct:btc?.changePct??null};
 return respond(ruleBasedCopilot(q,{advanced,intelligence:{marketRegime:base.marketRegime}}));
}
export async function replayApi(url,env){
 const id=url.searchParams.get('id')||'';
 if(!/^[\w:|.\-]{1,240}$/.test(id))return respond({error:'Invalid monitor id'},400);
 const monitor=await env.DB.prepare('SELECT * FROM signal_monitors WHERE id=?').bind(id).first();
 if(!monitor)return respond({error:'No verified monitor for this ID'},404);
 const [events,pubs]=await Promise.all([
  env.DB.prepare('SELECT kind,observed_price,observed_at,details_json,delivery_status FROM signal_events WHERE signal_id=? ORDER BY observed_at ASC LIMIT 80').bind(id).all(),
  env.DB.prepare('SELECT id,source,symbol,direction,bucket,sent_at,is_trackable,eligibility_reason FROM signal_publications WHERE monitor_id=? ORDER BY sent_at LIMIT 30').bind(id).all()
 ]);
 return respond({version:'5.0-replay',monitor,events:events.results||[],publications:pubs.results||[],
  note:'Observed candle-price level sequence only. No inferred exchange fills or actual account returns.'});
}
// Optional licensed CoinGlass liquidation model. Disabled by default: never spend credits on an unauthenticated public UI.
// Only operator-controlled, dual-opt-in secret + flag may enable upstream requests.
export async function liquidationHeatmapApi(url,env){
 const symbol=url.searchParams.get('symbol')||'BTC_USDT';
 if(!liveSymbols(symbol))return respond({error:'Invalid contract symbol'},400);
 if(!env?.COINGLASS_API_KEY||env.PUBLIC_HEATMAP_ENABLED!=='true')
  return respond({available:false,configured:false,symbol,provider:'CoinGlass Professional/Enterprise',
   reason:'Premium liquidation heatmap not activated; no paid provider requests were made.',
   docs:'https://docs.coinglass.com/reference/liquidation-heatmap'});
 const range=url.searchParams.get('range')||'24h';
 if(!['12h','24h','3d','7d'].includes(range))return respond({error:'Unsupported range'},400);
 const exchange='Binance',pair=symbol.replace('_','');
 const urlApi='https://open-api-v4.coinglass.com/api/futures/liquidation/heatmap/model1?exchange='+exchange+'&symbol='+pair+'&range='+range;
 const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),11000);
 try{
  const res=await fetch(urlApi,{signal:ac.signal,headers:{Accept:'application/json','CG-API-KEY':env.COINGLASS_API_KEY}});
  if(!res.ok)throw Error('Provider HTTP '+res.status);
  const payload=await res.json();
  if(String(payload?.code)!=='0'||!Array.isArray(payload?.data?.y_axis)||!Array.isArray(payload?.data?.liquidation_leverage_data))throw Error('Invalid licensed heatmap');
  const levels=payload.data.y_axis,rollup=new Map();
  for(const cell of payload.data.liquidation_leverage_data){
   const index=Number(cell[1]),usd=n(cell[2]);
   if(Number.isInteger(index)&&index>=0&&index<levels.length&&usd>0)
    rollup.set(index,(rollup.get(index)||0)+usd);
  }
  const peaks=[...rollup].map(([index,valueUsd])=>({price:n(levels[index]),modeledExposureUsd:r(valueUsd)}))
   .filter(x=>x.price>0).sort((a,b)=>b.modeledExposureUsd-a.modeledExposureUsd).slice(0,16);
  return respond({available:true,configured:true,provider:'CoinGlass heatmap model1',exchange,symbol:pair,range,
   peakModeledZones:peaks,capturedAt:iso(),method:'Provider modeled estimated leverage liquidation concentration',
   caveat:'Modeled exposure, not actual forced fills or guaranteed liquidation. Not MEXC market data. Licensed provider may charge API credits.'});
 }catch(e){return respond({available:false,configured:true,symbol,error:'Premium heatmap unavailable: '+String(e.message).slice(0,95)},503)}
 finally{clearTimeout(timer)}
}

export async function liquidityApi(url){
 const symbol=url.searchParams.get('symbol')||'BTC_USDT';
 if(!liveSymbols(symbol))return respond({error:'Invalid MEXC futures symbol'},400);
 try{return respond(orderBookSummary(await getJson(BASE+'/api/v1/contract/depth/'+symbol+'?limit=25'),symbol))}
 catch(e){return respond({available:false,symbol,error:'Order-book source unavailable: '+String(e.message).slice(0,100)},503)}
}
export async function volatilityApi(url){
 const symbol=url.searchParams.get('symbol')||'BTC_USDT';
 if(!liveSymbols(symbol))return respond({error:'Invalid MEXC futures symbol'},400);
 const now=Math.floor(Date.now()/1000),end=Math.floor(now/3600)*3600,from=end-3600*150;
 try{
  const raw=await getJson(BASE+'/api/v1/contract/kline/'+symbol+'?interval=Min60&start='+from+'&end='+now);
  if(raw.success===false||!Array.isArray(raw.data?.time))throw Error('Invalid closed-candle response');
  const bars=raw.data.time.map((t,i)=>({at:new Date(Number(t)*1000).toISOString(),t:Number(t),close:n(raw.data.close?.[i])}))
   .filter(x=>x.t<end&&x.close>0).sort((a,b)=>a.t-b.t).slice(-110);
  return respond(historicalVolatility(bars,symbol));
 }catch(e){return respond({available:false,symbol,error:'Closed candle source unavailable: '+String(e.message).slice(0,100)},503)}
}
