from __future__ import annotations

import argparse
import importlib.util
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_agent() -> ModuleType:
    spec = importlib.util.spec_from_file_location("omawarden_benchmark", ROOT / "omawarden-agent.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load omawarden-agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark OmaWarden's in-memory vault index")
    parser.add_argument("--items", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=25)
    args = parser.parse_args()
    if args.items < 1 or args.iterations < 1:
        parser.error("--items and --iterations must be positive")

    agent = load_agent()
    items = [
        {
            "id": str(index),
            "name": f"Entry {index} GitHub" if index % 37 == 0 else f"Entry {index}",
            "favorite": index % 101 == 0,
            "type": 1,
            "login": {
                "username": f"user{index}@example.test",
                "password": "fixture-only",
                "totp": "fixture-only" if index % 5 == 0 else "",
                "uris": [{"uri": f"https://service{index % 500}.example.test/login"}],
            },
        }
        for index in range(args.items)
    ]

    tracemalloc.start()
    began = time.perf_counter()
    metadata = agent.project_item_metadata(items, True)
    search_index = agent.build_search_index(metadata)
    build_ms = (time.perf_counter() - began) * 1000
    peak_mib = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    tracemalloc.stop()

    queries = ("git", "service42", f"user{args.items - 1}", "entry example")
    print(f"items={args.items} build_ms={build_ms:.2f} peak_mib={peak_mib:.2f}")
    for query in queries:
        samples = []
        for _ in range(args.iterations):
            began = time.perf_counter()
            agent.search_index(search_index, query, 20)
            samples.append((time.perf_counter() - began) * 1000)
        print(
            f"query={query!r} p50_ms={statistics.median(samples):.3f} "
            f"p95_ms={percentile(samples, 0.95):.3f}"
        )

    recent_ids = [str(args.items - 1), "100", "5"]
    samples = []
    for _ in range(args.iterations):
        began = time.perf_counter()
        agent.browse_index(search_index, recent_ids, 20)
        samples.append((time.perf_counter() - began) * 1000)
    print(f"browse_p50_ms={statistics.median(samples):.3f} browse_p95_ms={percentile(samples, 0.95):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
