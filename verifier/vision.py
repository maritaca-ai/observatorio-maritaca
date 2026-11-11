"""Execute the pinned visual scorers from a complete or sparse checkout."""
import ast
from functools import lru_cache
from pathlib import Path
import subprocess
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def source(relative):
    path = 'benchmarks/visao/'+relative
    try:
        return (ROOT/path).read_text()
    except FileNotFoundError:
        return subprocess.check_output(['git', 'show', 'HEAD:'+path], cwd=ROOT).decode()


@lru_cache
def upstream(benchmark):
    if benchmark not in ('realworldqa', 'ocrbench'):
        raise ValueError('Unknown visual benchmark')
    path = benchmark+'/upstream.py'
    tree = ast.parse(source(path))
    if benchmark == 'realworldqa':
        # The original function imports this helper. Load its original module
        # in memory so sparse checkouts need no extra files or dependencies.
        name = 'lmms_eval.tasks._task_utils.mcq_extract'
        helper = ModuleType(name)
        sys.modules[name] = helper
        helper_path = 'vendor/lmms_eval/tasks/_task_utils/mcq_extract.py'
        exec(compile(source(helper_path), helper_path, 'exec'), helper.__dict__)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'realworldqa_process_results')
        scope = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), scope)
        return scope[node.name]
    main = next(n for n in tree.body if isinstance(n, ast.If)
                and '__name__' in ast.unparse(n.test))
    node = next(n for n in main.body if isinstance(n, ast.For)
                and isinstance(n.body[0], ast.Assign)
                and ast.unparse(n.body[0].targets[0]) == 'data_type')
    return compile(ast.Module(body=[node], type_ignores=[]), path, 'exec')


def score(benchmark, native, final):
    if not isinstance(final, str):
        raise ValueError('Final answer must be text')
    if benchmark == 'realworldqa':
        return float(upstream(benchmark)(native, [final])['exact_match'])
    row = dict(native, predict=final)
    exec(upstream(benchmark), {'data': [row]})
    return float(row.get('result', 0))
