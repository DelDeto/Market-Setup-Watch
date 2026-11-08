// ATLAS V2: server-pushed market feed, authenticated scanner events and
// price-observation journal. This NEVER places exchange orders.
const BASE='https://contract.mexc.com';
const GH_ISSUER='https://token.actions.githubusercontent.com';
const AUD='atlas-market-terminal';
const REPO='DelDeto/Market-Setup-Watch';
const AUTH_WORKFLOWS=new Set(['market-setup-watch.yml','atlas-event-dispatch.yml']);
const JSON_HEADERS={'content-type':'application/json;charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
const ACTIVE=new Set(['WAIT_ENTRY','ENTRY_OBSERVED','TP1_OBSERVED']);
const TRACKED_BUCKETS=new Set(['ENTRY_READY','NEAR_ENTRY','DEVELOPING','SWING_TOP_PICK']);
let jwksCache=null;
function response(x,status=200){return new Response(JSON.stringify(x),{status,headers:JSON_HEADERS})}
function number(v){if(v===null||v===undefined||v==='')return null;const x=Number(v);return Number.isFinite(x)?x:null}
function base64url(s){const p=s.replace(/-/g,'+').replace(/_/g,'/');return Uint8Array.from(atob(p+'='.repeat((4-p.length%4)%4)),c=>c.charCodeAt(0))}
function decodePart(s){return JSON.parse(new TextDecoder().decode(base64url(s)))}
export async function verifyGitHubOIDC(req,filename){
 const bearer=req.headers.get('authorization')||'';
 if(!bearer.startsWith('Bearer '))throw Error('missing bearer token');
 const parts=bearer.slice(7).split('.');
 if(parts.length!==3||parts.some(p=>p.length>6500))throw Error('malformed JWT');
 const header=decodePart(parts[0]), claims=decodePart(parts[1]), now=Math.floor(Date.now()/1000);
 if(header.alg!=='RS256'||typeof header.kid!=='string'||header.typ&&header.typ!=='JWT')throw Error('unsupported signature');
 if(claims.iss!==GH_ISSUER||claims.aud!==AUD||claims.repository!==REPO||claims.ref!=='refs/heads/main'||now>=Number(claims.exp)||now<Number(claims.nbf||0)-60||Number(claims.iat)>now+60)throw Error('invalid token claims');
 const refs=String(claims.workflow_ref||'');
 if(!AUTH_WORKFLOWS.has(filename)||refs!==REPO+'/.github/workflows/'+filename+'@refs/heads/main')throw Error('untrusted workflow');
 if(!jwksCache||Date.now()-jwksCache.at>15*60*1000){const r=await fetch(GH_ISSUER+'/.well-known/jwks',{headers:{accept:'application/json'}});if(!r.ok)throw Error('GitHub key set unavailable');jwksCache={at:Date.now(),keys:(await r.json()).keys||[]};}
 const key=jwksCache.keys.find(x=>x.kid===header.kid&&x.kty==='RSA'&&(!x.use||x.use==='sig'));
 if(!key)throw Error('unknown GitHub signing key');
 const imported=await crypto.subtle.importKey('jwk',key,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
 const ok=await crypto.subtle.verify('RSASSA-PKCS1-v1_5',imported,base64url(parts[2]),new TextEncoder().encode(parts[0]+'.'+parts[1]));
 if(!ok)throw Error('invalid JWT signature');
 return claims;
}
export function parseMonitor(x,when){
 if(!x||typeof x!=='object'||typeof x.id!=='string'||x.id.length<8||x.id.length>220||!/^[-A-Z0-9_]{3,35}$/.test(x.symbol||''))return null;
 const direction=String(x.direction||'').toUpperCase(),bucket=String(x.bucket||'');
 const entryLow=number(x.entry_low),entryHigh=number(x.entry_high),stop=number(x.stop),tp1=number(x.tp1),tp2=number(x.tp2);
 if(!['LONG','SHORT'].includes(direction)||!TRACKED_BUCKETS.has(bucket)||![entryLow,entryHigh,stop,tp1].every(v=>v!==null&&v>0)||entryLow>entryHigh)return null;
 if(direction==='LONG'&&!(stop<entryLow&&tp1>entryHigh))return null;
 if(direction==='SHORT'&&!(stop>entryHigh&&tp1<entryLow))return null;
 if(tp2!==null&&(direction==='LONG'?tp2<=tp1:tp2>=tp1))return null;
 const score=number(x.score);
 return {id:x.id,symbol:x.symbol,direction,bucket,entryLow,entryHigh,stop,tp1,tp2,score,source:'Market Setup Watch',createdAt:when,validUntil:new Date(Date.parse(when)+(bucket==='SWING_TOP_PICK'?48:4)*3600000).toISOString()};
}
export function transition(m,price,now){
 if(!ACTIVE.has(m.status))return null;
 if(Date.parse(m.valid_until)<Date.parse(now))return {status:'EXPIRED',kind:'EXPIRED',price:Number.isFinite(price)?price:null};
 if(!Number.isFinite(price)||price<=0)return null;
 if(m.status==='WAIT_ENTRY'){
  if(price>=m.entry_low&&price<=m.entry_high)return {status:'ENTRY_OBSERVED',kind:'ENTRY_OBSERVED',price};
  return null;
 }
 const stopHit=m.direction==='LONG'?price<=m.stop:price>=m.stop;
 const target1=m.direction==='LONG'?price>=m.tp1:price<=m.tp1;
 const target2=m.tp2!==null&&m.tp2!==undefined&&(m.direction==='LONG'?price>=m.tp2:price<=m.tp2);
 if(stopHit)return {status:'SL_OBSERVED',kind:'SL_OBSERVED',price};
 if(target2)return {status:'TP2_OBSERVED',kind:'TP2_OBSERVED',price};
 if(target1&&m.status!=='TP1_OBSERVED')return {status:'TP1_OBSERVED',kind:'TP1_OBSERVED',price};
 return null;
}
async function listMarket(){
 const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(),12000);
 try{
  const r=await fetch(BASE+'/api/v1/contract/ticker',{signal:ctrl.signal,headers:{accept:'application/json'}});
  if(!r.ok)throw Error('MEXC HTTP '+r.status);
  const d=await r.json();
  if(d.success===false||!Array.isArray(d.data))throw Error('invalid MEXC ticker payload');
  const rows=d.data.filter(x=>typeof x.symbol==='string'&&x.symbol.endsWith('_USDT')&&number(x.lastPrice)>0).map(x=>({symbol:x.symbol,price:number(x.lastPrice),changePct:number(x.riseFallRate)===null?null:100*number(x.riseFallRate),turnover:number(x.amount24),volume:number(x.volume24),funding:number(x.fundingRate),openInterestContracts:number(x.holdVol)}));
  if(rows.length<50)throw Error('ticker response suspiciously small');
  return rows.sort((a,b)=>(b.turnover||0)-(a.turnover||0));
 }finally{clearTimeout(timer)}
}
async function addEvent(env,m,kind,price,at){
 await env.DB.prepare("INSERT OR IGNORE INTO signal_events(id,signal_id,kind,symbol,direction,observed_price,observed_at,details_json) VALUES(?,?,?,?,?,?,?,?)").bind(m.id+':'+kind,m.id,kind,m.symbol,m.direction,price,at,JSON.stringify({entry_low:m.entry_low,entry_high:m.entry_high,stop:m.stop,tp1:m.tp1,tp2:m.tp2,source:m.source,tracking:'observation_only'})).run();
}
async function observe(env,rows,at){
 const r=await env.DB.prepare("SELECT * FROM signal_monitors WHERE status IN ('WAIT_ENTRY','ENTRY_OBSERVED','TP1_OBSERVED') ORDER BY updated_at DESC LIMIT 200").all();
 const bySymbol=new Map(rows.map(x=>[x.symbol,x.price]));const changes=[];
 for(const m of r.results||[]){
  const price=bySymbol.get(m.symbol);
  const observedPrice=Number.isFinite(price)?price:null;
  const t=transition(m,observedPrice,at);
  if(t){
   const updates=["status=?","updated_at=?","last_price=?","last_tick_at=?"];
   const params=[t.status,at,observedPrice,at];
   if(t.kind==='ENTRY_OBSERVED'){updates.push('entry_observed_at=?');params.push(at)}
   if(t.kind==='TP1_OBSERVED'){updates.push('tp1_observed_at=?');params.push(at)}
   if(t.kind==='TP2_OBSERVED'){updates.push('tp2_observed_at=?','ended_at=?');params.push(at,at)}
   if(t.kind==='SL_OBSERVED'){updates.push('sl_observed_at=?','ended_at=?');params.push(at,at)}
   if(t.kind==='EXPIRED'){updates.push('ended_at=?');params.push(at)}
   params.push(m.id,m.status);
   const saved=await env.DB.prepare("UPDATE signal_monitors SET "+updates.join(',')+" WHERE id=? AND status=?").bind(...params).run();
   if((saved.meta?.changes||0)>0){await addEvent(env,m,t.kind,observedPrice,at);changes.push({id:m.id,symbol:m.symbol,direction:m.direction,kind:t.kind,price:observedPrice,at})}
  }
 }
 return changes;
}
export async function ingestScan(req,env){
 try{await verifyGitHubOIDC(req,'market-setup-watch.yml')}catch(e){return response({error:'unauthorized',reason:String(e.message)},401)}
 const declared=Number(req.headers.get('content-length')||0);
 if(declared>200000)return response({error:'payload too large'},413);
 let d;try{d=await req.json()}catch{return response({error:'invalid JSON'},400)}
 const at=d?.generatedAt;
 if(typeof at!=='string'||!Number.isFinite(Date.parse(at))||Math.abs(Date.now()-Date.parse(at))>90*60000||!Array.isArray(d.signals)||d.signals.length>50)return response({error:'invalid or stale batch'},422);
 let valid=0,rejected=0;
 for(const candidate of d.signals){
  const v=parseMonitor(candidate,at);
  if(!v){rejected++;continue}
  const result=await env.DB.prepare("INSERT INTO signal_monitors(id,symbol,source,direction,bucket,score,entry_low,entry_high,stop,tp1,tp2,created_at,updated_at,valid_until,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'WAIT_ENTRY') ON CONFLICT(id) DO UPDATE SET bucket=excluded.bucket,score=excluded.score,updated_at=excluded.updated_at,valid_until=CASE WHEN signal_monitors.status='WAIT_ENTRY' THEN excluded.valid_until ELSE signal_monitors.valid_until END").bind(v.id,v.symbol,v.source,v.direction,v.bucket,v.score,v.entryLow,v.entryHigh,v.stop,v.tp1,v.tp2,v.createdAt,new Date().toISOString(),v.validUntil).run();
  valid++;
 }
 if(valid){try{const room=env.LIVE_ROOM.get(env.LIVE_ROOM.idFromName('atlas-usdt-futures'));await room.fetch('https://room.internal/wake',{method:'POST'})}catch(e){console.error('Room wake:',e.message)}}
 return response({ok:true,accepted:valid,rejected,sourceTime:at});
}
export async function trackingData(env){
 const [signals,events,publications]=await Promise.all([
  env.DB.prepare("SELECT id,symbol,source,direction,bucket,score,entry_low,entry_high,stop,tp1,tp2,created_at,updated_at,valid_until,status,last_price,last_tick_at,entry_observed_at,tp1_observed_at,tp2_observed_at,sl_observed_at,ended_at FROM signal_monitors ORDER BY updated_at DESC LIMIT 200").all(),
  env.DB.prepare("SELECT id,signal_id,kind,symbol,direction,observed_price,observed_at,delivery_status FROM signal_events ORDER BY observed_at DESC LIMIT 100").all(),
  env.DB.prepare("SELECT id,source,symbol,direction,bucket,notification_kind,scan_at,sent_at,is_trackable,eligibility_reason,monitor_id FROM signal_publications ORDER BY sent_at DESC LIMIT 120").all()
 ]);
 return response({signals:signals.results||[],events:events.results||[],publications:publications.results||[],semantics:'Closed-candle price-level outcome journal plus confirmed Telegram delivery receipts. NOT trade fills, exchange execution or realized PnL.'});
}
export async function claimEvents(req,env){
 try{await verifyGitHubOIDC(req,'atlas-event-dispatch.yml')}catch(e){return response({error:'unauthorized',reason:String(e.message)},401)}
 const now=new Date().toISOString(),lease=new Date(Date.now()+4*60000).toISOString();
 const q=await env.DB.prepare("SELECT id,kind,symbol,direction,observed_price,observed_at,details_json FROM signal_events WHERE kind IN ('ENTRY_OBSERVED','TP1_OBSERVED','TP2_OBSERVED','SL_OBSERVED') AND (delivery_status='pending' OR (delivery_status='leased' AND leased_until<?)) ORDER BY observed_at ASC LIMIT 15").bind(now).all();
 const claimed=[];
 for(const x of q.results||[]){const r=await env.DB.prepare("UPDATE signal_events SET delivery_status='leased',leased_until=? WHERE id=? AND (delivery_status='pending' OR (delivery_status='leased' AND leased_until<?))").bind(lease,x.id,now).run();if((r.meta?.changes||0)>0)claimed.push(x)}
 return response({events:claimed,leaseUntil:lease});
}
export async function ackEvents(req,env){
 try{await verifyGitHubOIDC(req,'atlas-event-dispatch.yml')}catch(e){return response({error:'unauthorized',reason:String(e.message)},401)}
 let d;try{d=await req.json()}catch{return response({error:'invalid JSON'},400)}
 if(!Array.isArray(d.ids)||d.ids.length>15)return response({error:'invalid ids'},422);
 let count=0;
 for(const id of d.ids){if(typeof id!=='string'||id.length>260)continue;const r=await env.DB.prepare("UPDATE signal_events SET delivery_status='sent',delivered_at=?,leased_until=NULL WHERE id=? AND delivery_status='leased'").bind(new Date().toISOString(),id).run();count+=r.meta?.changes||0}
 return response({ok:true,acknowledged:count});
}
export class AtlasLiveRoom{
 constructor(ctx,env){this.ctx=ctx;this.env=env}
 async wake(){if(!(await this.ctx.storage.getAlarm()))await this.ctx.storage.setAlarm(Date.now()+750)}
 async fetch(req){
  const url=new URL(req.url);
  if(url.pathname==='/wake'){await this.wake();return response({ok:true})}
  if(url.pathname==='/status'){const h=await this.ctx.storage.get('lastStatus');return response({...(h||{mode:'starting'}),subscribers:this.ctx.getWebSockets().length,scheduled:!!(await this.ctx.storage.getAlarm())})}
  if(url.pathname==='/oi-snapshot'){const h=await this.ctx.storage.get('lastOiSnapshot');return response(h||{available:false,updatedAt:null,items:[]},h?200:503)}
  if(url.pathname!=='/connect'&&url.pathname!=='/api/ws')return response({error:'not found'},404);
  if(req.headers.get('upgrade')?.toLowerCase()!=='websocket')return response({error:'WebSocket upgrade required'},426);
  const pair=new WebSocketPair();const [client,server]=Object.values(pair);
  this.ctx.acceptWebSocket(server);
  const h=await this.ctx.storage.get('lastStatus');
  server.send(JSON.stringify({type:'hello',mode:'Cloudflare WebSocket + upstream MEXC HTTP snapshots',lastTick:h?.updatedAt||null}));
  await this.wake();
  return new Response(null,{status:101,webSocket:client});
 }
 webSocketMessage(ws,message){if(String(message)==='ping')ws.send('pong')}
 webSocketClose(ws){try{ws.close(1000,'bye')}catch{}}
 async alarm(){
  const at=new Date().toISOString();const peers=this.ctx.getWebSockets();
  try{
   const rows=await listMarket();
   // Result tracking is handled by the chronological closed-candle evaluator.
   // The 10-second ticker stream must never infer fills from sampled last prices.
   const changed=[];
   const payload=JSON.stringify({type:'market',updatedAt:at,mode:'REST snapshots via WebSocket',items:rows});
   for(const ws of peers){try{ws.send(payload)}catch{try{ws.close(1011,'send failed')}catch{}}}
   if(changed.length){const msg=JSON.stringify({type:'tracking',observedAt:at,events:changed});for(const ws of peers){try{ws.send(msg)}catch{}}}
   // Persist a small, authentic MEXC contract-OI sample for Cron fallback if a separate Worker egress IP receives HTTP 403.
   // This is NOT a full-market replacement for the D1 ticker snapshot.
   try{
    const previous=await this.ctx.storage.get('lastOiSnapshot');
    if(!previous?.updatedAt||Date.now()-Date.parse(previous.updatedAt)>4*60*1000){
     const withOi=rows.filter(x=>number(x.openInterestContracts)>0).sort((a,b)=>(b.turnover||0)-(a.turnover||0));
     const pinned=['BTC_USDT','ETH_USDT','ZEC_USDT'].map(k=>withOi.find(x=>x.symbol===k)).filter(Boolean);
     const chosen=[...new Map([...withOi.slice(0,25),...pinned].map(x=>[x.symbol,x])).values()];
     if(chosen.length>=10)await this.ctx.storage.put('lastOiSnapshot',{available:true,updatedAt:at,items:chosen,source:'MEXC ticker via AtlasLiveRoom; contract units'});
    }
   }catch(e){console.warn('LiveRoom OI sample retention failed:',String(e).slice(0,100))}
   const status={updatedAt:at,instrumentCount:rows.length,mode:'REST snapshots via WebSocket',error:null};
   await this.ctx.storage.put('lastStatus',status);
   await this.env.DB.prepare("INSERT INTO live_feed_health(id,updated_at,mode,last_error,instrument_count) VALUES(1,?,?,NULL,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,mode=excluded.mode,last_error=NULL,instrument_count=excluded.instrument_count").bind(at,status.mode,rows.length).run();
  }catch(e){
   const error=String(e).slice(0,250);
   await this.ctx.storage.put('lastStatus',{updatedAt:at,mode:'degraded',error});
   await this.env.DB.prepare("INSERT INTO live_feed_health(id,updated_at,mode,last_error,instrument_count) VALUES(1,?,'degraded',?,NULL) ON CONFLICT(id) DO UPDATE SET mode='degraded',last_error=excluded.last_error").bind(at,error).run().catch(()=>{});
   for(const ws of peers){try{ws.send(JSON.stringify({type:'error',message:'Live source temporarily unavailable. Fallback polling applies.'}))}catch{}}
  }finally{
   // Continuous server-side polling even with no browser connected.
   // Do not confuse REST snapshots with true exchange tick-by-tick streaming.
   await this.ctx.storage.setAlarm(Date.now()+(peers.length?10000:30000));
  }
 }
}
