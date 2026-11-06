"""Route requests to independent native Transformers processes on one GPU.

Each request runs the unchanged single-request checkpoint generate path. This
avoids the Python thread bottleneck without padding, truncating, merging or
changing generation budgets. All child processes remain in the worker's process
group so a lane shutdown also terminates its replicas.
"""
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import queue
import subprocess
import sys
import time
import urllib.error
import urllib.request


def serve_replicas(args):
    args.audit_dir.mkdir(parents=True,exist_ok=True)
    prefill_lock=args.prefill_lock or args.audit_dir/'prefill.lock'
    available=queue.Queue()
    children=[]
    launch_id=str(time.time_ns())
    with ExitStack() as resources:
        try:
            for index in range(args.replicas):
                port=args.port+index+1
                argv=[sys.executable,'-m','s5_nano.hf_server','--model',args.model,
                      '--served-model-name',args.served_model_name,
                      '--chat-template',str(args.chat_template),
                      '--max-model-len',str(args.max_model_len),
                      '--audit-dir',str(args.audit_dir),'--replicas','1',
                      '--enable-thinking',str(args.enable_thinking).lower(),
                      '--prefill-lock',str(prefill_lock),'--port',str(port)]
                log=resources.enter_context((args.audit_dir/f'pool-{launch_id}-{index}.log').open('ab',buffering=0))
                process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,
                    stderr=subprocess.STDOUT,env=dict(os.environ,OMP_NUM_THREADS='1',
                    TOKENIZERS_PARALLELISM='false',S5_NANO_HF_POOL_SIZE=str(args.replicas)))
                children.append((port,process))
            receipt=dict(time=time.time(),pid=os.getpid(),replicas=args.replicas,
                         backend='transformers_native_process_pool',
                         prefill_serialized=True,prompt_padding=False,
                         children=[dict(port=port,pid=p.pid) for port,p in children])
            (args.audit_dir/f'pool-{launch_id}.json').write_text(json.dumps(receipt,indent=2)+'\n')
            pending=dict(children)
            deadline=time.monotonic()+1200
            while pending:
                for port,process in list(pending.items()):
                    if process.poll() is not None:
                        raise RuntimeError('Native serving replica exited during startup')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2):
                            available.put((port,process));del pending[port]
                    except OSError:
                        pass
                if pending:
                    if time.monotonic()>deadline:
                        raise TimeoutError('Native serving replicas did not become ready')
                    time.sleep(1)

            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*arguments):
                    pass

                def respond(self,status,payload):
                    raw=json.dumps(payload).encode()
                    self.send_response(status);self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

                def do_GET(self):
                    if any(p.poll() is not None for _,p in children):
                        self.respond(503,{'error':{'message':'A native serving replica exited'}})
                    elif self.path=='/health':
                        self.respond(200,{'status':'ready','backend':receipt['backend'],'replicas':args.replicas})
                    elif self.path=='/v1/models':
                        self.respond(200,dict(object='list',data=[dict(id=args.served_model_name,
                            object='model',created=0,owned_by='local',max_model_len=args.max_model_len)]))
                    else:
                        self.respond(404,{'error':{'message':'Unknown endpoint'}})

                def do_POST(self):
                    if self.path!='/v1/chat/completions':
                        self.respond(404,{'error':{'message':'Unknown endpoint'}});return
                    body=self.rfile.read(int(self.headers['Content-Length']))
                    port,process=available.get()
                    try:
                        if process.poll() is not None:
                            raise RuntimeError('Native serving replica exited')
                        request=urllib.request.Request(f'http://127.0.0.1:{port}{self.path}',data=body,
                            headers={'Content-Type':'application/json'})
                        try:
                            with urllib.request.urlopen(request,timeout=10800) as response:
                                status,payload=response.status,response.read()
                        except urllib.error.HTTPError as error:
                            status,payload=error.code,error.read()
                        self.send_response(status);self.send_header('Content-Type','application/json')
                        self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                    except Exception as error:
                        self.respond(503,{'error':{'message':str(error),'type':type(error).__name__}})
                    finally:
                        available.put((port,process))

            ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
        finally:
            for _,process in children:
                if process.poll() is None:
                    process.terminate()
            for _,process in children:
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()
