import test from 'node:test';
import assert from 'node:assert/strict';
import {icalToUtc,parseBlsCalendar} from '../macro_calendar.js';
const now=Date.parse('2026-11-08T09:00:00Z');
const ics=(entries)=>'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'+entries.join('\r\n')+'\r\nEND:VCALENDAR';
const evt=(title,time,uid='sample')=>[
 'BEGIN:VEVENT','UID:'+uid,'SUMMARY:'+title,
 'DTSTART;TZID=America/New_York:'+time,
 'URL:https://www.bls.gov/schedule/news_release/',
 'END:VEVENT'].join('\r\n');
test('DST and EST in BLS iCalendar are converted to UTC correctly',()=>{
 assert.equal(icalToUtc('20261110T083000','America/New_York'),'2026-11-10T13:30:00.000Z');
 assert.equal(icalToUtc('20260310T083000','America/New_York'),'2026-03-10T12:30:00.000Z');
 assert.equal(icalToUtc('20261110T133000Z'),'2026-11-10T13:30:00.000Z');
 assert.equal(icalToUtc('20261110'),null);
});
test('realistic iCal filters and calendar source schedule',()=>{
 const xml=ics([
  evt('Consumer Price Index - October 2026','20261110T083000','1'),
  evt('Employment Situation','20261204T083000','2'),
  evt('Producer Price Index','20261113T083000','3'),
  evt('Training event unrelated','20261115T103000','4'),
  evt('Job Openings and Labor Turnover Survey','20261201T100000','5')
 ]);
 const rows=parseBlsCalendar(xml,now);
 assert.deepEqual(rows.map(x=>x.kind),['CPI','PPI','JOLTS','JOBS']);
 assert.equal(rows[0].scheduledAt,'2026-11-10T13:30:00.000Z');
 assert.equal(rows[0].impact,'HIGH');
 assert.equal(rows[0].sourceUrl,'https://www.bls.gov/schedule/news_release/');
});
test('unfold iCal lines; reject spoofed external source URLs and impossible start timestamps',()=>{
 const xml=ics([
 ['BEGIN:VEVENT','UID:real','SUMMARY:Consumer Price Index -',' October','DTSTART;TZID=America/New_York:20261110T083000','URL:https://evil.example/attack','END:VEVENT'].join('\r\n'),
 ['BEGIN:VEVENT','UID:bad','SUMMARY:Producer Price Index','DTSTART;TZID=America/New_York:20261310T083000','END:VEVENT'].join('\r\n')
 ]);
 const rows=parseBlsCalendar(xml,now);
 assert.equal(rows.length,1);
 assert.equal(rows[0].sourceUrl,'https://www.bls.gov/schedule/news_release/');
 assert.equal(rows[0].title,'Consumer Price Index -October');
});


test('iCal SUMMARY with language parameters and standard UID/URL are parsed',()=>{
 const input=ics([[
  'BEGIN:VEVENT','UID:jobs-2026',
  'SUMMARY;LANGUAGE=en-US:Employment Situation - November 2026',
  'DTSTART;TZID=America/New_York:20261204T083000',
  'URL:https://www.bls.gov/schedule/news_release/empsit.htm',
  'END:VEVENT'
 ].join('\r\n')]);
 const rows=parseBlsCalendar(input,now);
 assert.equal(rows.length,1);
 assert.equal(rows[0].kind,'JOBS');
 assert.equal(rows[0].title,'Employment Situation - November 2026');
 assert.equal(rows[0].uid,'jobs-2026');
 assert.equal(rows[0].scheduledAt,'2026-12-04T13:30:00.000Z');
});

test('BLS LIVE feed TZID=US-Eastern is recognized across winter and summer DST',()=>{
 assert.equal(icalToUtc('20261110T083000','US-Eastern'),'2026-11-10T13:30:00.000Z');
 assert.equal(icalToUtc('20260714T083000','US-Eastern'),'2026-07-14T12:30:00.000Z');
 assert.equal(icalToUtc('20261110T083000','US/Eastern'),'2026-11-10T13:30:00.000Z');
 const actualFormat=ics([[
   'BEGIN:VEVENT',
   'UID:f65741ec-4080-474c-b2e3-1349fe430963',
   'DTSTART;TZID=US-Eastern:20261110T083000',
   'SUMMARY:Consumer Price Index - October 2026',
   'END:VEVENT'
 ].join('\r\n')]);
 const x=parseBlsCalendar(actualFormat,now);
 assert.equal(x.length,1);
 assert.equal(x[0].kind,'CPI');
 assert.equal(x[0].scheduledAt,'2026-11-10T13:30:00.000Z');
});
