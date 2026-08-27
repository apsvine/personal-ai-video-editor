import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { activeSegment, seekVideo, timedWords } from '../.test-build/src/transcript.js';
import { SegmentText } from '../.test-build/src/TranscriptReview.js';

const segment = { segment_id: '0', start: 1, end: 3, text: 'Hello world', raw_text: 'Hello world', edited: false,
  words: [{text:'Hello',start:1,end:1.5,confidence:.9},{text:' world',start:2,end:3,confidence:.3}] };

test('active segment follows playback, gaps, adjacent boundaries and ending', () => {
  const segments = [segment, {...segment, segment_id:'1',start:3,end:4}];
  for (const [time, id] of [[0,null],[1,'0'],[2.9,'0'],[3,'1'],[4,null],[NaN,null]]) {
    assert.equal(activeSegment(segments, time), id);
  }
});
test('seek uses exact segment/word start, clamps duration and rejects invalid values', () => {
  const video = {currentTime:0,duration:10};
  seekVideo(video, segment.start); assert.equal(video.currentTime, 1);
  seekVideo(video, segment.words[1].start); assert.equal(video.currentTime, 2);
  seekVideo(video, 20); assert.equal(video.currentTime, 10);
  seekVideo(video, -1); seekVideo(video, NaN); assert.equal(video.currentTime, 10);
  seekVideo(null, 1);
});
test('word validation never invents timing', () => {
  assert.deepEqual(timedWords(segment), segment.words);
  for (const words of [undefined, [], [{text:'bad',start:NaN,end:1}], [{text:'bad',start:2,end:1}], [{text:'bad',start:0,end:1}]]) {
    assert.deepEqual(timedWords({...segment, words}), []);
  }
});
test('raw text renders timed words and subtle low probability tooltip', () => {
  const html = renderToStaticMarkup(createElement(SegmentText,{segment,seek:()=>{}}));
  assert.match(html, /Hello/); assert.match(html, /Seek to 2.00s/); assert.match(html,/Low ASR probability/);
  assert.doesNotMatch(html, /Original ASR text/);
});
test('edited text remains separate from original word alignment and HTML is escaped', () => {
  const html = renderToStaticMarkup(createElement(SegmentText,{segment:{...segment,edited:true,text:'<b>Corrected</b>'},seek:()=>{}}));
  assert.match(html, /&lt;b&gt;Corrected&lt;\/b&gt;/);
  assert.match(html,/Original ASR text and timed words/);
  assert.match(html,/Seek to 2.00s/);
});
test('missing word timing renders segment-seek text', () => {
  const html = renderToStaticMarkup(createElement(SegmentText,{segment:{...segment,words:[]},seek:()=>{}}));
  assert.match(html,/Hello world/); assert.match(html,/segment-text/); assert.doesNotMatch(html,/class="word"/);
});
