"""MMLU PT: adapter for the pinned upstream implementation."""
BENCHMARK = 'mmlu_pt'
TASKS = ['mmlu_pt_high_school', 'mmlu_pt_undergraduate']
FAMILY = 'lumi'

def run(argv=None):
    from s5_nano.run_all import main
    return main(["--benchmarks", BENCHMARK, *(argv or [])])


if __name__ == "__main__":
    import sys
    raise SystemExit(run(sys.argv[1:]))
