import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Script} from 'node:vm';
const src=readFileSync(new URL('../worker.js',import.meta.url),'utf8');
test('inline HTML dashboard JS is syntactically valid and routes are present',()=>{
 const match=src.match(/const HTML=("(?:\\.|[^"\\])*");\s*$/s);
 assert.ok(match,'Worker HTML string is present');
 const html=JSON.parse(match[1]);
 const script=html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
 assert.ok(script,'dashboard script is present');
 assert.doesNotThrow(()=>new Script(script));
 for(const id of ['trackingTab','pubrows','pubcount','moncount','outcomeRate','outcomeHealthNote','macroTab','macroNews','macroCount','macroFeeds','macroContextRows','macroCalendarRows','macroCalendarStatus','timezoneSelect','relationshipTab','pairAssetA','pairAssetB','pairGo','pairCorrelation','pairPriceChart','pairRollingChart'])
  assert.ok(html.includes('id="'+id+'"'),'Missing dashboard element: '+id);
 for(const url of ['/api/outcomes','/api/tracking','/api/ws','/api/macro','/api/macro/alerts/claim','/api/macro/calendar','/api/relationship'])
  assert.ok(src.includes(url),'Missing API route: '+url);
});
