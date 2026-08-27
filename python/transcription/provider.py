"""Offline faster-whisper adapter. Importing this module loads no ML runtime."""
from pathlib import Path
from python.common.errors import MediaError

VERSION = '1.2.1'
SETTINGS = dict(device='cpu', compute_type='int8', cpu_threads=4, num_workers=1,
                beam_size=5, word_timestamps=True, vad_filter=False)


def require_model(path):
    path = Path(path)
    required = ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt')
    if not path.is_dir() or any(not (path / name).is_file() for name in required):
        raise MediaError('model_not_installed',
                         'Local base model is missing or incomplete. Complete the separately approved model setup.', 503)
    return path


def transcribe(audio, model_path, settings):
    require_model(model_path)
    try:
        from importlib.metadata import version
        if version('faster-whisper') != VERSION:
            raise ImportError('Unsupported faster-whisper version')
        from faster_whisper import WhisperModel
    except (ImportError, ModuleNotFoundError) as error:
        raise MediaError('provider_not_installed', 'Install faster-whisper==1.2.1 in the project environment.', 503) from error
    model = WhisperModel(str(model_path), device=settings['device'], compute_type=settings['compute_type'],
                         cpu_threads=settings['cpu_threads'], num_workers=settings['num_workers'],
                         local_files_only=True)
    segments, info = model.transcribe(str(audio), beam_size=settings['beam_size'],
                                     word_timestamps=True, vad_filter=settings['vad_filter'])
    return dict(language=info.language, timing_quality='model_estimated_word_alignment', segments=[
        dict(start=s.start, end=s.end, text=s.text, confidence=None, words=[
            dict(text=w.word, start=w.start, end=w.end, confidence=w.probability)
            for w in (s.words or [])]) for s in segments])
