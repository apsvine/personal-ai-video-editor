// Isolated DOM/event tests. No user media or runtime writes.
import { createRoot } from 'react-dom/client';
import TranscriptReview from '../src/TranscriptReview';
import type { CaptionPlan } from '../src/captions';
import '../src/style.css';

const plan: CaptionPlan = {schema_version:1,project_id:'fixture',content_checksum:'c',
  removed:[{start:1,end:3}],items:[
    {caption_id:'first',original_start:0,original_end:1,edited_start:0,edited_end:1,text:'HELLO'},
    {caption_id:'second',original_start:3,original_end:4,edited_start:1,edited_end:2,text:'WORLD'}],
  warnings:[{type:'ambiguous_text_timing',segment_id:'2',word_index:null,caption_id:null,
    message:'Effective text could not be mapped safely to authoritative word timing. Segment omitted.'}]};
const review = {schema_version:1,project_id:'fixture',source_transcript_checksum:'a'.repeat(64),
  language:'en',timing_quality:'model_estimated_word_alignment',override_state:'none',override_message:null,
  segments:[{segment_id:'0',start:0,end:1,text:'HELLO',raw_text:'hello',edited:true,words:[{text:'hello',start:0,end:1,confidence:.9}]},
    {segment_id:'1',start:3,end:4,text:'WORLD',raw_text:'world',edited:true,words:[{text:'world',start:3,end:4,confidence:.9}]}]};
let stale=false;
let captionReads=0;
window.fetch=async(input, init)=>{
  const url=String(input);
  if(url.endsWith('/captions')) {
    captionReads++;
    return new Response(JSON.stringify(stale?{error:{message:'No current caption plan. Generate captions.'}}:plan),{status:stale?404:200});
  }
  if(url.includes('/cuts')) {
    if(init?.method) stale=true;
    return new Response(JSON.stringify({schema_version:1,project_id:'fixture',source_cuts_checksum:'b'.repeat(64),
      override_state:'none',override_message:null,warnings:[],candidates:[{cut_id:'d'.repeat(64),start:1,end:3,reason:'silence',decision:'accept'}],
      effective:{source_duration:5,effective_duration:3,time_removed:2}}));
  }
  if(init?.method) {
    stale=true;
    review.segments[0].text=JSON.parse(String(init.body)).text ?? 'hello';
  }
  return new Response(JSON.stringify(review));
};
const host=document.querySelector('#root')!;
let root=createRoot(host);
const results:string[]=[];
function assert(value:unknown,label:string) {if(!value)throw new Error(label); results.push('PASS '+label);}
async function wait(check:()=>unknown) {
  const deadline=Date.now()+4000;
  while(!check()) {if(Date.now()>deadline)throw new Error('UI timeout'); await new Promise(r=>setTimeout(r,10));}
}
const settle=()=>new Promise(r=>setTimeout(r,40));
function button(label:string) {return [...host.querySelectorAll('button')].find(b=>b.textContent===label)!;}
function mount(revision='1') {root.render(<TranscriptReview projectId="fixture" revision={revision} busy={false}/>);}
function clock(time:number, event='timeupdate') {
  const video=host.querySelector('video')!;
  Object.defineProperty(video,'currentTime',{value:time,writable:true,configurable:true});
  video.dispatchEvent(new Event(event,{bubbles:true}));
}
try {
  mount(); await wait(()=>host.querySelector('.caption-overlay')?.textContent==='HELLO');
  assert(true,'initial plan loaded using original time zero');
  assert(host.textContent?.includes('Segment omitted'),'ambiguous correction warning visible');
  clock(3.5); await wait(()=>host.querySelector('.caption-overlay')?.textContent==='WORLD');
  assert(true,'timeupdate follows original proxy time, not edited time');
  clock(1.5,'seeking'); await settle();
  assert(!host.querySelector('.caption-overlay'),'seeking immediately hides inside accepted removed span');
  clock(3.2,'seeked'); await wait(()=>host.querySelector('.caption-overlay')?.textContent==='WORLD');
  assert(true,'seeked immediately restores appropriate caption');
  clock(4); await settle(); assert(!host.querySelector('.caption-overlay'),'caption disappears at half-open end');
  clock(4.8); await settle(); assert(!host.querySelector('.caption-overlay'),'caption disappears outside all intervals');
  (host.querySelectorAll('.segment-time')[1] as HTMLButtonElement).click();
  await wait(()=>host.querySelector('.caption-overlay')?.textContent==='WORLD');
  assert(host.querySelector('video')!.currentTime===3,'existing segment seek updates overlay');
  root.unmount(); root=createRoot(host); mount();
  await wait(()=>host.querySelector('.caption-overlay')?.textContent==='HELLO');
  assert(captionReads>1,'remount restores persisted plan and preview');
  button('Reject').click();
  await wait(()=>host.textContent?.includes('No current caption plan'));
  assert(!host.querySelector('.caption-overlay'),'cut decision change invalidates visible snapshot');
  stale=false; button('Reload captions').click();
  await wait(()=>host.querySelector('.caption-overlay')?.textContent==='HELLO');
  button('Edit').click(); await wait(()=>host.querySelector('textarea'));
  const input=host.querySelector('textarea')!;
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'ambiguous new text');
  input.dispatchEvent(new Event('input',{bubbles:true})); await settle(); button('Save').click();
  await wait(()=>host.textContent?.includes('No current caption plan'));
  assert(!host.querySelector('.caption-overlay'),'correction invalidates visible snapshot without raw fallback');
  stale=false; mount('new-job:succeeded');
  await wait(()=>host.querySelector('.caption-overlay')?.textContent==='HELLO');
  assert(true,'job revision reloads generated plan');
  document.querySelector('#results')!.textContent=results.join('\n')+'\nALL PASSED';
} catch(error) {document.querySelector('#results')!.textContent=results.join('\n')+'\nFAIL '+String(error);}
