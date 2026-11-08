/**
 * ATLAS V3.6: Pair Relationship Lab.
 * Descriptive, synchronized log-return analysis; never causal proof or a trade instruction.
 *
 * Crypto: MEXC USDT perpetual closed candles (1h/4h/1d).
 * DXY: indicative daily basket reconstructed from ECB EUR reference rates.
 * NOT ICE's licensed intraday DXY benchmark. Do not forward fill weekends.
 */
const MARKET='https://contract.mexc.com/api/v1/contract/kline/';
const ECB='https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml';
const FT='https://api.frankfurter.app/';
const TF={ '1h':{interval:'Min60',ms:3600000,days:28},
 '4h':{interval:'Hour4',ms:4*3600000,days:84},
 '1d':{interval:'Day1',ms:86400000,days:89}};
const HTTP_HEADERS={'content-type':'application/json;charset=utf-8','cache-control':'public,max-age=300','x-content-type-options':'nosniff'};
const BODY_MAX=1300000;
const DXY_FACT=50.14348112,PROXY_WEIGHTS=Object.freeze({EUR:-0.576,JPY:0.136,GBP:-0.119,CAD:0.091,SEK:0.042,CHF:0.036});
function respond(body,status=200){return new Response(JSON.stringify(body),{status,headers:HTTP_HEADERS})}
export function assetName(raw){
 const s=String(raw||'').trim().toUpperCase().replace(/[\s-]/g,'');
 if(s==='DXY'||s==='USDX'||s==='DX')return 'DXY';
 if(s.endsWith('_USDT'))return /^[A-Z0-9]{2,24}_USDT$/.test(s)?s:null;
 if(s.endsWith('USDT')){const token=s.slice(0,-4);return /^[A-Z0-9]{2,24}$/.test(token)?token+'_USDT':null}
 return /^[A-Z0-9]{2,24}$/.test(s)?s+'_USDT':null;
}
export function dxyEstimate(c){
 const r={};for(const k of ['USD','JPY','GBP','CAD','SEK','CHF']){const n=Number(c?.[k]);if(!Number.isFinite(n)||n<=0)return null;r[k]=n}
 const {USD,JPY,GBP,CAD,SEK,CHF}=r;
 const eurusd=USD,usdjpy=JPY/USD,gbpusd=USD/GBP,usdcad=CAD/USD,usdsek=SEK/USD,usdchf=CHF/USD;
 const idx=DXY_FACT*Math.pow(eurusd,PROXY_WEIGHTS.EUR)
  *Math.pow(usdjpy,PROXY_WEIGHTS.JPY)*Math.pow(gbpusd,PROXY_WEIGHTS.GBP)
  *Math.pow(usdcad,PROXY_WEIGHTS.CAD)*Math.pow(usdsek,PROXY_WEIGHTS.SEK)
  *Math.pow(usdchf,PROXY_WEIGHTS.CHF);
 return Number.isFinite(idx)&&idx>0?idx:null;
}
function xmlAttributes(tag){
 const out={};for(const m of tag.matchAll(/([A-Za-z]+)=["']([^"']+)["']/g))out[m[1]]=m[2];return out;
}
export function parseEcb90DayXml(xml){
 const doc=String(xml||'');
 const result=[];
 // ECB 90-day XML includes Cube(time=YYYY-MM-DD) with Cube(currency,rate) children.
 const dates=/<(?:\w+:)?Cube\b(?=[^>]*\btime=["']\d{4}-\d{2}-\d{2}["'])[^>]*>([\s\S]*?)<\/(?:\w+:)?Cube>/gi;
 for(const outer of doc.matchAll(dates)){
  const opening=outer[0].match(/^<[^>]+>/)?.[0]||'';
  const date=xmlAttributes(opening).time;
  if(!/^\d{4}-\d{2}-\d{2}$/.test(date||''))continue;
  const quotes={};
  for(const child of outer[1].matchAll(/<(?:\w+:)?Cube\b[^>]*\/?>/gi)){
   const a=xmlAttributes(child[0]);if(a.currency)quotes[a.currency]=Number(a.rate);
  }
  const close=dxyEstimate(quotes);
  if(close!==null)result.push({t:Date.parse(date+'T00:00:00Z'),close});
 }
 return result.sort((a,b)=>a.t-b.t).filter((x,i,all)=>!i||x.t!==all[i-1].t);
}
export function parseFrankfurter(data){
 const result=[];
 for(const [date,c] of Object.entries(data?.rates||{})){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(date))continue;
  const close=dxyEstimate(c);
  if(close!==null)result.push({t:Date.parse(date+'T00:00:00Z'),close});
 }
 return result.sort((a,b)=>a.t-b.t);
}
async function withTimeout(url,{timeout=12500,headers={Accept:'application/json'}}={}){
 const c=new AbortController();const timer=setTimeout(()=>c.abort(),timeout);
 try{const r=await fetch(url,{signal:c.signal,headers});if(!r.ok)throw Error('SOURCE_HTTP_'+r.status);
  const text=await r.text();if(text.length>BODY_MAX)throw Error('SOURCE_RESPONSE_TOO_LARGE');return text;
 }finally{clearTimeout(timer)}
}
async function ecbDxy(){
 try{
  const raw=await withTimeout(ECB,{timeout:11000,headers:{Accept:'application/xml,text/xml,*/*'}});
  const samples=parseEcb90DayXml(raw);
  if(samples.length<15)throw Error('ECB_RATES_INSUFFICIENT');
  return {data:samples,source:'ECB official EUR reference rates (derived basket)',sourceUrl:ECB,sourceType:'indicative_proxy'};
 }catch(e){
  // Frankfurter redistributes ECB reference series; label the intermediary.
  // Never silently present a reconstruction as the official live ICE DXY.
  const end=new Date().toISOString().slice(0,10),start=new Date(Date.now()-92*86400000).toISOString().slice(0,10);
  const raw=await withTimeout(FT+start+'..'+end+'?from=EUR&to=USD,JPY,GBP,CAD,SEK,CHF');
  const samples=parseFrankfurter(JSON.parse(raw));
  if(samples.length<15)throw Error('ECB_AND_FALLBACK_RATES_UNAVAILABLE');
  return {data:samples,source:'ECB reference rates via Frankfurter (derived basket)',sourceUrl:'https://api.frankfurter.app/',sourceType:'indicative_proxy',primaryError:String(e.message).slice(0,90)};
 }
}
async function cryptoCandles(symbol,tf){
 const config=TF[tf];const now=Date.now();
 const start=Math.floor((now-config.days*86400000)/1000),end=Math.floor(now/1000);
 const u=new URL(MARKET+symbol);u.searchParams.set('interval',config.interval);
 u.searchParams.set('start',String(start));u.searchParams.set('end',String(end));
 const data=JSON.parse(await withTimeout(u.toString()));
 if(data?.success===false||!Array.isArray(data?.data?.time)||!Array.isArray(data?.data?.close))throw Error('MEXC_INVALID_KLINE_'+symbol);
 const rows=data.data.time.map((t,i)=>({t:Number(t)*1000,close:Number(data.data.close[i])}))
  .filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.close)&&x.close>0&&x.t+config.ms<=now)
  .sort((a,b)=>a.t-b.t);
 if(rows.length<20)throw Error('MEXC_BARS_INSUFFICIENT_'+symbol);
 return {data:rows,source:'MEXC USDT perpetual closed '+tf+' candles',sourceType:'futures',sourceUrl:'https://www.mexc.com/',symbol};
}
function key(t,daily){return daily?new Date(t).toISOString().slice(0,10):String(t)}
export function alignPairs(first,second,{daily=false}={}){
 const a=new Map(first.map(x=>[key(x.t,daily),x]));const paired=[];
 for(const b of second){
  const x=a.get(key(b.t,daily));
  if(x&&Number.isFinite(x.close)&&x.close>0&&Number.isFinite(b.close)&&b.close>0)
   paired.push({time:daily?key(b.t,true):new Date(b.t).toISOString(),a:x.close,b:b.close});
 }
 return paired.sort((x,y)=>x.time.localeCompare(y.time));
}
export function pearson(a,b){
 if(a.length!==b.length||a.length<3)return null;
 const n=a.length,ma=a.reduce((s,v)=>s+v,0)/n,mb=b.reduce((s,v)=>s+v,0)/n;
 let vx=0,vy=0,c=0;
 for(let i=0;i<n;i++){const x=a[i]-ma,y=b[i]-mb;vx+=x*x;vy+=y*y;c+=x*y}
 return vx>1e-18&&vy>1e-18?Math.max(-1,Math.min(1,c/Math.sqrt(vx*vy))):null;
}
function variance(x){if(x.length<3)return null;const mean=x.reduce((s,v)=>s+v,0)/x.length;return x.reduce((s,v)=>s+(v-mean)**2,0)/(x.length-1)}
function cov(x,y){if(x.length<3||x.length!==y.length)return null;const a=x.reduce((s,v)=>s+v,0)/x.length,b=y.reduce((s,v)=>s+v,0)/y.length;return x.reduce((s,v,i)=>s+(v-a)*(y[i]-b),0)/(x.length-1)}
const round=(v,dp=4)=>Number.isFinite(v)?Number(v.toFixed(dp)):null;
export function analyzeRelationships(pairs){
 if(pairs.length<22)return {available:false,reason:'Insufficient matched history (need at least 22 common price observations).',matchedBars:pairs.length};
 const aR=[],bR=[],points=[],rolling=[];
 const a0=pairs[0].a,b0=pairs[0].b;
 for(let i=0;i<pairs.length;i++){
  const v=pairs[i];
  points.push({time:v.time,a:round(v.a/a0*100,3),b:round(v.b/b0*100,3)});
  if(i){aR.push(Math.log(v.a/pairs[i-1].a));bR.push(Math.log(v.b/pairs[i-1].b))}
  if(aR.length>=20){
   const c=pearson(aR.slice(-20),bR.slice(-20));
   rolling.push({time:v.time,correlation:round(c,3)});
  }
 }
 const correlation=pearson(aR,bR),latest20=pearson(aR.slice(-20),bR.slice(-20));
 const older20=aR.length>=40?pearson(aR.slice(-40,-20),bR.slice(-40,-20)):null;
 const vA=variance(aR),vB=variance(bR);
 const beta=vB&&vB>1e-16?cov(aR,bR)/vB:null;
 const lagValues=[];
 for(let lag=-3;lag<=3;lag++){
  // Lag is an offset comparison of historical closed returns, not a claim of predictive causality.
  const x=[],y=[];
  for(let i=0;i<aR.length;i++){
   const j=i-lag;
   if(j>=0&&j<bR.length){x.push(aR[i]);y.push(bR[j])}
  }
  lagValues.push({lagBarsBPrecedesA:lag,correlation:round(pearson(x,y),3),sampleCount:x.length});
 }
 const lagCandidates=lagValues.filter(x=>x.lagBarsBPrecedesA!==0&&x.sampleCount>=20&&x.correlation!==null);
 lagCandidates.sort((x,y)=>Math.abs(y.correlation)-Math.abs(x.correlation));
 let divergenceZ=null;
 if(beta!==null){
  const spreads=pairs.map(v=>Math.log(v.a/a0)-beta*Math.log(v.b/b0)),window=spreads.slice(-20);
  if(window.length>=20){
   const mean=window.reduce((s,v)=>s+v,0)/window.length;
   const sd=Math.sqrt(window.reduce((s,v)=>s+(v-mean)**2,0)/(window.length-1));
   if(sd>1e-9)divergenceZ=round((window.at(-1)-mean)/sd,3);
  }
 }

 const retA=100*(pairs.at(-1).a/a0-1),retB=100*(pairs.at(-1).b/b0-1);
 let relation='INCONCLUSIVE';
 if(correlation!==null){relation=correlation>=0.6?'STRONG_POSITIVE':correlation>=0.25?'MODERATE_POSITIVE':correlation<=-0.6?'STRONG_INVERSE':correlation<=-0.25?'MODERATE_INVERSE':'WEAK_OR_MIXED'}
 return {available:true,relation,samples:aR.length,matchedBars:pairs.length,
  correlation:round(correlation,3),rollingLatest:round(latest20,3),rollingPrevious:round(older20,3),
  beta:round(beta,3),volatilityA:round(vA===null?null:Math.sqrt(vA)*100,3),
  volatilityB:round(vB===null?null:Math.sqrt(vB)*100,3),
  volRatio:round(vA&&vB?Math.sqrt(vA/vB):null,3),
  returnA:round(retA,2),returnB:round(retB,2),relativeReturn:round(retA-retB,2),
  points,rolling,lagDiagnostics:lagValues,largestAbsHistoricalLag:lagCandidates[0]||null,
  divergenceZ20:divergenceZ,lagCaveat:'Lead/lag offsets are retrospective, vulnerable to multiple comparisons and cannot establish price prediction.',
  interpretation:'Pearson coefficient uses aligned logarithmic CLOSE-to-CLOSE returns, not price levels; BETA is sensitivity of A to B returns; window is historical and correlation is not causation.'};
}
export async function relationshipApi(reqUrl){
 const url=typeof reqUrl==='string'?new URL(reqUrl):reqUrl;
 const a=assetName(url.searchParams.get('a')||'BTC'),b=assetName(url.searchParams.get('b')||'ZEC');
 if(!a||!b)return respond({error:'Unsupported ticker format. Use e.g. BTC, ZEC, BTC_USDT or DXY.'},422);
 if(a===b)return respond({error:'Select two different assets.'},422);
 const tfRequested=url.searchParams.get('tf')||'4h';
 if(!TF[tfRequested])return respond({error:'Supported timeframes: 1h, 4h, 1d.'},422);
 const dxyIncluded=a==='DXY'||b==='DXY';
 const tf=dxyIncluded?'1d':tfRequested;
 const labels=[a,b],inputs=await Promise.allSettled(labels.map(x=>x==='DXY'?ecbDxy():cryptoCandles(x,tf)));
 const errors=[];
 for(let i=0;i<inputs.length;i++)if(inputs[i].status==='rejected')errors.push(labels[i]+': '+String(inputs[i].reason?.message||'UPSTREAM_UNAVAILABLE').slice(0,140));
 if(errors.length)return respond({error:'Unable to retrieve comparable history. No relationship calculated.',sourceErrors:errors,assets:labels,requestedTimeframe:tfRequested,effectiveTimeframe:tf},503);
 const sourceA=inputs[0].value,sourceB=inputs[1].value;
 const pairs=alignPairs(sourceA.data,sourceB.data,{daily:tf==='1d'});
 const stats=analyzeRelationships(pairs);
 return respond({version:'3.6',assetA:a,assetB:b,timeframe:tf,requestedTimeframe:tfRequested,
  forcedDaily:dxyIncluded&&tfRequested!=='1d',sources:{a:{type:sourceA.sourceType,name:sourceA.source,link:sourceA.sourceUrl},b:{type:sourceB.sourceType,name:sourceB.source,link:sourceB.sourceUrl}},
  refreshedAt:new Date().toISOString(),latestShared:pairs.at(-1)?.time||null,
  ...stats,disclaimer:dxyIncluded?
   'DXY is a reference reconstruction from six ECB FX spot reference rates, NOT ICE live DXY. ECB publishes on business days only. Crypto daily close is based on UTC date, not synchronized to ECB fixing time. No weekend forward-fill. Interpret relationship as date-aligned, not high-frequency or causal.':
   'MEXC USDT perpetual futures close prices. Return correlation describes co-movement, not causation, prediction or trading signal.'});
}
