"""Deterministic planning, pure mapping and actual FFmpeg synthetic audio coverage."""
import copy
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import wave
from unittest.mock import patch
from python.audio_features import silence
from python.editing import cuts as c
from python.media import normalization as n
from python.transcription import engine as e


def fixture():
    project = dict(project_id='a'*32, source={'sha256':'b'*64}, outputs={'audio.wav':'c'*64})
    raw = dict(segments=[dict(start=0, end=1, text='word', words=[dict(start=0, end=1)])], content_checksum='d'*64)
    key = c.identity(project, raw, 10, 10, c.SETTINGS, 'test-ffmpeg')
    return key, raw


class CutTests(unittest.TestCase):
    def test_topology_ids_and_input_invalidation(self):
        key, raw = fixture()
        detected = [dict(start=2, end=4), dict(start=6, end=8)]
        first = c.generate(key, raw, detected)
        self.assertEqual(first, c.generate(key, raw, detected))
        self.assertEqual(first['removed'], [dict(start=2.2,end=3.8),dict(start=6.2,end=7.8)])
        self.assertEqual(first['keep'], [dict(start=0,end=2.2),dict(start=3.8,end=6.2),dict(start=7.8,end=10)])
        self.assertEqual(c.validate(first, key, raw), first)
        for field in ('source_checksum','audio_checksum','transcript_checksum','timing_checksum'):
            changed = copy.deepcopy(key); changed['source'][field] = 'e'*64
            self.assertNotEqual(first['candidates'][0]['cut_id'], c.generate(changed,raw,detected)['candidates'][0]['cut_id'])
        changed = copy.deepcopy(key); changed['settings']['threshold_db'] = -45
        self.assertNotEqual(first['candidates'][0]['cut_id'], c.generate(changed,raw,detected)['candidates'][0]['cut_id'])
        changed = c.generate(key,raw,[dict(start=2.1,end=4)])
        self.assertNotEqual(first['candidates'][0]['cut_id'],changed['candidates'][0]['cut_id'])

    def test_word_protection_segment_fallback_empty_and_boundaries(self):
        key, raw = fixture()
        raw['segments'] = [dict(start=1,end=5,text='speech',words=[dict(start=2,end=3)])]
        result = c.generate(key,raw,[dict(start=0,end=6)])
        for interval in result['removed']:
            self.assertTrue(interval['end'] <= 1.8 or interval['start'] >= 3.2)
        raw['segments'][0]['words'] = []
        result = c.generate(key,raw,[dict(start=0,end=6)])
        for interval in result['removed']:
            self.assertTrue(interval['end'] <= .8 or interval['start'] >= 5.2)
        raw['segments'] = []
        result = c.generate(key,raw,[dict(start=0,end=10)])
        self.assertTrue(result['warnings']); self.assertEqual(result['removed'],[dict(start=.2,end=9.8)])
        self.assertEqual(c.generate(key,raw,[dict(start=2,end=2.79)])['candidates'],[])
        self.assertEqual(len(c.generate(key,raw,[dict(start=2,end=2.8)])['candidates']),1)
        key['settings']['padding'] = .26
        self.assertEqual(c.generate(key,raw,[dict(start=2,end=2.8)])['candidates'],[])

    def test_explicit_audio_offset_moves_proposals_and_protection_together(self):
        key, raw = fixture(); key['audio_offset'] = .5; key['source_duration'] = 10.5
        value = c.generate(key, raw, [dict(start=2,end=4)])
        self.assertEqual(value['removed'], [dict(start=2.7,end=4.3)])
        self.assertEqual(value['candidates'][0]['silence_start'],2)
        self.assertEqual(c.protections(raw,10.5,.2,.5),[dict(start=.3,end=1.7)])
        c.validate(value,key,raw)

    def test_parser_eof_and_invalid_results(self):
        self.assertEqual(silence.parse('silence_start: 1\nsilence_end: 2 | silence_duration: 1\nsilence_start: 3',4),
                         [dict(start=1,end=2),dict(start=3,end=4)])
        self.assertEqual(silence.parse('no silence',4),[])
        for text in ('silence_start: NaN','silence_start: -1','silence_start: 5','silence_end: 2',
                     'silence_start: 2\nsilence_end: 1','silence_start: 1\nsilence_start: 2', 'silence_start: nonsense'):
            with self.assertRaises(ValueError): silence.parse(text,4)

    def test_corrupt_topology_and_settings_rejected(self):
        key, raw = fixture(); value = c.generate(key,raw,[dict(start=2,end=4)])
        for field, replacement in [('keep',[]),('removed',[]),('candidates',[]),('source_duration',-1),('schema_version',True),('removed',[dict(start=True,end=3.8)])]:
            bad = {**value,field:replacement}; bad['content_checksum'] = e.content_checksum(bad)
            with self.assertRaises(ValueError): c.validate(bad,key,raw)
        for setting in ({**c.SETTINGS,'padding':-1},{**c.SETTINGS,'threshold_db':float('nan')},{**c.SETTINGS,'min_cut':True}):
            with self.assertRaises(ValueError): c.settings_value(setting)
        for intervals in ([dict(start=2,end=1)],[dict(start=1,end=3),dict(start=2,end=4)],[dict(start=0,end=11)]):
            with self.assertRaises(ValueError): c.mapping(10,intervals)

    def test_mapping_identity_multiple_cuts_and_splice_convention(self):
        for t in (0,1,5,10):
            self.assertEqual(c.original_to_edited(10,[],t),dict(removed=False,edited_time=t))
            self.assertEqual(c.edited_to_original(10,[],t),dict(original_time=t))
        removed=[dict(start=2,end=4),dict(start=6,end=8)]
        self.assertEqual(c.mapping(10,removed)['effective_duration'],6)
        for t, expected in ((2,2),(3,2),(6,4),(7.9,4)):
            self.assertEqual(c.original_to_edited(10,removed,t),dict(removed=True,splice_time=expected))
        self.assertEqual(c.edited_to_original(10,removed,2),dict(original_time=4))
        self.assertEqual(c.edited_to_original(10,removed,4),dict(original_time=8))
        for t in (0,1,4,5,8,9,10):
            mapped=c.original_to_edited(10,removed,t)
            self.assertEqual(c.edited_to_original(10,removed,mapped['edited_time'])['original_time'],t)
        for t in (-1,float('nan'),11,True):
            with self.assertRaises(ValueError): c.original_to_edited(10,removed,t)
        with self.assertRaises(ValueError): c.edited_to_original(10,removed,7)
        edges=[dict(start=0,end=2),dict(start=4,end=6),dict(start=6,end=8),dict(start=9,end=10)]
        self.assertEqual(c.edited_to_original(10,edges,0),dict(original_time=2))
        self.assertEqual(c.edited_to_original(10,edges,2),dict(original_time=8))
        self.assertEqual(c.edited_to_original(10,edges,3),dict(original_time=10))
        self.assertEqual(c.mapping(10,[dict(start=0,end=10)])['mapping'],[])
        self.assertEqual(c.edited_to_original(10,[dict(start=0,end=10)],0),dict(original_time=10))

    def test_alignment_checks(self):
        data=dict(format={'duration':'10','start_time':'0'},streams=[dict(codec_type='video',start_time='0'),dict(codec_type='audio',codec_name='aac',sample_rate='48000',start_time='0')])
        project={'source':{'filename':'source.mp4'}}
        with patch.object(silence,'probe',return_value=data):
            self.assertEqual(silence.timeline(Path('/private/tmp'),project,10),(10,0))
            with self.assertRaises(n.MediaError): silence.timeline(Path('/private/tmp'),project,8)
        shifted=copy.deepcopy(data); shifted['streams'][1]['start_time']='0.5'
        proxy=copy.deepcopy(data); proxy['streams'][1]['start_time']=str(.5-1024/48000)
        with patch.object(silence,'probe',side_effect=[proxy,shifted]):
            self.assertEqual(silence.timeline(Path('/private/tmp'),project,9.5),(10,.5))
        bad=copy.deepcopy(data); bad['streams'][1]['start_time']='.5'
        with patch.object(silence,'probe',side_effect=[data,bad]):
            with self.assertRaises(n.MediaError): silence.timeline(Path('/private/tmp'),project,10)
        bad['streams'][1].pop('start_time')
        with patch.object(silence,'probe',return_value=bad):
            with self.assertRaises(n.MediaError): silence.timeline(Path('/private/tmp'),project,10)

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_real_ffmpeg_synthetic_pcm_threshold_and_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); audio=root/'audio.wav'
            # One second audible tone, two silence, one tone, then trailing silence.
            samples=[int(5000*math.sin(2*math.pi*440*i/16000)) if i<16000 or 48000<=i<64000 else 0 for i in range(80000)]
            with wave.open(str(audio),'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'))
                stream.writeframes(struct.pack('<'+'h'*len(samples),*samples))
            before=audio.read_bytes()
            result=silence.detect(audio,5,c.SETTINGS,root)
            self.assertEqual(len(result),2)
            self.assertAlmostEqual(result[0]['start'],1,places=3); self.assertAlmostEqual(result[0]['end'],3,places=3)
            self.assertAlmostEqual(result[1]['start'],4,places=3); self.assertEqual(result[1]['end'],5)
            self.assertEqual(before,audio.read_bytes())
