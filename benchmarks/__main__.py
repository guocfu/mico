import argparse
import sys
from pathlib import Path

from .runner import load_tasks, print_summary, run_benchmark, write_markdown_summary, write_results


def main():
    parser = argparse.ArgumentParser(description="Run deterministic mico benchmark cases.")
    parser.add_argument("--group", default=None, help="Run only benchmark tasks in this group.")
    args = parser.parse_args()

    tasks = load_tasks()
    if args.group:
        tasks = [task for task in tasks if task.get("group", "harness_regression") == args.group]
    result = run_benchmark(tasks)
    print_summary(result)

    results_dir = Path(__file__).resolve().parent.parent / "benchmarks" / "results"
    json_path = results_dir / "latest.json"
    markdown_path = results_dir / "latest.md"
    write_results(result, json_path)
    write_markdown_summary(result, markdown_path)
    print(f"\nResults written to {json_path}")
    print(f"Summary written to {markdown_path}")

    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()
