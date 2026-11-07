import test from 'node:test';
import assert from 'node:assert/strict';
import {parseMonitor, transition} from '../live.js';

const t='2026-11-07T16:00:00.000Z';
const raw={id:'setup-sample-12345',symbol:'BTC_USDT',direction:'SHORT',bucket:'ENTRY_READY',score:82,entry_low:98,entry_high:100,stop:105,tp1:90,tp2:85};
const valid=parseMonitor(raw,t);
test('validate geometry and expiry',()=>{
 assert.equal(valid.symbol,'BTC_USDT');
 assert.equal(valid.validUntil,'2026-11-07T20:00:00.000Z');
 assert.equal(parseMonitor({...raw,stop:97},t),null);
 assert.equal(parseMonitor({...raw,entry_low:null},t),null);
 assert.equal(parseMonitor({...raw,direction:'BUY'},t),null);
});
test('watching setup is not treated as executed trade',()=>{
 const m={...valid,entry_low:98,entry_high:100,status:'WAIT_ENTRY',valid_until:'2026-11-07T20:00:00Z',direction:'SHORT'};
 assert.equal(transition(m,91,'2026-11-07T16:01:00Z'),null);
 assert.deepEqual(transition(m,99,'2026-11-07T16:01:00Z'),{status:'ENTRY_OBSERVED',kind:'ENTRY_OBSERVED',price:99});
});
test('short stop and take-profit are only observed after entry',()=>{
 const m={...valid,status:'ENTRY_OBSERVED',valid_until:'2026-11-07T20:00:00Z',direction:'SHORT'};
 assert.equal(transition(m,105,'2026-11-07T16:02:00Z').status,'SL_OBSERVED');
 assert.equal(transition(m,90,'2026-11-07T16:02:00Z').status,'TP1_OBSERVED');
 assert.equal(transition(m,84,'2026-11-07T16:02:00Z').status,'TP2_OBSERVED');
});
test('long target and stop geometry',()=>{
 const p=parseMonitor({...raw,direction:'LONG',stop:95,tp1:110,tp2:115},t);
 assert.equal(transition({...p,status:'ENTRY_OBSERVED'},112,'2026-11-07T16:01:00Z').status,'TP1_OBSERVED');
 assert.equal(transition({...p,status:'ENTRY_OBSERVED'},94,'2026-11-07T16:01:00Z').status,'SL_OBSERVED');
});
test('expiry takes precedence over stale levels',()=>{
 const m={...valid,status:'WAIT_ENTRY',valid_until:'2026-11-07T16:10:00Z'};
 assert.equal(transition(m,99,'2026-11-07T16:20:00Z').status,'EXPIRED');
 assert.equal(transition(m,null,'2026-11-07T16:20:00Z').status,'EXPIRED');
});
