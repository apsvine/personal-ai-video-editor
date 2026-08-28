"""Cut API, persistence, immutability and job integration regressions."""
import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import test_transcript_review as review_tests
from python.audio_features import silence
from python.editing import cuts as c
from python.common.control import checkpoint
from python.media import normalization as n
from python.transcription import engine as e


class CutReviewTests(unittest.TestCase):
    def setUp(self):
        review_tests.TranscriptReviewTests.setUp(self)
        self.raw['segments'] = [dict(start=0,end=.3,text='hello',confidence=None,words=[dict(start=0,end=.3,text='hello',confidence=.9)]),
                                dict(start=1.7,end=2,text='world',confidence=None,words=[dict(start=1.7,end=2,text='world',confidence=.9)])]
        self.raw['content_checksum']=e.content_checksum(self.raw); n.atomic_json(self.raw_path,self.raw)
        self.enterContext(patch.object(silence,'timeline',return_value=(2,0)))
        self.enterContext(patch.object(silence,'version',return_value='test-ffmpeg'))
        self.detect=self.enterContext(patch.object(silence,'detect',return_value=[dict(start=.3,end=1.7)]))
        c.analyze(self.root,self.project)
        self.cuts_path=self.path/'analysis/cuts.json'; self.cuts=c.read_cuts(self.root,self.project)
        self.cid=self.cuts['candidates'][0]['cut_id']; self.cut_url=f'/projects/{self.pid}/cuts'
        self.cut_identity=dict(source_cuts_checksum=self.cuts['content_checksum'])
        self.decision_path=self.path/'overrides/user_cuts.json'

    def decide(self, action='accept', **extra):
        return self.client.put(self.cut_url+'/overrides/'+self.cid,headers=self.headers,json={**self.cut_identity,'action':action,**extra})

    def reset_cut(self, all=False):
        return self.client.post(self.cut_url+('/overrides/reset' if all else f'/overrides/{self.cid}/reset'),headers=self.headers,json=self.cut_identity)

    def test_pending_accept_reject_reset_and_immutable_inputs(self):
        # Include an actual Phase 05 override in the immutable snapshot.
        (self.path/'overrides').mkdir(exist_ok=True)
        n.atomic_json(self.path/'overrides/user_transcript.json',dict(schema_version=1,project_id=self.pid,
            source_transcript_checksum=self.raw['content_checksum'],segments={'0':{'text':''}}))
        files=[self.path/'source/test.mp4',self.raw_path,self.cuts_path,*list((self.path/'normalized').iterdir()),self.path/'overrides/user_transcript.json']
        before={p:p.read_bytes() for p in files}
        review=self.client.get(self.cut_url+'/review').json()
        self.assertEqual(review['effective']['effective_duration'],2); self.assertEqual(review['candidates'][0]['decision'],'pending')
        accepted=self.decide(); self.assertEqual(accepted.status_code,200)
        self.assertAlmostEqual(accepted.json()['effective']['effective_duration'],1)
        self.assertEqual(self.client.get(self.cut_url+'/review').json(),accepted.json())
        self.assertEqual(self.decide('reject').json()['effective']['effective_duration'],2)
        value=self.reset_cut().json(); self.assertEqual(value['candidates'][0]['decision'],'pending')
        self.assertEqual(value['effective']['effective_duration'],2); self.assertFalse(self.decision_path.exists())
        self.decide(); self.assertEqual(set(p.name for p in self.decision_path.parent.iterdir()),{'user_transcript.json','user_cuts.json'})
        self.assertEqual(set(json.loads(self.decision_path.read_text())),{'schema_version','project_id','source_cuts_checksum','decisions'})
        self.assertEqual(self.reset_cut(all=True).status_code,200); self.assertFalse(self.decision_path.exists())
        self.assertEqual(self.reset_cut(all=True).status_code,200)
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)

    def test_stale_and_invalid_overrides_never_applied(self):
        self.decide(); old=self.decision_path.read_bytes()
        c.analyze(self.root,self.project,settings={**c.SETTINGS,'threshold_db':-45})
        value=self.client.get(self.cut_url+'/review').json()
        self.assertEqual(value['override_state'],'stale'); self.assertEqual(value['effective']['time_removed'],0)
        self.assertEqual(self.decide().status_code,409); self.assertEqual(self.decision_path.read_bytes(),old)
        self.cut_identity['source_cuts_checksum']=value['source_cuts_checksum']
        self.assertEqual(self.reset_cut(all=True).status_code,200)
        for contents in ('null','[]','{bad',json.dumps({'schema_version':True})):
            self.decision_path.write_text(contents)
            value=self.client.get(self.cut_url+'/review').json()
            self.assertEqual(value['override_state'],'invalid'); self.assertEqual(value['effective']['time_removed'],0)
            self.assertEqual(self.reset_cut(all=True).status_code,200)

    def test_guards_validation_busy_and_paths(self):
        endpoint=self.cut_url+'/overrides/'+self.cid
        payload={**self.cut_identity,'action':'accept'}
        self.assertEqual(self.client.put(endpoint,json=payload).status_code,403)
        self.assertEqual(self.client.put(endpoint,json=payload,headers={**self.headers,'Origin':'https://foreign.test'}).status_code,403)
        for extra in ({'action':'delete'},{'start':0},{'source_cuts_checksum':False}):
            self.assertEqual(self.decide(**extra).status_code,422)
        self.assertEqual(self.decide(source_cuts_checksum='a'*64).status_code,409)
        self.assertEqual(self.client.put(self.cut_url+'/overrides/bad',json=payload,headers=self.headers).status_code,422)
        self.jobs.reserve()
        try: self.assertEqual(self.decide().status_code,409)
        finally: self.jobs.release()
        outside=Path(self.temp)/'outside'; outside.mkdir()
        (self.path/'overrides').symlink_to(outside,target_is_directory=True)
        self.assertEqual(self.decide().status_code,400); self.assertEqual(list(outside.iterdir()),[])

    def test_atomic_failure_prior_artifacts_preserved(self):
        self.decide(); before=self.decision_path.read_bytes(); generated=self.cuts_path.read_bytes()
        with patch.object(Path,'replace',side_effect=OSError('full')):
            self.assertEqual(self.decide('reject').status_code,500)
            with self.assertRaises(OSError): c.analyze(self.root,self.project,settings={**c.SETTINGS,'threshold_db':-45})
        self.assertEqual(self.decision_path.read_bytes(),before); self.assertEqual(self.cuts_path.read_bytes(),generated)
        self.assertEqual(list(self.path.rglob('*.tmp')),[])

    def test_cache_inputs_and_reused_project(self):
        before=self.cuts_path.read_bytes(); self.detect.reset_mock()
        self.assertTrue(c.analyze(self.root,self.project)['reused']); self.detect.assert_not_called()
        self.assertEqual(self.cuts_path.read_bytes(),before)
        with patch.object(n,'require_tools'): reused=n.create_project(self.root,'test.mp4',4)
        reused['source']['sha256']=self.project['source']['sha256']; reused['reused_project_id']=self.pid
        n.save_project(self.root/reused['project_id'],reused,'reused')
        self.cut_url=f'/projects/{reused["project_id"]}/cuts'
        self.assertEqual(self.decide().json()['project_id'],self.pid)
        self.assertFalse((self.root/reused['project_id']/'overrides').exists())
        self.raw['segments'][0]['text']='changed'; self.raw['content_checksum']=e.content_checksum(self.raw); n.atomic_json(self.raw_path,self.raw)
        self.assertEqual(self.client.get(self.cut_url).status_code,404)
        self.assertFalse(c.analyze(self.root,self.project)['reused'])
        self.assertEqual(self.client.get(self.cut_url+'/review').json()['override_state'],'stale')

    def test_missing_invalid_empty_transcript_and_no_audio(self):
        before=self.cuts_path.read_bytes()
        self.raw_path.write_text('{}')
        with self.assertRaises(n.MediaError): c.analyze(self.root,self.project)
        self.assertEqual(self.cuts_path.read_bytes(),before)
        self.raw_path.unlink()
        with self.assertRaises(n.MediaError): c.analyze(self.root,self.project)
        self.raw['segments']=[]; self.raw['content_checksum']=e.content_checksum(self.raw); n.atomic_json(self.raw_path,self.raw)
        c.analyze(self.root,self.project)
        value=self.client.get(self.cut_url+'/review').json()
        self.assertTrue(value['warnings']); self.assertEqual(value['effective']['time_removed'],0)
        project=copy.deepcopy(self.project); project['audio_status']='no_audio'; project['outputs'].pop('audio.wav')
        with self.assertRaises(n.MediaError) as context: c.analyze(self.root,project)
        self.assertEqual(context.exception.code,'no_audio')

    def test_analyze_job_cache_cancel_retry_and_failure(self):
        endpoint=f'/projects/{self.pid}/jobs'
        response=self.client.post(endpoint,headers=self.headers,json={'stage':'analyze'})
        self.assertEqual(response.status_code,202); self.jobs.thread.join(5)
        job=self.jobs.latest(self.pid); self.assertEqual(job['status'],'succeeded'); self.assertTrue(job['reused'])
        before=self.cuts_path.read_bytes()
        self.cuts_path.unlink()
        entered=threading.Event(); release=threading.Event()
        def wait_detect(*args):
            entered.set(); release.wait(5); checkpoint(.5); return [dict(start=.3,end=1.7)]
        with patch.object(silence,'detect',side_effect=wait_detect):
            response=self.client.post(endpoint,headers=self.headers,json={'stage':'analyze'}); job=response.json()
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.client.post(endpoint,headers=self.headers,json={'stage':'analyze'}).status_code,409)
            self.assertEqual(self.client.post(endpoint+'/'+job['job_id']+'/cancel',headers=self.headers).status_code,202)
            release.set(); self.jobs.thread.join(5)
        self.assertEqual(self.jobs.read(self.pid,job['job_id'])['status'],'cancelled'); self.assertFalse(self.cuts_path.exists())
        response=self.client.post(endpoint+'/'+job['job_id']+'/retry',headers=self.headers)
        self.assertEqual(response.status_code,202); self.jobs.thread.join(5)
        retried=self.jobs.read(self.pid,response.json()['job_id']); self.assertEqual(retried['stage'],'analyze')
        self.assertEqual(retried['retry_of'],job['job_id']); self.assertEqual(retried['status'],'succeeded')
        self.assertEqual(self.cuts_path.read_bytes(),before)
        for stage in ('plan','render'):
            self.assertEqual(self.client.post(endpoint,headers=self.headers,json={'stage':stage}).status_code,422)

    def test_interrupted_analysis_recovers_and_retries_same_stage(self):
        from python.common.jobs import JobManager
        entered=threading.Event(); release=threading.Event()
        def waiting(*args):
            entered.set(); release.wait(5); checkpoint(.5)
        with patch.object(silence,'version',return_value='changed-tool'),patch.object(silence,'detect',side_effect=waiting):
            job=self.jobs.start(self.pid,stage='analyze')
            self.assertTrue(entered.wait(5))
            self.jobs.active[1].shutdown.set(); release.set(); self.jobs.thread.join(5)
        interrupted=self.jobs.read(self.pid,job['job_id']); self.assertEqual(interrupted['status'],'interrupted')
        # A record left running after process death uses the same generic startup recovery.
        interrupted['status']='running'; self.jobs.save(interrupted)
        recovered=JobManager(self.root); recovered.recover()
        self.assertEqual(recovered.read(self.pid,job['job_id'])['status'],'interrupted')
        next_job=recovered.retry(self.pid,job['job_id']); recovered.thread.join(5)
        self.assertEqual(recovered.read(self.pid,next_job['job_id'])['status'],'succeeded')
        self.assertEqual(next_job['stage'],'analyze'); recovered.close()

    def test_detector_failure_preserves_previous_plan_and_decisions(self):
        self.decide(); before=self.cuts_path.read_bytes(); overrides=self.decision_path.read_bytes()
        with patch.object(silence,'version',return_value='changed-tool'),patch.object(silence,'detect',side_effect=n.MediaError('tool_failed','failure')):
            job=self.jobs.start(self.pid,stage='analyze'); self.jobs.thread.join(5)
        self.assertEqual(self.jobs.read(self.pid,job['job_id'])['status'],'failed')
        self.assertEqual(before,self.cuts_path.read_bytes()); self.assertEqual(overrides,self.decision_path.read_bytes())

    def test_malformed_decisions_and_cut_artifacts(self):
        self.decide(); valid=json.loads(self.decision_path.read_text())
        for update in ({'schema_version':True},{'project_id':'wrong'},{'extra':1},
                       {'decisions':{'a'*64:{'action':'accept'}}},{'decisions':{self.cid:{'action':'accept','start':0}}},
                       {'decisions':{self.cid:{'action':'pending'}}}):
            n.atomic_json(self.decision_path,{**valid,**update})
            value=self.client.get(self.cut_url+'/review').json()
            self.assertEqual(value['override_state'],'invalid'); self.assertEqual(value['effective']['time_removed'],0)
            self.assertEqual(self.decide().status_code,409)
        original=self.cuts_path.read_bytes()
        for contents in ('null','[]','{}','{broken'):
            self.cuts_path.write_text(contents)
            self.assertEqual(self.client.get(self.cut_url).status_code,404)
        self.cuts_path.write_bytes(original)
