import sys
from pathlib import Path

from .runner import load_tasks, print_summary, run_benchmark, write_results


def main():
    tasks = load_tasks()
    result = run_benchmark(tasks)
    print_summary(result)

    results_dir = Path(__file__).resolve().parent.parent / "benchmarks" / "results"
    out_path = results_dir / "latest.json"
    write_results(result, out_path)
    print(f"\nResults written to {out_path}")

    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()
