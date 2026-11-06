"""MATH-PT · PT-BR MC: adapter for the pinned upstream implementation."""
BENCHMARK = 'math_pt'
TASKS = ['math_pt_br_mc']
FAMILY = 'pt'

def run(argv=None):
    from s5_nano.run_all import main
    return main(["--benchmarks", BENCHMARK, *(argv or [])])


if __name__ == "__main__":
    import sys
    raise SystemExit(run(sys.argv[1:]))
