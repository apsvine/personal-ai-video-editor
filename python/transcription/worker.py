"""Private managed child; only writes an attempt's temporary result."""
import json
import os
import sys
import traceback
from pathlib import Path
from python.common.errors import MediaError
from python.transcription.provider import transcribe


def main():
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    request = json.loads(Path(sys.argv[1]).read_text())
    try:
        result = transcribe(request['audio'], request['model'], request['settings'])
    except Exception as error:
        traceback.print_exc()
        failure = error if isinstance(error, MediaError) else MediaError('transcription_failed', 'Transcription failed. See the local transcription log.')
        result = dict(error=failure.result())
    Path(request['output']).write_text(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
