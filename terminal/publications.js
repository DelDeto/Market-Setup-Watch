// ATLAS V3 authenticated publication receipt ledger.
// Journal exactly what the scanner confirms it delivered to Telegram.
import {verifyGitHubOIDC,parseMonitor} from './live.js';
const B={'content-type':'application/json;charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
const ok=(v,status=200)=>new Response(JSON.stringify(v),{status,headers:B});
const ALLOWED_BUCKETS=new Set(['ENTRY_READY','NEAR_ENTRY','DEVELOPING','WATCHLIST','SWING_TOP_PICK']);
const ALLOWED_MODES=new Set(['INTRADAY','SWING','HEARTBEAT_REFERENCE']);
function time(x){return typeof x==='string'?Date.parse(x):NaN;}
function n(x){if(x===null||x===undefined||x==='')return null;const y=Number(x);return Number.isFinite(y)?y:null;}
export function validatePublication(x){
 if(!x||typeof x!=='object'||typeof x.id!=='string'||!/^tg-[a-f0-9]{40}$/.test(x.id)||
    !/^[A-Z0-9]{2,25}_USDT$/.test(x.symbol||'')||
    !['LONG','SHORT'].includes(x.direction)||!ALLOWED_BUCKETS.has(x.bucket)||
    !ALLOWED_MODES.has(x.mode))return null;
 if(x.mode==='SWING'&&x.bucket!=='SWING_TOP_PICK'||x.mode==='INTRADAY'&&x.bucket==='SWING_TOP_PICK')return null;
 const plan={id:x.id,symbol:x.symbol,direction:x.direction,bucket:x.bucket,entry_low:n(x.entry_low),
 entry_high:n(x.entry_high),stop:n(x.stop),tp1:n(x.tp1),tp2:n(x.tp2),score:n(x.score)};
 const eligible=Boolean(x.is_trackable)&&(x.mode==='SWING'&&x.bucket==='SWING_TOP_PICK'||x.mode==='INTRADAY'&&x.bucket==='ENTRY_READY');
 return {plan,eligible,mode:x.mode,reason:String(x.reason||'UNSPECIFIED').slice(0,90)};
}
export async function ingestPublications(req,env){
 try{await verifyGitHubOIDC(req,'market-setup-watch.yml')}catch(e){return ok({error:'unauthorized',detail:String(e.message)},401)}
 if(Number(req.headers.get('content-length')||0)>250000)return ok({error:'payload too large'},413);
 let d;try{d=await req.json()}catch{return ok({error:'invalid JSON'},400)}
 const generated=time(d?.generatedAt),sent=time(d?.sentAt),now=Date.now();
 if(!Number.isFinite(generated)||!Number.isFinite(sent)||sent<generated||
    sent<now-2*3600000||sent>now+5*60000||!['setup_change','heartbeat'].includes(d?.notificationKind)||
    !Array.isArray(d.publications)||d.publications.length>30){
  return ok({error:'invalid or stale confirmed publication batch'},422);
 }
 let published=0,tracked=0,rejected=0;
 const nowIso=new Date(now).toISOString();
 for(const item of d.publications){
  const v=validatePublication(item);
  if(!v){rejected++;continue}
  const p=v.plan;
  const parsed=v.eligible?parseMonitor(p,d.sentAt):null;
  const eligible=!!parsed&&d.notificationKind==='setup_change';
  const reason=v.eligible&&!parsed?'INVALID_PLAN_GEOMETRY':!eligible?v.reason:'VERIFIED_PRICE_MONITOR';
  const r=await env.DB.prepare(
   "INSERT OR IGNORE INTO signal_publications(id,source,symbol,direction,bucket,notification_kind,scan_at,sent_at,is_trackable,eligibility_reason,monitor_id,entry_low,entry_high,stop,tp1,tp2,received_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
   .bind(p.id,'Market Setup Watch',p.symbol,p.direction,p.bucket,d.notificationKind,d.generatedAt,d.sentAt,eligible?1:0,reason,
     eligible?p.id:null,p.entry_low,p.entry_high,p.stop,p.tp1,p.tp2,nowIso).run();
  if((r.meta?.changes||0)===0)continue; // idempotent on retries
  published++;
  if(!eligible)continue;
  parsed.source=p.bucket==='SWING_TOP_PICK'?'Market Setup Watch / Swing':'Market Setup Watch / Intraday';
  const q=await env.DB.prepare(
   "INSERT OR IGNORE INTO signal_monitors(id,symbol,source,direction,bucket,score,entry_low,entry_high,stop,tp1,tp2,created_at,updated_at,valid_until,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'WAIT_ENTRY')")
  .bind(parsed.id,parsed.symbol,parsed.source,parsed.direction,parsed.bucket,parsed.score,
    parsed.entryLow,parsed.entryHigh,parsed.stop,parsed.tp1,parsed.tp2,parsed.createdAt,nowIso,parsed.validUntil).run();
  tracked+=(q.meta?.changes||0);
 }
 if(tracked){try{await env.LIVE_ROOM.get(env.LIVE_ROOM.idFromName('atlas-usdt-futures')).fetch('https://room.internal/wake',{method:'POST'})}catch(e){console.error('ATLAS room wake',e)}}
 return ok({ok:true,published,tracked,rejected,confirmedSentAt:d.sentAt,semantics:'Confirmed Telegram text references. Only valid ready plans become price-level monitors; NOT executed trades.'});
}
