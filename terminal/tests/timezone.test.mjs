import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Script} from 'node:vm';

const source=readFileSync(new URL('../worker.js',import.meta.url),'utf8');
const raw=source.match(/\nconst HTML=("(?:\\.|[^"\\])*");\s*$/s);
assert.ok(raw,'Worker HTML JSON payload exists');
const html=JSON.parse(raw[1]);
const code=html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert.ok(code,'Inline script exists');
const formatter=html.match(/^function formatStamp\(t\)\{[\s\S]*?^\}/m)?.[0];
assert.ok(formatter,'Timezone-aware time formatter exists');

function makeFormatter(zone){
 return new Function('state',formatter+'\nreturn formatStamp')({zone});
}

test('Vietnam display is exact UTC+7 for Fed/BLS news releases',()=>{
 const f=makeFormatter('VN');
 assert.equal(f('2026-11-10T13:30:00.000Z'),'10/11/2026 20:30:00 ICT');
 assert.equal(f('2026-12-04T13:30:00.000Z'),'04/12/2026 20:30:00 ICT');
});
test('UTC selection converts same instant without shifting internal timestamp',()=>{
 const f=makeFormatter('UTC');
 assert.equal(f('2026-11-10T13:30:00.000Z'),'10/11/2026 13:30:00 UTC');
});
test('Vietnam time crosses a day and year boundary correctly',()=>{
 const f=makeFormatter('VN');
 assert.equal(f('2026-12-31T20:15:02Z'),'01/01/2027 03:15:02 ICT');
});
test('nullable or invalid API timestamps render as unavailable',()=>{
 const f=makeFormatter('VN');
 assert.equal(f(null),'—');
 assert.equal(f(''),'—');
 assert.equal(f('not a date'),'—');
});
test('timezone dropdown and clock are functional and script parses',()=>{
 assert.doesNotThrow(()=>new Script(code));
 for(const part of [
  'id="timezoneSelect"','value="VN"','value="UTC"','function selectTimezone(zone)',
  "localStorage.getItem('atlas.display_time_zone')",
  "localStorage.setItem('atlas.display_time_zone',state.zone)",
  "$('timezoneSelect').onchange=()=>selectTimezone($('timezoneSelect').value)",
  'setInterval(renderClock,1000)',
  "function formatStamp(t)"
 ])assert.ok(html.includes(part),'Missing UI element or behavior: '+part);
});
test('all terminal tabs use shared formatter and calendar follows selected timezone',()=>{
 for(const part of ['id="marketTab"','id="signalsTab"','id="trackingTab"','id="macroTab"','id="researchTab"','id="analyticsTab"'])
  assert.ok(html.includes(part),part);
 assert.ok(html.includes("return esc(formatStamp(e.scheduled_at));"),'Calendar should not use browser local timezone directly');
 assert.ok(!html.includes("function utc(t)"),'UTC-only formatter should no longer exist');
 assert.ok(!html.includes("new Date().toISOString().replace('T'"),'Clock should not always show UTC');
 assert.ok(!html.includes('Sent at UTC'),'Hard-coded UTC publication heading');
 assert.ok(!html.includes('Last scanner run (UTC)'),'Hard-coded scanner label');
});
