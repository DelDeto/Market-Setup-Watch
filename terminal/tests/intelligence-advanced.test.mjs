import test from 'node:test';
import assert from 'node:assert/strict';
import {openInterestDelta,wilsonInterval,strategyTournament,selfAudit,historicalVolatility,
 orderBookSummary,ruleBasedCopilot,buildAdvanced} from '../intelligence-advanced.js';

const ts=(hoursAgo)=>new Date(Date.now()-hoursAgo*3600*1000).toISOString();
const m=(id,source='scanner',win=true,hours=1,score=85)=>({id,source,created_at:ts(hours),score,status:win?'TP1_OBSERVED':'SL_OBSERVED',tp1_observed_at:win?ts(hours-.2):null});
test('open interest needs a time-separated real historical observation and keeps contract units',()=>{
 const history=[{symbol:'BTC_USDT',captured_at:ts(2),price:100,open_interest_contracts:1000},
 {symbol:'BTC_USDT',captured_at:ts(0),price:120,open_interest_contracts:1100}];
 const current=[{symbol:'BTC_USDT',price:120,openInterestContracts:1100}];
 const out=openInterestDelta(current,history);
 assert.equal(out.coverage,1);assert.equal(out.items[0].interpretation,'OI_UP_PRICE_UP');
 assert.equal(out.items[0].contractUnits,true);
 assert.equal(openInterestDelta(current,[]).coverage,0);
 assert.equal(openInterestDelta([{symbol:'BTC_USDT',price:120}],history).coverage,0);
});
test('Wilson intervals refuse zero sample or invalid inputs',()=>{
 assert.equal(wilsonInterval(0,0),null);
 assert.equal(wilsonInterval(5,4),null);
 const z=wilsonInterval(3,6);assert.ok(z.lower95Pct<50&&z.upper95Pct>50);assert.equal(z.n,6);
});
test('strategy tournament uses chronological holdout and never auto-promotes',()=>{
 const rows=Array.from({length:60},(_,i)=>m('m'+i,'A',i%3!==0,90-i));
 const x=strategyTournament(rows);assert.equal(x.reviewed,60);
 assert.equal(x.promotionAllowed,false);assert.ok(x.sources[0].eligible);
 assert.equal(x.sources[0].development.n,42);assert.equal(x.sources[0].heldOut.n,18);
 const sparse=strategyTournament([m('1'),m('2','a',false)]);assert.equal(sparse.sources[0].eligible,false);
 const broken=strategyTournament([{...m('x'),status:'DATA_GAP'}]);assert.equal(broken.reviewed,0);
});
test('self-audit fails closed for missing feeds and missing benchmarks',()=>{
 const s=selfAudit({});assert.equal(s.status,'DEGRADED');assert.ok(s.issues.length>=4);
 assert.equal(s.verifiedTelegramDelivery,false);assert.equal(s.autoStrategyTuning,false);
});
test('volatility EWMA uses at least 35 closed returns; positive one-sigma band',()=>{
 assert.equal(historicalVolatility([{close:100}],'BTC_USDT').available,false);
 const arr=Array.from({length:100},(_,i)=>({at:ts((100-i)),close:100*Math.exp(i*.002+.005*Math.sin(i))}));
 const x=historicalVolatility(arr,'BTC_USDT');
 assert.equal(x.available,true);assert.ok(x.sigmaLogReturnPct>0);
 assert.ok(x.simulatedPriceBand68[0]<arr.at(-1).close&&x.simulatedPriceBand68[1]>arr.at(-1).close);
 assert.equal(x.horizon,'1h');assert.match(x.caveat,/NOT/);
});
test('orderbook is contract-unit read only; detects empty/crossed books',()=>{
 const x=orderBookSummary({success:true,data:{bids:[[99,100,2],[98,50,1]],asks:[[101,80,1],[102,70,2]],timestamp:Date.now()}},'BTC_USDT');
 assert.equal(x.available,true);assert.equal(x.bidDepthContracts,150);assert.equal(x.liquidationHeatmapAvailable,false);
 assert.ok(x.spreadPct>0);
 assert.equal(orderBookSummary({data:{bids:[[102,1]],asks:[[101,1]]}},'BTC_USDT').available,false);
});
test('copilot is deterministic, bounded and never falsely claims generative AI',()=>{
 const x=ruleBasedCopilot('BTC trend',{intelligence:{marketRegime:{regime:'MIXED',btcChange24hPct:1.5,breadthPositivePct:52}}});
 assert.equal(x.mode,'RULE_BASED_EVIDENCE_ASSISTANT');assert.equal(x.model,'none');
 assert.match(x.answer,/MIXED/);assert.equal(ruleBasedCopilot('').status,'INVALID');
});
test('capabilities explicitly mark unavailable data and disabled auto trading',()=>{
 const out=buildAdvanced({snapshot:{items_json:JSON.stringify([{symbol:'BTC_USDT',price:100,openInterestContracts:500,changePct:2}])}});
 assert.equal(out.version,'5.0-evidence');
 assert.equal(out.capabilities.length,15);
 assert.match(out.capabilities.find(x=>x.name.includes('Liquidation')).status,/NO_LIQUIDATION/);
 assert.equal(out.tournament.promotionAllowed,false);
});
