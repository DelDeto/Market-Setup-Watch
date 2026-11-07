import WebSocket from 'ws';
const base=process.env.ATLAS_URL||'https://atlas-terminal-v2-preview.duc-nguyen-ndd127.workers.dev';
const url=base.replace(/^http/,'ws')+'/api/ws';
const client=new WebSocket(url,{headers:{'User-Agent':'ATLAS-Preview-Validation/2.0'},handshakeTimeout:15000});
let completed=false;
const fail=(m)=>{if(completed)return;completed=true;console.error(m);client.terminate();process.exit(1)};
const timer=setTimeout(()=>fail('Timeout: no server-pushed MEXC data within 45 seconds'),45000);
client.on('message',raw=>{
 try{
  const msg=JSON.parse(raw.toString());
  if(msg.type==='hello'){console.log('WebSocket connected:',msg.mode)}
  if(msg.type==='error')console.warn('WebSocket upstream warning:',msg.message);
  if(msg.type==='market'){
   if(!Array.isArray(msg.items)||msg.items.length<50)return fail('Too few market symbols');
   if(!msg.updatedAt||!msg.mode?.includes('REST'))return fail('Missing source provenance');
   console.log('WebSocket market push OK',msg.updatedAt,msg.items.length);
   completed=true;clearTimeout(timer);client.close();process.exit(0);
  }
 }catch(e){fail(e.stack||e.message)}
});
client.on('unexpected-response',(_,r)=>fail('Upgrade rejected HTTP '+r.statusCode));
client.on('error',e=>fail('WebSocket error: '+String(e)));
