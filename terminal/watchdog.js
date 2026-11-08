// ATLAS V3.1: Independent Cloudflare Cron watchdog.
// Public state is read-only. Recovery dispatch requires a private, repo-scoped
// GitHub Actions write token. No unauthenticated trigger or auto trading.
import {verifyGitHubOIDC} from './live.js';
const REPO='DelDeto/Market-Setup-Watch',FLOW='market-setup-watch.yml';
const GH='https://api.github.com/repos/'+REPO+'/actions/workflows/'+FLOW;
const SOURCE_MAX_AGE=45*60000, RECOVERY_COOLDOWN=40*60000,GH_CHECK_INTERVAL=12*60000;
const HEADERS={'content-type':'application/json;charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
function response(x,status=200){return new Response(JSON.stringify(x),{status,headers:HEADERS})}
export function scanHealth(sourceTime,nowMs=Date.now()){
 const stamp=sourceTime?Date.parse(sourceTime):NaN;
 if(!Number.isFinite(stamp))return {status:'STALE',ageSeconds:null,reason:'SCANNER_SOURCE_MISSING'};
 const delta=nowMs-stamp;
 if(delta < -300000)return {status:'STALE',ageSeconds:Math.round(delta/1000),reason:'SCANNER_TIMESTAMP_IN_FUTURE'};
 return {status:delta>SOURCE_MAX_AGE?'STALE':'OK',ageSeconds:Math.round(delta/1000),reason:delta>SOURCE_MAX_AGE?'SCANNER_TOO_OLD':'FRESH'};
}
export function decideRecovery({status,nowMs=Date.now(),lastDispatchAt=null,runs=[],githubError=null,tokenConfigured=false}){
 if(status!=='STALE')return {action:'NONE',reason:'SCANNER_HEALTHY'};
 if(githubError)return {action:'BLOCKED',reason:'GITHUB_INSPECTION_FAILED'};
 const active=runs.some(x=>['in_progress','queued','waiting','pending','requested'].includes(x.status));
 if(active)return {action:'WAIT',reason:'GITHUB_RUN_ALREADY_ACTIVE'};
 const recent=runs.some(x=>{const t=Date.parse(x.created_at||'');return Number.isFinite(t)&&nowMs-t>=0&&nowMs-t<RECOVERY_COOLDOWN});
 if(recent)return {action:'WAIT',reason:'GITHUB_RUN_WITHIN_COOLDOWN'};
 const prev=lastDispatchAt?Date.parse(lastDispatchAt):NaN;
 if(Number.isFinite(prev)&&nowMs-prev<RECOVERY_COOLDOWN)return {action:'WAIT',reason:'CLOUDFLARE_RECOVERY_COOLDOWN'};
 if(!tokenConfigured)return {action:'BLOCKED',reason:'GITHUB_RECOVERY_TOKEN_NOT_CONFIGURED'};
 return {action:'DISPATCH',reason:'STALE_AND_NO_RECENT_RUN'};
}
async function githubRuns(){
 const c=new AbortController();const timer=setTimeout(()=>c.abort(),9000);
 try{
  const r=await fetch(GH+'/runs?per_page=12',{headers:{'Accept':'application/vnd.github+json','User-Agent':'ATLAS-Cloudflare-Watchdog/3.1','X-GitHub-Api-Version':'2022-11-28'},signal:c.signal});
  if(!r.ok)throw Error('GITHUB_RUNS_HTTP_'+r.status);
  const d=await r.json();
  if(!Array.isArray(d.workflow_runs))throw Error('GITHUB_RUNS_INVALID');
  return d.workflow_runs.map(x=>({id:x.id,status:x.status,created_at:x.created_at,conclusion:x.conclusion})).slice(0,12);
 }finally{clearTimeout(timer)}
}
async function dispatchWorkflow(token){
 const c=new AbortController(),timer=setTimeout(()=>c.abort(),12000);
 try{
  const r=await fetch(GH+'/dispatches',{method:'POST',headers:{'Accept':'application/vnd.github+json',
   'X-GitHub-Api-Version':'2022-11-28','User-Agent':'ATLAS-Cloudflare-Watchdog/3.1',
   'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({ref:'main'}),signal:c.signal});
  if(r.status!==204&&r.status!==200)throw Error('GITHUB_DISPATCH_HTTP_'+r.status);
  return true;
 }finally{clearTimeout(timer)}
}
function notice(kind,sourceTime,now,ageSeconds,reason){
 const age=ageSeconds===null?'unknown':Math.max(0,Math.round(ageSeconds/60))+' min';
 const text=kind==='SCANNER_STALE'?
  '⚠️ ATLAS SCANNER STALE\nSource scan age: '+age+'\nSource timestamp (UTC): '+(sourceTime||'missing')+
  '\nCause: '+reason+'\nCloudflare independently detected scanner lag. GitHub recovery is rate-limited. No trades are executed.':
  kind==='SCANNER_RECOVERED'?
  '✅ ATLAS SCANNER RECOVERED\nSource timestamp (UTC): '+(sourceTime||'unknown')+'\nCloudflare independent watchdog confirms scanner freshness.':
  '🔄 ATLAS SCANNER RECOVERY DISPATCHED\nSource age: '+age+'\nDispatched existing Market Setup Watch workflow, with 40-min cooldown.';
 return text+'\nhttps://atlas-market-terminal.duc-nguyen-ndd127.workers.dev';
}
async function createNotice(env,id,kind,sourceTime,now,ageSeconds,reason){
 await env.DB.prepare("INSERT OR IGNORE INTO watchdog_notifications(id,kind,created_at,source_at,message,delivery_status) VALUES(?,?,?,?,?,'pending')")
 .bind(id,kind,now,sourceTime,notice(kind,sourceTime,now,ageSeconds,reason)).run();
}
async function sendDirectTelegram(env){
 const token=env.WATCHDOG_TELEGRAM_BOT_TOKEN,chat=env.WATCHDOG_TELEGRAM_CHAT_ID;
 if(!token||!chat)return {configured:false,delivered:0};
 const rows=await env.DB.prepare("SELECT id,message FROM watchdog_notifications WHERE delivery_status='pending' ORDER BY created_at ASC LIMIT 3").all();
 let delivered=0;
 for(const row of rows.results||[]){
  const lease=new Date(Date.now()+240000).toISOString();
  const locked=await env.DB.prepare("UPDATE watchdog_notifications SET delivery_status='leased',leased_until=? WHERE id=? AND delivery_status='pending'").bind(lease,row.id).run();
  if(!(locked.meta?.changes))continue;
  try{
   const c=new AbortController(),t=setTimeout(()=>c.abort(),12000);
   let data;
   try{
    const res=await fetch('https://api.telegram.org/bot'+token+'/sendMessage',{method:'POST',
     headers:{'content-type':'application/json'},body:JSON.stringify({chat_id:chat,text:row.message,disable_web_page_preview:true}),signal:c.signal});
    if(!res.ok)throw Error('TELEGRAM_HTTP_'+res.status);
    data=await res.json();
   }finally{clearTimeout(t)}
   if(data.ok!==true)throw Error('TELEGRAM_REJECTED');
   await env.DB.prepare("UPDATE watchdog_notifications SET delivery_status='sent',delivered_at=?,leased_until=NULL WHERE id=? AND delivery_status='leased'").bind(new Date().toISOString(),row.id).run();
   delivered++;
  }catch(e){
   await env.DB.prepare("UPDATE watchdog_notifications SET delivery_status='pending',leased_until=NULL WHERE id=? AND delivery_status='leased'").bind(row.id).run();
   console.error('Direct watchdog Telegram failed',String(e));
  }
 }
 return {configured:true,delivered};
}
export async function runCloudflareWatchdog(env,{nowMs=Date.now()}={}){
 const at=new Date(nowMs).toISOString();
 const [scan,previous]=await Promise.all([
  env.DB.prepare('SELECT source_updated_at FROM scanner_snapshots WHERE id=1').first(),
  env.DB.prepare('SELECT * FROM watchdog_state WHERE id=1').first()
 ]);
 const sourceTime=scan?.source_updated_at||null,health=scanHealth(sourceTime,nowMs);
 const tokenConfigured=Boolean(env.GITHUB_RECOVERY_TOKEN),telegramConfigured=Boolean(env.WATCHDOG_TELEGRAM_BOT_TOKEN&&env.WATCHDOG_TELEGRAM_CHAT_ID);
 let githubCheckedAt=previous?.github_checked_at||null;
 let githubRunAt=previous?.github_run_at||null,githubRunStatus=previous?.github_run_status||null;
 let dispatchAt=previous?.last_dispatch_at||null,dispatchStatus=previous?.last_dispatch_status||null;
 let error=null,note=health.reason,action='NONE';
 const shouldCheck=health.status==='STALE'&&(!githubCheckedAt||nowMs-Date.parse(githubCheckedAt)>=GH_CHECK_INTERVAL);
 if(health.status==='STALE'){
  if(shouldCheck){
   let runs=[],ghError=null;
   try{
    runs=await githubRuns();
    const latest=runs[0]||null;
    githubRunAt=latest?.created_at||null;
    githubRunStatus=latest?.status||null;
   }catch(e){ghError=String(e).slice(0,160)}
   githubCheckedAt=at;
   const plan=decideRecovery({status:health.status,nowMs,lastDispatchAt:dispatchAt,runs,githubError:ghError,tokenConfigured});
   action=plan.action;note=plan.reason;
   if(ghError)error=ghError;
   if(plan.action==='DISPATCH'){
    dispatchAt=at;dispatchStatus='ATTEMPTED';
    try{
     await dispatchWorkflow(env.GITHUB_RECOVERY_TOKEN);
     dispatchStatus='DISPATCHED';note='RECOVERY_DISPATCH_ACCEPTED';
     await createNotice(env,'recover-dispatched:'+at,'RECOVERY_DISPATCHED',sourceTime,at,health.ageSeconds,note);
    }catch(e){error=String(e).slice(0,160);dispatchStatus='FAILED';note='RECOVERY_DISPATCH_FAILED'}
   }
  }else{action='WAIT';note='GITHUB_INSPECTION_THROTTLED'}
 }
 const previouslyStale=previous?.status==='STALE';
 if(health.status==='STALE'&&!previouslyStale){
  await createNotice(env,'stale:'+at,'SCANNER_STALE',sourceTime,at,health.ageSeconds,note);
 }else if(health.status==='OK'&&previouslyStale){
  await createNotice(env,'recovered:'+at,'SCANNER_RECOVERED',sourceTime,at,health.ageSeconds,note);
 }
 await env.DB.prepare(
 "INSERT INTO watchdog_state(id,checked_at,status,scanner_source_at,scanner_age_seconds,last_healthy_at,github_checked_at,github_run_at,github_run_status,last_dispatch_at,last_dispatch_status,last_dispatch_error,direct_recovery_configured,direct_telegram_configured,note) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET checked_at=excluded.checked_at,status=excluded.status,scanner_source_at=excluded.scanner_source_at,scanner_age_seconds=excluded.scanner_age_seconds,last_healthy_at=excluded.last_healthy_at,github_checked_at=excluded.github_checked_at,github_run_at=excluded.github_run_at,github_run_status=excluded.github_run_status,last_dispatch_at=excluded.last_dispatch_at,last_dispatch_status=excluded.last_dispatch_status,last_dispatch_error=excluded.last_dispatch_error,direct_recovery_configured=excluded.direct_recovery_configured,direct_telegram_configured=excluded.direct_telegram_configured,note=excluded.note")
 .bind(at,health.status,sourceTime,health.ageSeconds,health.status==='OK'?at:previous?.last_healthy_at||null,
  githubCheckedAt,githubRunAt,githubRunStatus,dispatchAt,dispatchStatus,error,tokenConfigured?1:0,telegramConfigured?1:0,note).run();
 const telegram=await sendDirectTelegram(env);
 return {at,status:health.status,ageSeconds:health.ageSeconds,action,note,telegram:telegram.configured?'direct':'github_relay'};
}
export async function watchdogStatus(env){
 const [state,queue]=await Promise.all([
  env.DB.prepare('SELECT * FROM watchdog_state WHERE id=1').first(),
  env.DB.prepare("SELECT kind,created_at,source_at,delivery_status,delivered_at FROM watchdog_notifications ORDER BY created_at DESC LIMIT 15").all()
 ]);
 return response({watchdog:state||{status:'INITIALIZING'},notices:queue.results||[],
  method:'Cloudflare independent cron 3min; GitHub source state age threshold 45min; cooldown 40min',
  recovery:'Direct GitHub workflow dispatch requires GITHUB_RECOVERY_TOKEN Worker secret. Existing GitHub watchdog provides fallback on its own schedule.',
  notifications:'Direct Telegram requires WATCHDOG_TELEGRAM_BOT_TOKEN and WATCHDOG_TELEGRAM_CHAT_ID; otherwise protected GitHub OIDC relay uses existing secrets.'});
}
export async function claimWatchdogNotices(req,env){
 try{await verifyGitHubOIDC(req,'atlas-event-dispatch.yml')}catch(e){return response({error:'unauthorized',detail:String(e.message)},401)}
 const now=new Date().toISOString(),lease=new Date(Date.now()+4*60000).toISOString();
 const rows=await env.DB.prepare("SELECT id,kind,message,created_at FROM watchdog_notifications WHERE delivery_status='pending' OR (delivery_status='leased' AND leased_until<?) ORDER BY created_at ASC LIMIT 8").bind(now).all();
 const claimed=[];
 for(const x of rows.results||[]){
  const r=await env.DB.prepare("UPDATE watchdog_notifications SET delivery_status='leased',leased_until=? WHERE id=? AND (delivery_status='pending' OR (delivery_status='leased' AND leased_until<?))").bind(lease,x.id,now).run();
  if((r.meta?.changes||0)>0)claimed.push(x);
 }
 return response({notices:claimed,leased_until:lease});
}
export async function ackWatchdogNotices(req,env){
 try{await verifyGitHubOIDC(req,'atlas-event-dispatch.yml')}catch(e){return response({error:'unauthorized',detail:String(e.message)},401)}
 let d;try{d=await req.json()}catch{return response({error:'invalid JSON'},400)}
 if(!Array.isArray(d.ids)||d.ids.length>8)return response({error:'invalid ids'},422);
 let count=0;
 for(const id of d.ids){
  if(typeof id!=='string'||id.length>160)continue;
  const r=await env.DB.prepare("UPDATE watchdog_notifications SET delivery_status='sent',delivered_at=?,leased_until=NULL WHERE id=? AND delivery_status='leased'").bind(new Date().toISOString(),id).run();
  count+=r.meta?.changes||0;
 }
 return response({ok:true,acknowledged:count});
}
