"""ASSIN 2 RTE: adapter for the pinned upstream implementation."""
BENCHMARK = 'assin_rte'
TASKS = ['assin_rte']
FAMILY = 'pt'

def run(argv=None):
    from s5_nano.run_all import main
    return main(["--benchmarks", BENCHMARK, *(argv or [])])


if __name__ == "__main__":
    import sys
    raise SystemExit(run(sys.argv[1:]))
