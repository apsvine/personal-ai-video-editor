"""Run a persisted transcription job while the backend is stopped; never downloads models."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python.common.jobs import JobManager
from python.common.errors import MediaError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_id')
    args = parser.parse_args()
    jobs = JobManager(ROOT / 'runtime/projects')
    try:
        jobs.startup()
        job = jobs.start(args.project_id, stage='transcribe')
        try:
            jobs.thread.join()
        except KeyboardInterrupt:
            jobs.cancel(args.project_id, job['job_id'])
            jobs.thread.join()
        result = jobs.read(args.project_id, job['job_id'])
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'succeeded' else 1
    except BlockingIOError:
        print('Stop the backend before running this CLI.', file=sys.stderr)
        return 1
    except MediaError as error:
        print(json.dumps({'error': error.result()}), file=sys.stderr)
        return 1
    finally:
        jobs.close()


if __name__ == '__main__':
    sys.exit(main())
