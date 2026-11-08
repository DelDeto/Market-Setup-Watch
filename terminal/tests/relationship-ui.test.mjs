import test from 'node:test';
import assert from 'node:assert/strict';
import {Script, createContext, runInContext} from 'node:vm';
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


test('Asset A and B are native dropdowns with searchable filters and live catalog status',()=>{
 for(const id of ['pairAssetA','pairAssetB']){
  assert.match(html,new RegExp('<select id="'+id+'"'));
  assert.doesNotMatch(html,new RegExp('<input id="'+id+'"'));
 }
 for(const id of ['pairFilterA','pairFilterB','pairAssetCatalogStatus'])
  assert.ok(html.includes('id="'+id+'"'),'Missing '+id);
 assert.ok(relationshipClientJs.includes("get('/api/market')"));
 assert.ok(relationshipClientJs.includes('window.loadPairAssetCatalog=loadPairAssetCatalog'));
 assert.ok(html.includes("if(window.loadPairAssetCatalog)window.loadPairAssetCatalog()"));
});
test('both dropdowns populate from MEXC, retain DXY and preserve independent selection during search',async()=>{
 class Control{
  constructor(value=''){this.value=value;this.dataset={};this.handlers={};this.options=[];this.textContent=''}
  addEventListener(event,fn){this.handlers[event]=fn}
  replaceChildren(fragment){this.options=fragment.nodes;this.value=this.options[0]?.value||''}
 }
 const els={
  pairAssetA:new Control('BTC'),pairAssetB:new Control('ZEC'),
  pairFilterA:new Control(''),pairFilterB:new Control(''),
  pairGo:new Control(),pairAssetCatalogStatus:new Control(),
 };
 const document={
  createDocumentFragment:()=>({nodes:[],appendChild(opt){this.nodes.push(opt)}}),
  querySelectorAll:()=>[]
 };
 const ctx=createContext({
  document,Option:function(label,value){this.label=label;this.value=value},
  state:{markets:[{symbol:'BTC_USDT'},{symbol:'ZEC_USDT'},{symbol:'SOL_USDT'},{symbol:'ETH_USDT'}, {symbol:'bad'},{symbol:'BTC_USDT'}]},
  window:{addEventListener:()=>{}},$:id=>els[id],
  get:async()=>{throw Error('Should use already fetched market state')},
  console
 });
 runInContext(relationshipClientJs,ctx);
 await ctx.window.loadPairAssetCatalog();
 const values=id=>els[id].options.map(o=>o.value);
 for(const id of ['pairAssetA','pairAssetB']){
  assert.ok(values(id).includes('SOL'));
  assert.ok(values(id).includes('DXY'));
  assert.equal(values(id).filter(x=>x==='BTC').length,1);
 }
 assert.equal(els.pairAssetA.value,'BTC');
 assert.equal(els.pairAssetB.value,'ZEC');
 els.pairFilterA.value='SOL';
 els.pairFilterA.handlers.input();
 assert.deepEqual(values('pairAssetA'),['BTC','SOL']); // chosen asset is retained
 assert.ok(values('pairAssetB').includes('ETH')); // filters independent
 assert.match(els.pairAssetCatalogStatus.textContent,/MEXC Futures assets/);
});
