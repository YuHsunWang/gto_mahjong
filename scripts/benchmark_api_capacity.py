"""Measure a running beta server using the real default EV request budget.

Run only against a server you operate. This is a finite smoke/load probe, not
a claim about sustained traffic capacity or host memory limits.
"""

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--concurrency', default='1,1,5,10')
    parser.add_argument('--in-process', action='store_true', help='exercise ASGI directly, without TCP/proxy')
    args = parser.parse_args()
    levels = [int(value) for value in args.concurrency.split(',')]
    if not levels or any(value < 1 or value > 20 for value in levels):
        parser.error('concurrency levels must be between 1 and 20')
    payload = {'hand': '123m123p123s11122233z'}
    # No sims/turns overrides: exercise the public endpoint's shipped defaults.
    report = {'request': payload, 'transport': 'ASGI' if args.in_process else 'HTTP', 'batches': []}
    if args.in_process:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from fastapi.testclient import TestClient
        from server.api import app
        transport = TestClient(app)
    else:
        transport = httpx.Client(base_url=args.url, timeout=75, trust_env=False)
    with transport as client:
        for level in levels:
            barrier = threading.Barrier(level)

            def rank():
                barrier.wait()
                start = time.perf_counter()
                response = client.post('/api/ev/rank', json=payload)
                return {'status': response.status_code, 'seconds': time.perf_counter() - start}

            health = []
            with ThreadPoolExecutor(level) as pool:
                jobs = [pool.submit(rank) for _ in range(level)]
                pending = set(jobs)
                while pending:
                    start = time.perf_counter()
                    response = client.get('/api/health')
                    health.append({'status': response.status_code, 'seconds': time.perf_counter() - start})
                    _, pending = wait(pending, timeout=0.1)
                requests = [job.result() for job in jobs]
            report['batches'].append({
                'concurrency': level,
                'requests': requests,
                'health_max_seconds': max(row['seconds'] for row in health),
                'health_all_ok': all(row['status'] == 200 for row in health),
                'median_seconds': statistics.median(row['seconds'] for row in requests),
            })
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
