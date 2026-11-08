import test from 'node:test';
import assert from 'node:assert/strict';
import {Script} from 'node:vm';
import {readFileSync} from 'node:fs';
import {relationshipClientJs} from '../relationship-client.js';
const source=readFileSync(new URL('../worker.js',import.meta.url),'utf8');
const m=source.match(/\nconst HTML=("(?:\\.|[^"\\])*");\s*$/s);
assert.ok(m,'HTML payload');
const html=JSON.parse(m[1]);
test('relationship client script compiles as a classic browser script',()=>{
 assert.ok(relationshipClientJs.length>3000);
 assert.doesNotThrow(()=>new Script(relationshipClientJs));
});
test('read-only Pair Relationship tab controls and chart canvases exist',()=>{
 for(const id of ['relationshipTab','pairAssetA','pairAssetB','pairTf','pairGo','pairCorrelation','pairRolling',
   'pairBeta','pairSamples','pairReturnA','pairReturnB','pairRelative','pairVolRatio',
   'pairPriceChart','pairRollingChart','pairSourceStatus','pairNote'])
   assert.ok(html.includes('id="'+id+'"'),'Missing '+id);
 assert.ok(html.includes('src="/assets/relationship.js"'));
 assert.ok(html.includes("relationship:'Pair Relationship Lab'"));
 assert.ok(html.includes("'macro','relationship','research'"));
});
test('public pair endpoints are read-only and served under same origin',()=>{
 assert.ok(source.includes("url.pathname==='/api/relationship')return relationshipApi(url)"));
 assert.ok(source.includes("url.pathname==='/assets/relationship.js'"));
 assert.ok(!relationshipClientJs.includes('api/ingest'));
 assert.ok(!relationshipClientJs.includes('api/alerts/ack'));
});
test('client has source notices and accurate comparison options',()=>{
 assert.ok(html.includes('indicative daily index derived from ECB FX references'));
 assert.ok(relationshipClientJs.includes('plotRelationship('));
 assert.ok(relationshipClientJs.includes('relKind('));
 assert.ok(relationshipClientJs.includes('window.analyzeRelationship=analyzeRelationship'));
});

test('Pair comparison follows ICT/UTC toggle while daily sessions retain date meaning',()=>{
 assert.ok(relationshipClientJs.includes('function relDisplayTime(value,daily)'));
 assert.ok(relationshipClientJs.includes("formatStamp(value)"));
 assert.ok(html.includes("if(state.tab==='relationship'&&window.renderRelationship)window.renderRelationship()"));
});
