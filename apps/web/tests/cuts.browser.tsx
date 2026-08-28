// Actual React DOM controls with isolated mock HTTP persistence; never touches user projects.
import { createRoot } from 'react-dom/client';
import CutReview from '../src/CutReview';
import type { CutReviewData } from '../src/cuts';
import '../src/style.css';
const fixture: CutReviewData = {schema_version:1,project_id:'fixture',source_cuts_checksum:'a'.repeat(64),override_state:'none',override_message:null,warnings:[],
  candidates:[{cut_id:'b'.repeat(64),start:1,end:3,reason:'silence',decision:'pending'},{cut_id:'c'.repeat(64),start:5,end:6,reason:'silence',decision:'pending'}],
  effective:{source_duration:10,effective_duration:10,time_removed:0}};
let saved=structuredClone(fixture); let fail=false; let seeks:number[]=[];
window.fetch=async (input,init)=>{
  if (fail && init?.method) return new Response(JSON.stringify({error:{message:'Simulated storage failure'}}),{status:500});
  if (init?.method) {
    const url=String(input); const body=JSON.parse(String(init.body));
    if (body.source_cuts_checksum!==saved.source_cuts_checksum) throw new Error('Wrong identity');
    if (url.endsWith('/overrides/reset')) saved=structuredClone(fixture);
    else {
      const id=url.match(/overrides\/([a-f0-9]+)/)?.[1]; const candidate=saved.candidates.find(c=>c.cut_id===id)!;
      candidate.decision=init.method==='PUT'?body.action:'pending';
    }
    saved.override_state=saved.candidates.some(c=>c.decision!=='pending')?'applied':'none';
    saved.effective.time_removed=saved.candidates.reduce((sum,c)=>sum+(c.decision==='accept'?c.end-c.start:0),0);
    saved.effective.effective_duration=10-saved.effective.time_removed;
  }
  return new Response(JSON.stringify(saved),{status:200});
};
const host=document.querySelector('#root')!; let root=createRoot(host); let revision=0;
function mount(busy=false) { root.render(<CutReview projectId="fixture" revision={String(revision++)} busy={busy} seek={t=>seeks.push(t)}/>); }
const results:string[]=[];
function assert(value:unknown,label:string) { if(!value) throw new Error(label); results.push('PASS '+label); }
async function wait(check:()=>unknown) { const deadline=Date.now()+3000; while(!check()) {if(Date.now()>deadline) throw new Error('UI timeout'); await new Promise(r=>setTimeout(r,10));} }
function button(label:string,index=0) {return [...host.querySelectorAll('button')].filter(b=>b.textContent===label)[index];}
async function click(label:string,index=0) {button(label,index).click(); await new Promise(r=>setTimeout(r,30));}
try {
  mount(); await wait(()=>host.querySelectorAll('.cut-candidate').length===2);
  assert(host.textContent?.includes('effective: 10.000s'),'pending retains full duration');
  await click('Seek start'); await click('Seek end'); assert(seeks.join(',')==='1,3','boundary seeking stays on original timeline');
  await click('Accept'); assert(host.textContent?.includes('effective: 8.000s'),'accept shortens effective plan');
  root.unmount(); root=createRoot(host); mount(); await wait(()=>host.textContent?.includes('effective: 8.000s'));
  assert(true,'saved acceptance restores on remount');
  await click('Accept',1); assert(host.textContent?.includes('effective: 7.000s'),'multiple acceptances combine');
  await click('Reject'); await click('Reject',1); assert(host.textContent?.includes('effective: 10.000s'),'rejecting all retains full duration');
  await click('Reset decision'); assert(host.querySelector('strong')?.textContent==='pending','reset returns to pending');
  await click('Reset All Decisions'); assert(saved.candidates.every(c=>c.decision==='pending'),'reset all clears decisions');
  fail=true; await click('Accept'); assert(host.textContent?.includes('Simulated storage failure') && saved.effective.time_removed===0,'failed save does not claim acceptance'); fail=false;
  saved.override_state='stale'; saved.override_message='Plan changed. Reset decisions.';
  await click('Reload Smart Cuts'); await wait(()=>host.textContent?.includes('Plan changed'));
  assert(button('Accept').disabled && !button('Reset All Decisions').disabled,'stale decisions blocked with reset available');
  await click('Reset All Decisions'); assert(!host.textContent?.includes('Plan changed'),'reset clears stale warning');
  mount(true); await wait(()=>host.querySelectorAll('.cut-candidate').length===2 && button('Accept').disabled);
  assert(button('Reject').disabled,'busy disables writes');
  document.querySelector('#results')!.textContent=results.join('\n')+'\nALL PASSED';
} catch(error) {document.querySelector('#results')!.textContent=results.join('\n')+'\nFAIL '+String(error);}
