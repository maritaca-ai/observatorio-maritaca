"""ENEM-VL · text: adapter for the pinned upstream implementation."""
BENCHMARK = 'enem_vl'
TASKS = ['enem_vl']
FAMILY = 'exams'

def run(argv=None):
    from s5_nano.run_all import main
    return main(["--benchmarks", BENCHMARK, *(argv or [])])


if __name__ == "__main__":
    import sys
    raise SystemExit(run(sys.argv[1:]))
