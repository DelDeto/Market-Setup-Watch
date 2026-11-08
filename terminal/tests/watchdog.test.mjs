import test from 'node:test';
import assert from 'node:assert/strict';
import {scanHealth,decideRecovery} from '../watchdog.js';

const base=Date.parse('2026-11-08T07:30:00.000Z');
const t=(mins)=>new Date(base-mins*60000).toISOString();
test('source timestamp (not D1 refresh timestamp) determines scanner freshness',()=>{
 assert.deepEqual(scanHealth(t(30),base),{status:'OK',ageSeconds:1800,reason:'FRESH'});
 assert.equal(scanHealth(t(46),base).status,'STALE');
 assert.equal(scanHealth(null,base).reason,'SCANNER_SOURCE_MISSING');
 assert.equal(scanHealth(new Date(base+6*60000).toISOString(),base).reason,'SCANNER_TIMESTAMP_IN_FUTURE');
});
test('never recover a healthy scanner',()=>{
 assert.equal(decideRecovery({status:'OK',nowMs:base,tokenConfigured:true}).action,'NONE');
});
test('an active GitHub scan blocks a duplicate recovery',()=>{
 const p=decideRecovery({status:'STALE',nowMs:base,tokenConfigured:true,
   runs:[{status:'in_progress',created_at:t(80)}]});
 assert.deepEqual(p,{action:'WAIT',reason:'GITHUB_RUN_ALREADY_ACTIVE'});
});
test('a run recently started blocks repeat dispatch',()=>{
 const p=decideRecovery({status:'STALE',nowMs:base,tokenConfigured:true,
   runs:[{status:'completed',created_at:t(15)}]});
 assert.equal(p.reason,'GITHUB_RUN_WITHIN_COOLDOWN');
});
test('Cloudflare recovery enforces 40-minute cooldown after any dispatch attempt',()=>{
 assert.equal(decideRecovery({status:'STALE',nowMs:base,tokenConfigured:true,
   lastDispatchAt:t(15)}).reason,'CLOUDFLARE_RECOVERY_COOLDOWN');
});
test('missing credentials never attempts unauthenticated GitHub dispatch',()=>{
 assert.deepEqual(decideRecovery({status:'STALE',nowMs:base,tokenConfigured:false}),
   {action:'BLOCKED',reason:'GITHUB_RECOVERY_TOKEN_NOT_CONFIGURED'});
});
test('failed Github inspection blocks dispatch even with valid token',()=>{
 assert.deepEqual(decideRecovery({status:'STALE',nowMs:base,githubError:'HTTP 429',tokenConfigured:true}),
   {action:'BLOCKED',reason:'GITHUB_INSPECTION_FAILED'});
});
test('only stale scanner, no active/recent run, available token triggers workflow',()=>{
 assert.equal(decideRecovery({status:'STALE',nowMs:base,tokenConfigured:true,
   runs:[{status:'completed',created_at:t(90)}]}).action,'DISPATCH');
});
