"""Opt-in acceptance server: wait in a cancellable subprocess before normalization."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'apps/api'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delay', type=int, default=20, choices=range(1, 121), metavar='1..120')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    from python.media import normalization as n
    import uvicorn
    from app.main import app
    original = n.normalize

    def delayed(root, project):
        n.checkpoint(0.02)
        log = n.safe_path(n.project_path(root, project['project_id']), 'logs', 'media.log')
        n.run_tool([sys.executable, '-c', f'import time; time.sleep({args.delay})'], log)
        return original(root, project)

    n.normalize = delayed
    print(f'Acceptance-only delay: {args.delay}s per normalization attempt.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
