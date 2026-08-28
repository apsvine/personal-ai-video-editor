// Dependency-free DOM integration harness. Mock HTTP persists across component remounts.
// Video time is controlled to test event wiring independently of codecs or user media.
import { createRoot } from 'react-dom/client';
import TranscriptReview from '../src/TranscriptReview';
import type { Review } from '../src/transcript';
import '../src/style.css';

const fixture: Review = {schema_version:1,project_id:'fixture',source_transcript_checksum:'a'.repeat(64),
  language:'en',timing_quality:'model_estimated_word_alignment',override_state:'none',override_message:null,
  segments:[{segment_id:'0',start:1,end:3,text:'Hello world',raw_text:'Hello world',edited:false,
    words:[{text:'Hello',start:1,end:1.5,confidence:.9},{text:' world',start:2,end:3,confidence:.4}]},
    {segment_id:'1',start:4,end:5,text:'No word timing',raw_text:'No word timing',edited:false,words:[]}]};
let saved = structuredClone(fixture);
window.fetch = async (_input, init) => {
  const url = String(_input);
  if (url.includes('/cuts')) return new Response(JSON.stringify({error:{message:'No cut plan in Phase 05 fixture.'}}),{status:404});
  if (init?.method) {
    const data = JSON.parse(String(init.body));
    if (url.endsWith('/overrides/reset')) saved = structuredClone(fixture);
    else {
      const id = url.match(/overrides\/(\d+)/)?.[1];
      const segment = saved.segments.find(s => s.segment_id === id)!;
      segment.text = init.method === 'PUT' ? data.text : segment.raw_text;
      segment.edited = segment.text !== segment.raw_text;
    }
    saved.override_state = saved.segments.some(s => s.edited) ? 'applied' : 'none';
  }
  return new Response(JSON.stringify(saved), {status:200, headers:{'Content-Type':'application/json'}});
};
const host = document.querySelector('#root')!;
let root = createRoot(host);
let revision = 0;
function mount() { root.render(<TranscriptReview projectId="fixture" revision={String(revision++)} busy={false}/>); }
const results: string[] = [];
function assert(value: unknown, label: string) { if (!value) throw new Error(label); results.push('PASS '+label); }
async function wait(check: () => unknown) {
  const deadline = Date.now()+3000;
  while (!check()) { if (Date.now()>deadline) throw new Error('Timed out waiting for UI'); await new Promise(r=>setTimeout(r,10)); }
}
function button(label: string) { return [...host.querySelectorAll('button')].find(b=>b.textContent === label)!; }
async function click(label: string) { button(label).click(); await new Promise(r=>setTimeout(r,20)); }
async function edit(text: string) {
  await click('Edit');
  const input = host.querySelector('textarea')!;
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,text);
  input.dispatchEvent(new Event('input',{bubbles:true}));
  await new Promise(r=>setTimeout(r,20));
  await click('Save');
  await wait(()=>!host.querySelector('textarea'));
}
try {
  mount(); await wait(()=>host.textContent?.includes('Hello'));
  assert(host.querySelectorAll('.segment').length===2,'transcript renders');
  const video = host.querySelector('video')!;
  Object.defineProperty(video,'duration',{value:10,configurable:true});
  Object.defineProperty(video,'currentTime',{value:0,writable:true,configurable:true});
  (host.querySelector('.segment-time') as HTMLButtonElement).click();
  assert(video.currentTime===1,'segment click seeks video');
  (host.querySelectorAll('.word')[1] as HTMLButtonElement).click();
  assert(video.currentTime===2,'word click seeks its original timestamp');
  video.currentTime=4.5; video.dispatchEvent(new Event('timeupdate',{bubbles:true}));
  await wait(()=>host.querySelectorAll('.segment')[1].getAttribute('aria-current')==='true');
  assert(true,'playback changes active segment');
  (host.querySelector('.segment-text') as HTMLButtonElement).click();
  assert(video.currentTime===4,'wordless segment falls back to segment seeking');
  await edit('Corrected text');
  assert(host.textContent?.includes('Corrected text') && host.textContent.includes('Edited'),'save displays corrected text');
  assert(host.textContent?.includes('Original ASR text'),'original remains accessible');
  root.unmount(); root=createRoot(host); mount();
  await wait(()=>host.textContent?.includes('Corrected text'));
  assert(true,'fresh component load restores persisted correction');
  await click('Reset Segment');
  assert(!host.textContent?.includes('Corrected text'),'segment reset restores original');
  await edit('Another correction'); await click('Reset All Corrections');
  assert(!host.textContent?.includes('Another correction'),'reset all restores original');
  saved.override_state='stale'; saved.override_message='The source transcript changed. Reset all corrections.';
  await click('Reload transcript'); await wait(()=>host.textContent?.includes('source transcript changed'));
  assert(button('Edit').disabled && !button('Reset All Corrections').disabled,'stale state blocks edits but permits reset');
  await click('Reset All Corrections');
  assert(!host.textContent?.includes('source transcript changed'),'reset clears stale state');
  document.querySelector('#results')!.textContent=results.join('\n')+'\nALL PASSED';
} catch (error) {
  document.querySelector('#results')!.textContent=results.join('\n')+'\nFAIL '+String(error);
}
