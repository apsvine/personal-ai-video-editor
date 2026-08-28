"""Read-only FFmpeg silence detection; no media output is produced."""
import json
import math
import re
import uuid
from python.media import normalization as n


def probe(path, log):
    return json.loads(n.run_tool(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
        '-show_entries', 'format=duration,start_time:stream=codec_type,codec_name,sample_rate,start_time,duration', '-of', 'json', str(path)], log))


def timeline(path, project, audio_duration):
    """Fail closed when normalized audio cannot be placed on the proxy time axis."""
    log = n.safe_path(path, 'logs', 'cuts-probe.log')
    try:
        proxy = probe(n.safe_path(path, 'normalized', 'proxy.mp4'), log)
        source = probe(n.safe_path(path, 'source', project['source']['filename']), log)
        def start(data, kind):
            value = float(next(s for s in data['streams'] if s['codec_type'] == kind)['start_time'])
            if not math.isfinite(value):
                raise ValueError('Nonfinite stream start')
            return value
        duration = float(proxy['format']['duration'])
        origin = float(source['format']['start_time'])
        offset = start(source, 'audio') - origin
        audio_stream = next(s for s in proxy['streams'] if s['codec_type'] == 'audio')
        if audio_stream['codec_name'] != 'aac':
            raise ValueError('Unexpected proxy codec')
        rate = int(audio_stream['sample_rate'])
        if rate <= 0:
            raise ValueError('Invalid proxy rate')
        # The immutable Phase 02 command re-encodes AAC, which may expose one
        # encoder-priming frame. The source's decoded start anchors WAV sample 0.
        proxy_audio = start(proxy, 'audio')
        plausible_starts = (offset, max(0, offset - 1024 / rate))
        if (not all(math.isfinite(v) for v in (duration, origin, offset))
                or duration <= 0 or not 0 <= offset < duration
                or abs(duration - (audio_duration + offset)) > .1
                or abs(start(source, 'video') - origin) > 1 / 30
                or abs(start(proxy, 'video')) > 1 / 30
                or min(abs(proxy_audio - v) for v in plausible_starts) > .002):
            raise ValueError('Uncertain audio/video alignment')
        return duration, offset
    except (ValueError, KeyError, TypeError, StopIteration) as error:
        raise n.MediaError('cuts_alignment_uncertain', 'Audio and video timing could not be safely matched. Smart Cuts is unavailable for this clip.', 409) from error


def version(log):
    return n.run_tool(['ffmpeg', '-version'], log).splitlines()[0]


def parse(text, duration):
    """Parse one attempt only, including open silence at EOF; reject malformed events."""
    intervals, pending, previous = [], None, 0.0
    for line in text.splitlines():
        if 'silence_start:' not in line and 'silence_end:' not in line:
            continue
        matches = re.findall(r'silence_(start|end):\s*([^\s|]+)', line)
        if not matches:
            raise ValueError('Malformed silence event')
        for kind, token in matches:
            value = float(token)
            if not math.isfinite(value) or value < 0 or value > duration + .0001:
                raise ValueError('Invalid silence time')
            value = min(value, duration)  # EOF text serialization tolerance only.
            if kind == 'start':
                if pending is not None or value < previous:
                    raise ValueError('Unordered silence start')
                pending = value
            else:
                if pending is None or value <= pending:
                    raise ValueError('Unpaired silence end')
                intervals.append({'start': pending, 'end': value})
                previous, pending = value, None
    if pending is not None and pending < duration:
        intervals.append({'start': pending, 'end': duration})
    return intervals


def detect(audio, duration, settings, log_dir):
    log = n.safe_path(log_dir, f'cuts-detect-{uuid.uuid4().hex}.log')
    n.run_tool(['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'info',
        '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'wav', '-i', str(audio),
        '-af', f"silencedetect=noise={settings['threshold_db']}dB:d={settings['min_silence']}", '-f', 'null', '-'], log)
    try:
        return parse(log.read_text(), duration)
    except ValueError as error:
        raise n.MediaError('invalid_silence_result', 'Silence analysis returned invalid timing. See the local cut log.', 422) from error
