import test from 'node:test';
import assert from 'node:assert/strict';
import {parseFeed,assess,FEEDS,selectReaction,parseAiResult} from '../macro.js';

const feed=FEEDS.find(x=>x.key==='fed_policy');
const bls=FEEDS.find(x=>x.key==='bls_cpi');
const now=Date.parse('2026-11-08T08:30:00Z');
function rss(items){return '<rss version="2.0"><channel>'+items.join('')+'</channel></rss>'}
function item(title,link,when='Sun, 08 Nov 2026 08:00:00 GMT',description='Policy announcement'){
 return '<item><title>'+title+'</title><link>'+link+'</link><pubDate>'+when+'</pubDate><description>'+description+'</description></item>'
}
test('parse official RSS publication timestamps, safe URLs and descriptions',()=>{
 const x=parseFeed(rss([item('Federal Reserve issues FOMC statement','https://www.federalreserve.gov/newsevents/pressreleases/monetary20261108a.htm?utm_campaign=x')]),feed,now);
 assert.equal(x.length,1);
 assert.equal(x[0].tier,'official');
 assert.equal(x[0].publishedAt,'2026-11-08T08:00:00.000Z');
 assert.ok(!x[0].url.includes('utm_campaign'));
});
test('refuse URL spoofing, javascript schemes, future news and older than 15d',()=>{
 const x=parseFeed(rss([
  item('fake','https://www.federalreserve.gov.evil.example/press'),
  item('fake2','javascript:alert(1)'),
  item('future','https://www.federalreserve.gov/press/future','Sun, 08 Nov 2026 09:30:00 GMT'),
  item('old','https://www.federalreserve.gov/press/old','Mon, 12 Oct 2026 08:30:00 GMT')
 ]),feed,now);
 assert.equal(x.length,0);
});
test('do not invent numbers, surprise or BTC direction from plain CPI headline',()=>{
 const x=assess({...parseFeed(rss([item('Consumer Price Index increases in October','https://www.bls.gov/news.release/cpi.toc.htm')]),bls,now)[0],title:'Consumer Price Index increases in October'});
 assert.equal(x.category,'INFLATION');
 assert.equal(x.impact,'HIGH');
 assert.equal(x.bias,'UNCERTAIN');
 assert.equal(x.forecastAvailable,false);
 assert.match(x.summaryVi,/chỉ dựa trên tiêu đề/i);
});
test('aggregate claims cannot be treated as official high-impact alerts',()=>{
 const x=assess({title:'SEC bitcoin ETF decision',description:'Unverified media headlines',tier:'aggregator'});
 assert.equal(x.impact,'MEDIUM');
 assert.equal(x.bias,'UNCERTAIN');
});
test('conditional higher-than-forecast inflation applies only scenario bias',()=>{
 const x=assess({title:'Inflation higher than expected',description:'',tier:'official'});
 assert.equal(x.bias,'RISK_OFF_POSSIBLE');
 assert.equal(x.confidence,'LOW');
});
test('allow only closed historical observations',()=>{
 const c=[{t:0,close:100},{t:60000,close:101},{t:120000,close:102}];
 assert.equal(selectReaction(c,0,60000,60000,180000)?.price,100);
 assert.equal(selectReaction(c,0,120000,60000,30000),null);
});


test('Workers AI returns structured object or JSON text without losing summary',()=>{
 const doc={summary_vi:'Báo cáo lao động Mỹ vừa được công bố.',rationale_vi:'Ảnh hưởng phụ thuộc số liệu so với kỳ vọng.'};
 assert.deepEqual(parseAiResult({response:doc}),doc);
 assert.deepEqual(parseAiResult({response:JSON.stringify(doc)}),doc);
 assert.deepEqual(parseAiResult({choices:[{message:{content:JSON.stringify(doc)}}]}),doc);
});
test('official SEC/ECB links cannot be spoofed',()=>{
 const sec=FEEDS.find(x=>x.key==='sec_releases');
 const ecb=FEEDS.find(x=>x.key==='ecb_press');
 assert.equal(parseFeed(rss([item('SEC digital asset regulation','https://sec.gov.evil.tld/press')]),sec,now).length,0);
 assert.equal(parseFeed(rss([item('ECB monetary policy press release','https://ecb.europa.eu.evil.tld/press')]),ecb,now).length,0);
});
