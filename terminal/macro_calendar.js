// ATLAS V3.5.2: Official BLS scheduled economic-release calendar.
// Records *scheduled* times only. No fabricated actual/consensus/forecast values.
const ICAL='https://www.bls.gov/schedule/news_release/bls.ics';
const RESPONSE={'content-type':'application/json;charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
const formatter=(zone)=>new Intl.DateTimeFormat('en-US',{timeZone:zone,timeZoneName:'shortOffset',year:'numeric'});
function offsetMinutes(date,zone){
 const offset=formatter(zone).formatToParts(date).find(x=>x.type==='timeZoneName')?.value||'';
 const m=offset.match(/^GMT([+-]\d{1,2})(?::(\d{2}))?$/);
 if(!m)throw Error('UNSUPPORTED_ICAL_TIME_ZONE');
 const sign=m[1].startsWith('-')?-1:1;
 return sign*(Math.abs(Number(m[1]))*60+Number(m[2]||0));
}
export function icalToUtc(value,zone='America/New_York'){
 const s=String(value||'').trim();
 const m=s.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z)?$/);
 if(!m)return null;const [y,mo,d,h,mi,se]=m.slice(1,7).map(Number);
 if(mo<1||mo>12||d<1||d>31||h>23||mi>59||se>59)return null;
 const naive=Date.UTC(y,mo-1,d,h,mi,se);if(!Number.isFinite(naive))return null;
 if(m[7])return new Date(naive).toISOString();
 // BLS live iCalendar uses TZID=US-Eastern (hyphen), while Intl uses IANA America/New_York.
 if(!['America/New_York','US/Eastern','US-Eastern'].includes(zone))return null;
 const resolved='America/New_York';
 let corrected=naive-offsetMinutes(new Date(naive),resolved)*60000;
 corrected=naive-offsetMinutes(new Date(corrected),resolved)*60000;
 return new Date(corrected).toISOString();
}
const TAGS=[
 {key:'CPI',re:/consumer price index|\bcpi\b|consumer prices/i,impact:'HIGH'},
 {key:'JOBS',re:/employment situation|nonfarm|payrolls|unemployment rate/i,impact:'HIGH'},
 {key:'PPI',re:/producer price index|\bppi\b|producer prices/i,impact:'HIGH'},
 {key:'JOLTS',re:/job openings and labor turnover|\bjolts\b/i,impact:'MEDIUM'},
 {key:'ECI',re:/employment cost index/i,impact:'MEDIUM'},
 {key:'WAGES',re:/real earnings|average hourly earnings/i,impact:'MEDIUM'}
];
export function parseBlsCalendar(source,nowMs=Date.now()){
 // RFC 5545 line folding; input never executes code and all URL/times are validated.
 const unfolded=String(source||'').replace(/\r?\n[ \t]/g,'');
 const chunks=[...unfolded.matchAll(/BEGIN:VEVENT([\s\S]*?)END:VEVENT/g)].slice(0,1500);
 const rows=[],seen=new Set();
 for(const chunk of chunks){
  const lines=chunk[1].split(/\r?\n/).filter(Boolean);
  const property=(name)=>lines.find(x=>new RegExp('^'+name+'(?:;[^:]*)?:','i').test(x))?.replace(/^[^:]*:/,'')||'';
  const title=property('SUMMARY').replace(/\\,/g,',').replace(/\\;/g,';').replace(/\\n/g,' ').trim().slice(0,180);
  const startLine=lines.find(x=>/^DTSTART(?:;[^:]*)?:/.test(x))||'';
  const startParts=startLine.split(':');const timeRaw=startParts.slice(1).join(':');
  const zone=/TZID=([^;:]+)/.exec(startParts[0])?.[1]||'America/New_York';
  const start=icalToUtc(timeRaw,zone);
  const eventType=TAGS.find(x=>x.re.test(title));
  if(!eventType||!start)continue;
  const t=Date.parse(start);
  if(t<nowMs-5*86400000||t>nowMs+120*86400000)continue;
  const uid=(property('UID')||title+'@'+start).slice(0,230);
  const id='bls:'+eventType.key+':'+start;
  if(seen.has(id))continue;seen.add(id);
  const original=property('URL');
  let url='https://www.bls.gov/schedule/news_release/';
  if(original){try{const u=new URL(original);if(u.protocol==='https:'&&u.hostname==='www.bls.gov')url=u.href.slice(0,600)}catch{}}
  rows.push({id,uid,title,kind:eventType.key,impact:eventType.impact,scheduledAt:start,sourceUrl:url,sourceName:'U.S. Bureau of Labor Statistics',status:'SCHEDULED'});
 }
 return rows.sort((a,b)=>a.scheduledAt.localeCompare(b.scheduledAt));
}
export async function collectBlsCalendar(env,{nowMs=Date.now(),force=false}={}){
 const now=new Date(nowMs).toISOString();
 const old=await env.DB.prepare('SELECT last_attempt_at,last_success_at FROM macro_calendar_health WHERE source=?').bind('BLS_ICAL').first();
 if(!force&&old?.last_success_at&&old.last_attempt_at&&nowMs-Date.parse(old.last_attempt_at)<2*3600000)return {skipped:true,lastSuccess:old.last_success_at||null};
 let added=0,count=0,error=null;
 try{
  const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(),11000);
  let body;
  try{
   const r=await fetch(ICAL,{signal:ctrl.signal,headers:{Accept:'text/calendar,text/plain,*/*','User-Agent':'ATLAS-Economic-Calendar/3.5.2'}});
   if(!r.ok)throw Error('BLS_ICAL_HTTP_'+r.status);
   body=await r.text();if(body.length>2500000)throw Error('BLS_ICAL_TOO_LARGE');
  }finally{clearTimeout(timer)}
  if(!/BEGIN:VCALENDAR/.test(body)||!/BEGIN:VEVENT/.test(body))throw Error('BLS_ICAL_INVALID');
  const events=parseBlsCalendar(body,nowMs);count=events.length;
  if(!events.length){
   // Include sanitized public iCal structure in health for audit; no user data.
   const sample=body.match(/BEGIN:VEVENT([\s\S]*?)END:VEVENT/i)?.[1]||'';
   const lines=sample.split(/\r?\n/).map(x=>x.trim()).filter(x=>/^(SUMMARY|DTSTART|DTEND|UID|DESCRIPTION)(;|:)/i.test(x)).slice(0,3).map(x=>x.slice(0,70));
   throw Error('NO_BLS_RELEASES count='+((body.match(/BEGIN:VEVENT/g)||[]).length)+' first='+lines.join(' | '));
  }
  for(const e of events){
   const r=await env.DB.prepare("INSERT INTO macro_calendar_events(id,source_key,source_name,uid,title,kind,impact,scheduled_at,source_url,status,checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,impact=excluded.impact,source_url=excluded.source_url,checked_at=excluded.checked_at")
    .bind(e.id,'BLS_ICAL',e.sourceName,e.uid,e.title,e.kind,e.impact,e.scheduledAt,e.sourceUrl,e.status,now).run();added+=r.meta?.changes||0;
  }
  await env.DB.prepare("DELETE FROM macro_calendar_events WHERE source_key='BLS_ICAL' AND scheduled_at<?").bind(new Date(nowMs-7*86400000).toISOString()).run();
 }catch(e){error=String(e).slice(0,550)}
 await env.DB.prepare("INSERT INTO macro_calendar_health(source,last_attempt_at,last_success_at,last_error,last_count) VALUES(?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,last_success_at=COALESCE(excluded.last_success_at,macro_calendar_health.last_success_at),last_error=excluded.last_error,last_count=excluded.last_count")
  .bind('BLS_ICAL',now,error?null:now,error,count).run();
 return {checkedAt:now,success:!error,events:count,upserted:added,error};
}
export async function macroCalendarApi(env){
 const now=new Date().toISOString();
 const [events,health]=await Promise.all([
  env.DB.prepare('SELECT id,source_name,title,kind,impact,scheduled_at,source_url,status FROM macro_calendar_events WHERE scheduled_at>=? ORDER BY scheduled_at ASC LIMIT 28').bind(now).all(),
  env.DB.prepare("SELECT * FROM macro_calendar_health WHERE source='BLS_ICAL'").first()
 ]);
 return new Response(JSON.stringify({events:events.results||[],health:health||null,
  note:'Official BLS release schedule (America/New_York converted to UTC), can change without notice. Does NOT include actual, expected, consensus or surprise data. FOMC/ECB calendars not yet integrated.'}),{headers:RESPONSE});
}
