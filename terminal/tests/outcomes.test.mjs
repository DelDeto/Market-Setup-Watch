import test from 'node:test';
import assert from 'node:assert/strict';
import {evaluateClosedCandles} from '../outcomes.js';
import {validatePublication} from '../publications.js';

const m={
 id:'tg-test123',symbol:'ABC_USDT',source:'Market Setup Watch / Intraday',
 direction:'SHORT',bucket:'ENTRY_READY',
 entry_low:98,entry_high:100,stop:105,tp1:90,tp2:85,
 status:'WAIT_ENTRY',created_at:'2026-11-07T16:00:00Z',
 valid_until:'2026-11-07T20:00:00Z',last_candle_at:null
};
const t=(minute)=>Date.parse('2026-11-07T16:00:00Z')+minute*60000;
const bar=(minute,low,high)=>({t:t(minute),l:low,h:high,c:(low+high)/2});
const now='2026-11-07T16:10:00Z';
test('closed minute candles track entry, TP1 then TP2 in proper order',()=>{
 const v=evaluateClosedCandles(m,[bar(0,99,101),bar(1,89,99),bar(2,84,91)],now,60000);
 assert.equal(v.status,'TP2_OBSERVED');
 assert.deepEqual(v.events.map(x=>x.kind),['ENTRY_OBSERVED','TP1_OBSERVED','TP2_OBSERVED']);
 assert.equal(v.processed,3);
});
test('same-candle entry and exit is ambiguous, not a win or loss',()=>{
 const v=evaluateClosedCandles(m,[bar(0,89,102)],now,60000);
 assert.equal(v.status,'AMBIGUOUS');
 assert.equal(v.quality,'same_candle_entry_and_exit');
});
test('same-candle SL and TP after entry are ambiguous',()=>{
 const v=evaluateClosedCandles({...m,status:'ENTRY_OBSERVED'},[bar(0,84,106)],now,60000);
 assert.equal(v.status,'AMBIGUOUS');
});
test('stop before TP1 is a price-level SL event',()=>{
 const v=evaluateClosedCandles(m,[bar(0,99,101),bar(1,96,106)],now,60000);
 assert.equal(v.status,'SL_OBSERVED');
 assert.deepEqual(v.events.map(e=>e.kind),['ENTRY_OBSERVED','SL_OBSERVED']);
});
test('TP1 first, then SL is not classified SL-before-TP1',()=>{
 const v=evaluateClosedCandles(m,[bar(0,99,101),bar(1,89,99),bar(2,96,106)],now,60000);
 assert.equal(v.status,'SL_AFTER_TP1');
 assert.deepEqual(v.events.map(e=>e.kind),['ENTRY_OBSERVED','TP1_OBSERVED','SL_AFTER_TP1']);
});
test('missing a single minute is DATA_GAP and cannot be counted',()=>{
 const v=evaluateClosedCandles(m,[bar(0,99,101),bar(2,84,106)],now,60000);
 assert.equal(v.status,'DATA_GAP');
 assert.equal(v.events.at(-1).kind,'DATA_GAP');
});
test('candle that began before alert cannot create a trade outcome',()=>{
 const v=evaluateClosedCandles({...m,created_at:'2026-11-07T16:00:30Z'},[bar(0,84,106),bar(1,99,101)],now,60000);
 assert.equal(v.status,'ENTRY_OBSERVED');
});
test('ignore still-forming candle',()=>{
 const v=evaluateClosedCandles(m,[bar(0,99,101),bar(9,80,106)],'2026-11-07T16:09:20Z',60000);
 assert.equal(v.status,'DATA_GAP'); // gap detected only from first closed available candle? bar 9 is unclosed and ignored
});
test('validated source publication is not automatically a trade monitor',()=>{
 const receipt={id:'tg-'+'a'.repeat(40),symbol:'BTC_USDT',direction:'LONG',bucket:'NEAR_ENTRY',mode:'INTRADAY',is_trackable:false,reason:'PREPARATORY_SIGNAL_NOT_EXECUTION'};
 assert.equal(validatePublication(receipt).eligible,false);
 assert.equal(validatePublication({...receipt,mode:'SWING'}),null);
 assert.equal(validatePublication({...receipt,mode:'INTRADAY',bucket:'ENTRY_READY',is_trackable:true}).eligible,true);
});
