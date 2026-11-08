import test from 'node:test';
import assert from 'node:assert/strict';
import {assetName,dxyEstimate,parseEcb90DayXml,parseFrankfurter,alignPairs,pearson,analyzeRelationships} from '../relationships.js';

const day=(s)=>Date.parse(s+'T00:00:00Z');
test('MEXC asset symbol validation and protected DXY aliases',()=>{
 assert.equal(assetName('btc'),'BTC_USDT');
 assert.equal(assetName('zec_usdt'),'ZEC_USDT');
 assert.equal(assetName('ETHUSDT'),'ETH_USDT');
 assert.equal(assetName('DXY'),'DXY');
 assert.equal(assetName('USDx'),'DXY');
 assert.equal(assetName('../../foo'),null);
 assert.equal(assetName('BTC?foo'),null);
});
test('ECB implied DXY formula uses all six currencies and rejects missing',()=>{
 const rates={USD:1.1,JPY:160,GBP:.85,CAD:1.5,SEK:11.2,CHF:.97};
 const result=dxyEstimate(rates);
 assert.ok(result>50&&result<180,'indicative value in plausible historical range');
 assert.equal(dxyEstimate({...rates,JPY:null}),null);
 assert.equal(dxyEstimate({...rates,USD:0}),null);
});
test('official ECB XML parser accepts Cube and excludes invalid/incomplete rate dates',()=>{
 const xml='<?xml version="1.0"?><gesmes:Envelope xmlns:gesmes="http://example.org"><Cube>'+
 "<Cube time='2026-11-05'><Cube currency='USD' rate='1.1'/><Cube currency='JPY' rate='160'/><Cube currency='GBP' rate='0.85'/><Cube currency='CAD' rate='1.5'/><Cube currency='SEK' rate='11.2'/><Cube currency='CHF' rate='0.97'/></Cube>"+
 "<Cube time='2026-11-04'><Cube currency='USD' rate='1.15'/><Cube currency='JPY' rate='161'/></Cube></Cube></gesmes:Envelope>";
 const x=parseEcb90DayXml(xml);
 assert.equal(x.length,1);
 assert.equal(x[0].t,day('2026-11-05'));
});
test('Frankfurter fallback keeps ECB daily dates and rejects partial quotes',()=>{
 const r={rates:{'2026-11-05':{USD:1.1,JPY:160,GBP:.85,CAD:1.5,SEK:11.2,CHF:.97},'2026-11-06':{USD:1.1}}};
 const x=parseFrankfurter(r);
 assert.equal(x.length,1);assert.equal(x[0].t,day('2026-11-05'));
});
test('align matching observation timestamps; never forward fill weekends',()=>{
 const a=[{t:day('2026-11-06'),close:100},{t:day('2026-11-07'),close:101},
   {t:day('2026-11-08'),close:102},{t:day('2026-11-09'),close:103}];
 const b=[{t:day('2026-11-06'),close:100},{t:day('2026-11-09'),close:105}];
 const pairs=alignPairs(a,b,{daily:true});
 assert.deepEqual(pairs.map(x=>x.time),['2026-11-06','2026-11-09']);
});
test('correlation on log returns not on price levels: perfectly related series',()=>{
 const x=Array.from({length:58},(_,i)=>{
   const value=Math.sin(i*.7)*.011 +i*.00023;
   return {time:new Date(day('2026-01-01')+i*86400000).toISOString(),a:100*Math.exp(value+ i*.005),b:200*Math.exp(value*.5+i*.0025)}
 });
 const stats=analyzeRelationships(x);
 assert.ok(stats.available);
 assert.ok(stats.correlation>.999,JSON.stringify(stats));
 assert.ok(stats.beta>1.9&&stats.beta<2.1);
 assert.equal(stats.samples,57);
 assert.equal(stats.rolling.length,38);
});
test('inverse and uncorrelated classification with no causal assertion',()=>{
 const p=Array.from({length:60},(_,i)=>({time:String(i),a:Math.exp(i*.02+Math.sin(i)),b:Math.exp(-i*.02-Math.sin(i))}));
 const out=analyzeRelationships(p);
 assert.equal(out.relation,'STRONG_INVERSE');
 assert.ok(out.correlation<-.999);
 assert.match(out.interpretation,/not causation/i);
});
test('missing history and zero-variance returns cannot manufacture a correlation',()=>{
 const p=Array.from({length:26},(_,i)=>({time:String(i),a:100,b:100+i}));
 const out=analyzeRelationships(p);
 assert.equal(out.correlation,null);
 assert.equal(out.beta,0); // zero return variance of A with nonzero B variance yields beta 0
 assert.equal(out.relation,'INCONCLUSIVE');
 assert.equal(analyzeRelationships(p.slice(0,3)).available,false);
 assert.equal(pearson([1,1,1],[2,3,4]),null);
});
