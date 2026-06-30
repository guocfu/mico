from pathlib import Path

from .eval_runner import load_eval_tasks, result_to_dict, run_eval, write_eval_results


def main():
    tasks = load_eval_tasks()
    result = run_eval(tasks)
    results_dir = Path(__file__).resolve().parent / "results"
    json_path = results_dir / "eval-latest.json"
    markdown_path = results_dir / "eval-latest.md"
    write_eval_results(result, json_path, markdown_path)
    print(f"Eval results written to {json_path}")
    print(f"Eval summary written to {markdown_path}")
    return 0 if result_to_dict(result)["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
