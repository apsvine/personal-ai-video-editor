import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { activeCaption } from '../.test-build/src/captions.js';
import { CaptionOverlay, CaptionStatus } from '../.test-build/src/CaptionPreview.js';

const item = {caption_id:'c', original_start:4, original_end:5, edited_start:2, edited_end:3, text:'Corrected <text>'};
const plan = {items:[item], removed:[{start:1,end:3}], warnings:[]};
test('caption activation uses proxy original time, never edited time', () => {
  assert.equal(activeCaption(plan,4.5),item);
  assert.equal(activeCaption(plan,2.5),null);
});
test('half-open intervals, gaps, negative and invalid clocks hide captions', () => {
  for (const time of [0,3,5,NaN,Infinity,-1]) assert.equal(activeCaption(plan,time),null);
  assert.equal(activeCaption(plan,4),item);
  assert.equal(activeCaption(null,4),null);
});
test('removed spans defensively hide even an overlapping preview item', () => {
  assert.equal(activeCaption({...plan, items:[{...item,original_start:0}]},2),null);
});
test('overlay renders escaped corrected text only when active', () => {
  assert.match(renderToStaticMarkup(createElement(CaptionOverlay,{plan,time:4.1})),/Corrected &lt;text&gt;/);
  assert.equal(renderToStaticMarkup(createElement(CaptionOverlay,{plan,time:5})), '');
});
test('omitted ambiguity warning is visible and readable', () => {
  const html=renderToStaticMarkup(createElement(CaptionStatus,{plan:{...plan,warnings:[
    {type:'ambiguous_text_timing',segment_id:'1',message:'Segment omitted: ambiguous corrected text.'}]},error:'',loading:false,reload:()=>{}}));
  assert.match(html,/role="alert"/); assert.match(html,/Segment 2/); assert.match(html,/ambiguous corrected text/);
});
