import test from 'node:test';
import assert from 'node:assert/strict';
import {marketRegime,anomalyRadar,sectorRotation,fundingRadar,signalLab,riskPreview,healthAudit,buildIntelligence} from '../intelligence.js';

const row=(symbol,changePct,turnover=2_000_000,funding=.0001)=>({symbol:symbol+'_USDT',price:100,changePct,turnover,funding,high:105,low:95});
const universe=[row('BTC',3),row('ETH',4),row('SOL',6),row('ADA',3),row('AVAX',2),row('NEAR',4),
...Array.from({length:40},(_,i)=>row('X'+i,2,1_000_000)),
row('ZEC',45,5_000_000,.003)];
test('regime is a descriptive breadth proxy; cannot claim AI probability',()=>{
 const r=marketRegime(universe,{regime:'BULLISH'},5);
 assert.equal(r.regime,'BULL_TREND_PROXY');assert.equal(r.scannerBias,'BULLISH');
 assert.equal(marketRegime([],{},null).regime,'INSUFFICIENT_DATA');
 assert.equal(marketRegime(universe,{regime:'BULLISH'},60).scannerBias,'UNVERIFIED_OR_STALE');
});
test('anomaly/flow radar show only observed 24h indicators',()=>{
 const a=anomalyRadar(universe);assert.ok(a.ready);assert.equal(a.items[0].symbol,'ZEC_USDT');
 const f=fundingRadar(universe);assert.equal(f.openInterestAvailable,false);assert.equal(f.liquidationsAvailable,false);
});
test('sector rotation labels only curated groups and never assumes missing sectors',()=>{
 const s=sectorRotation(universe);assert.ok(s.groups.some(x=>x.sector==='Layer 1'));
 assert.ok(s.coverage.includes('curated'));
});
test('observational TP1-first is not live win rate or realized PnL',()=>{
 const rows=[{id:'1',source:'Scanner',status:'TP2_OBSERVED',tp1_observed_at:'2026-11-08T00:00:00Z'},
 {id:'2',source:'Scanner',status:'SL_OBSERVED',tp1_observed_at:null},
 {id:'3',source:'Scanner',status:'AMBIGUOUS',tp1_observed_at:null}];
 const s=signalLab(rows,[{id:'pub1'}]);assert.equal(s.unambiguousResolved,2);
 assert.equal(s.ambiguousOrGapped,1);assert.equal(s.tp1FirstRatePct,50);
 assert.equal(s.statisticallySufficient,false);
});
test('risk sizing direction check, percentage cap and account isolation',()=>{
 let x=riskPreview({equity:1000,entry:100,stop:98,riskPct:1,maxExposurePct:20,direction:'LONG'});
 assert.equal(x.valid,true);assert.equal(x.units,2);assert.equal(x.modeledStopLoss,4);assert.ok(x.exposureCapped);
 assert.equal(riskPreview({equity:1000,entry:100,stop:110,riskPct:1,direction:'LONG'}).valid,false);
 assert.equal(riskPreview({equity:1000,entry:100,stop:98,riskPct:10}).valid,false);
 assert.equal(riskPreview({equity:1000,entry:100,stop:102,riskPct:1,direction:'SHORT'}).valid,true);
});
test('freshness audit reports unknown and stale, never zeroes errors',()=>{
 const a=healthAudit({});assert.equal(a.status,'DEGRADED');assert.equal(a.failures.length,4);
 const b=healthAudit({snapshotAt:'2020-01-01T00:00:00Z'});assert.equal(b.sources.market.status,'STALE');
});
test('report avoids fake intelligence when D1 snapshot missing',()=>{
 const r=buildIntelligence({});assert.equal(r.marketRegime.instruments,0);assert.equal(r.health.status,'DEGRADED');
 assert.equal(r.capabilities.find(x=>x.name==='AI Copilot').status,'NOT_ENABLED');
});
