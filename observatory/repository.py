"""Read result files from a checkout or Git objects without a 16 GB worktree."""
import json
from pathlib import Path
import subprocess


class Repository:
    def __init__(self, root, from_git=False, worktree_overlay=False):
        self.root = Path(root)
        self.process = None
        self.worktree_overlay = worktree_overlay
        if worktree_overlay and not from_git:
            raise ValueError('Worktree overlay requires a Git fallback')
        if from_git:
            self.process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=self.root,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def bytes(self, path):
        path = str(path)
        if Path(path).is_absolute() or '..' in Path(path).parts or '\n' in path:
            raise ValueError('Invalid repository path')
        if self.process is None or (self.worktree_overlay and (self.root/path).is_file()):
            return (self.root/path).read_bytes()
        self.process.stdin.write(('HEAD:'+path+'\n').encode())
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode().split()
        if len(header) == 2 and header[-1] == 'missing':
            raise FileNotFoundError(path)
        if len(header) != 3 or header[1] != 'blob':
            raise ValueError('Missing Git blob: '+path)
        data = self.process.stdout.read(int(header[2]))
        if len(data) != int(header[2]) or self.process.stdout.read(1) != b'\n':
            raise ValueError('Incomplete Git blob: '+path)
        return data

    def json(self, path):
        data = self.bytes(path)
        try:
            import orjson
        except ImportError:
            return json.loads(data)
        return orjson.loads(data)

    def response_files(self, folder):
        """List the actual parts, independently of the summary's inventory."""
        if self.process is None or (self.worktree_overlay and any((self.root/folder).glob('respostas-*.json'))):
            return {p.name for p in (self.root/folder).glob('respostas-*.json')}
        names = subprocess.check_output(
            ['git', 'ls-tree', '--name-only', 'HEAD:'+str(folder)], cwd=self.root, text=True)
        return {name for name in names.splitlines()
                if name.startswith('respostas-') and name.endswith('.json')}

    def close(self):
        if self.process:
            self.process.stdin.close()
            self.process.stdout.close()
            self.process.wait(timeout=10)
