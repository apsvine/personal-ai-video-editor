import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { CandidateRow } from '../.test-build/src/CutReview.js';
import { decisionLabel } from '../.test-build/src/cuts.js';
for (const [decision,label] of [['pending','pending'],['accept','accepted'],['reject','rejected']]) {
  test(`candidate ${label} has clear state, original boundaries and actions`,()=>{
    assert.equal(decisionLabel(decision),label);
    const html=renderToStaticMarkup(createElement(CandidateRow,{candidate:{cut_id:'a',start:1,end:2.5,reason:'silence',decision},blocked:false,change:()=>{},seek:()=>{}}));
    assert.match(html,/1.000–2.500s/); assert.match(html,/1.500s/); assert.match(html,/silence/);
    assert.match(html,new RegExp(`<strong>${label}</strong>`));
    for (const action of ['Accept','Reject','Reset decision','Seek start','Seek end']) assert.ok(html.includes(action));
    assert.equal(html.includes('disabled=""'),decision==='pending');
  });
}
test('busy or stale review disables all decision writes but preserves seeking',()=>{
  const html=renderToStaticMarkup(createElement(CandidateRow,{candidate:{cut_id:'a',start:1,end:2,reason:'silence',decision:'accept'},blocked:true,change:()=>{},seek:()=>{}}));
  assert.equal((html.match(/disabled/g)||[]).length,3);
  assert.match(html,/<button>Seek start<\/button>/);
});
