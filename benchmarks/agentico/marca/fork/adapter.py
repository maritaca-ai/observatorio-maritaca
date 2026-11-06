"""MARCA public: adapter for the pinned upstream implementation."""
BENCHMARK = 'marca'
TASKS = ['marca_public']
FAMILY = 'public'

def run(argv=None):
    from s5_nano.run_all import main
    return main(["--benchmarks", BENCHMARK, *(argv or [])])


if __name__ == "__main__":
    import sys
    raise SystemExit(run(sys.argv[1:]))
