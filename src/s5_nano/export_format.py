"""Readable final-record format shared by every native benchmark adapter."""
import ast,collections,gzip,hashlib,json
from pathlib import Path
from . import auditing as _pricing
from .prepare import REPO
LLM_JUDGES={'harmbench', 'oab_bench_full', 'arena_hard_v2', 'lumen_pt', 'marca_public', 'magis_bench', 'bluex_v2', 'browsecomp_plus', 'conduta_bench', 'prosa_pt'}
PARAMS=('temperature', 'top_p', 'top_k', 'min_p', 'presence_penalty', 'frequency_penalty', 'repetition_penalty', 'max_tokens', 'max_completion_tokens', 'max_output_tokens', 'stop', 'seed', 'n', 'chat_template_kwargs', 'reasoning_effort', 'reasoning', 'response_format', 'text', 'tool_choice', 'parallel_tool_calls', 'verbosity')
CULTURAL_PROMPT=next(ast.literal_eval(n.value) for n in ast.parse((REPO/'benchmarks/brasil_especifico/culturalbench/fork/benchmarks/extract_answer_culture.py').read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prompt_extract' for t in n.targets))
def read(p):
    with gzip.open(p,'rt') if str(p).endswith('.gz') else open(p) as f:return json.load(f)
def lines(p):
    with gzip.open(p,'rt') if str(p).endswith('.gz') else open(p) as f:
        for l in f:
            if l.strip():yield json.loads(l)
def sig(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def field(obj,name):return obj.get(name)
def parsed(s):
    if isinstance(s,str):
        try:return json.loads(s)
        except ValueError:return s
    return s
def output_text(raw):
    if not isinstance(raw,dict):return None
    if raw.get('choices'):return raw['choices'][0].get('message',{}).get('content')
    if raw.get('output') is not None:
        return ''.join(c.get('text','') for m in raw['output'] for c in m.get('content',[]) if c.get('type')=='output_text')
    return raw.get('output_text')
def parameters(req):
    if not isinstance(req,dict):return None
    p={k:req[k] for k in PARAMS if k in req}
    if isinstance(req.get('extra_body'),dict):p.update(parameters(req['extra_body']) or {})
    return p
def clean(v):
    """Remove execution bookkeeping, retaining native verdicts and criteria."""
    if isinstance(v,list):return [clean(x) for x in v]
    if not isinstance(v,dict):return v
    out={}
    for k,x in v.items():
        if any(s in k.lower() for s in ('sha256','fingerprint','operator','executed_by','runner_name')):continue
        if k in {'provenance','source','source_id','result_id','manifest','manifest_path','path','api_base',
                 'uid','id','key','record_id','answer_id','ans_id','conversation_hash','request_id','model_id',
                 'time','tstamp','created_at','completed_at','created','billing','user','access_programs',
                 'raw_response','raw','model_identity_validations'}:continue
        if k in {'model','model_name'}:continue
        out[k]=clean(x)
    return out
def usage_total(u):
    if not isinstance(u,dict):return None
    if isinstance(u.get('total_tokens'),int):return u['total_tokens']
    a=u.get('input_tokens',u.get('prompt_tokens'));b=u.get('output_tokens',u.get('completion_tokens'))
    return a+b if type(a) is int and type(b) is int else None
def sum_usage(us):
    if not us or any(usage_total(u) is None for u in us):return None
    if len(us)==1:return us[0]
    return {'prompt_tokens':sum(u.get('prompt_tokens',u.get('input_tokens',0)) for u in us),
            'completion_tokens':sum(u.get('completion_tokens',u.get('output_tokens',0)) for u in us),
            'total_tokens':sum(usage_total(u) for u in us)}
def no_cost(reason='nao_registrado'):
    return {'valor':None,'moeda':None,'origem':reason}
def cost(c):
    if not isinstance(c,dict):return no_cost()
    if c.get('status')=='reused_saved_response_no_new_charge' and isinstance(c.get('original_cost'),dict):c=c['original_cost']
    currency=c.get('currency')
    key='brl' if currency=='BRL' or c.get('brl') is not None else 'usd'
    amount=c.get(key)
    if amount is None:return no_cost(c.get('status','nao_registrado'))
    out={'valor':amount,'moeda':key.upper(),'origem':c.get('status','registro_da_execucao')}
    for a,b in [('tariff_date','data_tarifa'),('tariff_source','fonte_tarifa'),('input_per_million','entrada_por_milhao'),
                ('cached_input_per_million','entrada_cache_por_milhao'),('output_per_million','saida_por_milhao')]:
        if a in c:out[b]=c[a]
    return out
def sum_cost(cs):
    if not cs:return no_cost()
    if len(cs)==1:return cs[0]
    if any(c['valor'] is None for c in cs):return no_cost('custo_de_uma_ou_mais_chamadas_nao_registrado')
    if len({c['moeda'] for c in cs})!=1:return {'valor':None,'moeda':None,'parcelas':cs,'origem':'moedas_distintas'}
    return {'valor':sum(c['valor'] for c in cs),'moeda':cs[0]['moeda'],'origem':'soma_dos_julgamentos_selecionados'}

class Native:
    def __init__(self,directory,model,mode,task):
        HERE=Path(directory)
        self.gen=collections.defaultdict(list);self.judge=collections.defaultdict(list);self.raw=collections.defaultdict(list)
        for p in (HERE/'native').glob(f'{model}--{mode}--{task}*.jsonl.gz'):
            for r in lines(p):
                key=r['case_id'];kind=r['kind']
                (self.gen if kind=='generation' else self.judge if kind=='judgment' else self.raw)[key].append(r)
        for p in (HERE/'tool-meta').glob(f'{model}--{mode}--{task}*.jsonl.gz'):
            for r in lines(p):
                saved=self.gen.get(r['case_id']);turns=r.get('turns') or []
                if not saved or not turns:continue
                first=saved[0]
                for k in ('parameters','messages','tools'):first[k]=turns[0].get(k)
                first['parameter_source']='effective_request'
                first['wire_turns']=turns
                if len(turns)==1 and not first.get('reasoning'):first['reasoning']=turns[0].get('reasoning')
        self.http=[];self.by_text=collections.defaultdict(list);self.by_id={};self.by_checks=collections.defaultdict(list);self.by_parsed=collections.defaultdict(list)
        for p in (HERE/'judges').glob(f'{model}--{mode}--{task}*.jsonl.gz'):
            for h in lines(p):
                raw=h.get('response') or {};t=output_text(raw)
                if not isinstance(raw,dict) or not isinstance(t,str):continue
                i=len(self.http);self.http.append(h)
                if raw.get('id'):self.by_id[raw['id']]=i
                self.by_text[sig(t)].append(i)
                j=parsed(t)
                if isinstance(j,(dict,list)):self.by_parsed[sig(j)].append(i)
                if isinstance(j,dict) and isinstance(j.get('criteria_checks'),list):
                    self.by_checks[self.check_key(j['criteria_checks'])].append(i)
    @staticmethod
    def check_key(cs):return sig(sorted([(str(c.get('criterion','')).strip(),c.get('is_met'),c.get('justification','')) for c in cs]))
    def generation(self,qid,final):
        rs=sorted(self.gen.get(str(qid),[]),key=lambda r:r.get('turn',0))
        if not rs:return []
        last=rs[-1]
        if last.get('final') is not None and last['final']!=final:
            # A stale generation must never be attached to a final case.
            valid=[r for r in rs if r.get('final')==final]
            if len(valid)!=1:return []
            return valid
        return rs
    def judgments(self,qid,native_j,expected_model=None):
        ids=[];raws=[]
        def walk(v):
            if isinstance(v,list):
                for x in v:walk(x)
            elif isinstance(v,dict):
                if isinstance(v.get('raw'),dict):raws.append(v['raw'])
                for k in ['result','judgment','games']:
                    if k in v:walk(v[k])
                for k in ['answer','judgment','original_judgment']:
                    t=v.get(k)
                    if isinstance(t,str):ids.extend(self.by_text.get(sig(t),[]))
        walk(native_j)
        if isinstance(native_j,(dict,list)):ids.extend(self.by_parsed.get(sig(native_j),[]))
        if isinstance(native_j,dict) and isinstance(native_j.get('parsed'),dict):ids.extend(self.by_parsed.get(sig(native_j['parsed']),[]))
        for r in self.judge.get(str(qid),[])+self.raw.get(str(qid),[]):
            v=r['record'];result=v.get('result',v)
            consistent=False
            if isinstance(native_j,dict):
                if native_j.get('original_judgment'):
                    consistent=output_text(v.get('raw'))==native_j['original_judgment']
                elif native_j.get('criteria_checks'):
                    consistent=result.get('criteria_checks')==native_j['criteria_checks']
                elif isinstance(result.get('raw'),dict):
                    consistent=parsed(output_text(result['raw']))==native_j
                elif native_j.get('judgment') is not None:
                    consistent=result.get('judgment')==native_j['judgment']
                elif native_j.get('parsed') is not None:
                    consistent=result.get('parsed')==native_j['parsed']
            if consistent:walk(v)
        for r in raws:
            if r.get('id') in self.by_id:ids.append(self.by_id[r['id']])
            elif output_text(r):ids.extend(self.by_text.get(sig(output_text(r)),[]))
        if isinstance(native_j,dict) and native_j.get('criteria_checks'):
            ids.extend(self.by_checks.get(self.check_key(native_j['criteria_checks']),[]))
        # Multiple byte-identical logs of a cached verdict represent one selected call.
        selected={}
        for i in ids:
            h=self.http[i]
            if expected_model:
                actual=(h.get('request') or {}).get('model','')
                stem=expected_model.split('/')[-1]
                if stem not in actual and actual not in expected_model:continue
            k=sig([h.get('request'),output_text(h.get('response'))])
            selected.setdefault(k,h)
        return list(selected.values()),raws

def calls_from_http(http):
    out=[]
    for h in http:
        req=h['request'] or {};raw=h['response'] or {};u=h.get('usage') or raw.get('usage')
        call={'modelo':req.get('model') or raw.get('model'),'parametros':parameters(req),
              'total_tokens':usage_total(u),'tokens':clean(u),'custo':cost(h.get('cost')),
              'resposta':output_text(raw)}
        if req.get('messages') is not None:call['mensagens']=req['messages']
        else:
            if 'instructions' in req:call['system']=req['instructions']
            if 'input' in req:call['entrada']=req['input']
        out.append(call)
    return out

def fallback_calls(raws,native_rows,model):
    out=[];seen=set()
    for r in raws:
        key=sig(r)
        if key in seen:continue
        seen.add(key)
        served=r.get('model') or model;u=r.get('usage')
        estimates=(_pricing.openrouter_token_cost(served,u),_pricing.maritaca_token_cost(served,u),_pricing.token_cost(served,u,r.get('service_tier')))
        recorded=next((x for x in estimates if x.get('usd') is not None or x.get('brl') is not None),{})
        c=cost(recorded)
        if c['valor'] is not None and c['origem']!='provider_reported_usage_cost':c['origem']='estimativa_reconstruida_com_tarifa_registrada_na_campanha'
        request=None
        for native_row in native_rows:
            nr=native_row['record']
            if nr.get('raw',{}).get('id')==r.get('id') and nr.get('request'):request=nr['request'];break
            body=nr.get('identity',{}).get('details',{}).get('payload',{}).get('body')
            if body and nr.get('result',{}).get('raw',{}).get('id')==r.get('id'):request=body;break
        item={'modelo':served,'parametros':parameters(request or r),
            'total_tokens':usage_total(u),'tokens':clean(u),'custo':c,'resposta':output_text(r),
            'origem_parametros':'requisicao_registrada' if request else 'metadados_da_resposta_do_provedor'}
        if request and request.get('messages'):item['mensagens']=request['messages']
        out.append(item)
    for r in native_rows:
        j=r['record'];result=j.get('result') or {}
        if result.get('judge_usage') and not out:
            u=result['judge_usage'];c=cost({'usd':u.get('cost'),'status':'provider_reported_usage_cost'})
            if c['valor'] is None:
                candidates=(_pricing.openrouter_token_cost(model,u),_pricing.maritaca_token_cost(model,u),_pricing.token_cost(model,u))
                estimate=next((x for x in candidates if x.get('usd') is not None or x.get('brl') is not None),{})
                c=cost(estimate)
                if c['valor'] is not None:c['origem']='estimativa_reconstruida_com_tarifa_registrada_na_campanha'
            out.append({'modelo':model,'parametros':clean(j.get('identity',{}).get('details',{}).get('judge')),
                        'total_tokens':usage_total(u),'tokens':clean(u),'custo':c,'resposta':result.get('judgment')})
    return out

def chosen(task,j):
    if task=='arena_hard_v2':return j.get('category')=='hard_prompt'
    if task=='prosa_pt':return not j.get('excluded')
    if task=='sob':return j.get('modality')=='text'
    if task=='lumen_pt':return j.get('kind')=='harmful'
    return True

def format_case(case,response,native,record,number,include_control=False):
    task=case['benchmark_id'];qid=case['case_id'];j=parsed(response['judgment'].get('text'))
    if not include_control and not chosen(task,j):return None
    gens=native.generation(qid,response['final'])
    first=gens[0] if gens else {};last=gens[-1] if gens else {}
    profile=record.get('profile') or {}
    effective=first.get('parameter_source') in ('effective_request','recorded_request')
    pp=dict(first.get('parameters') or {}) if effective else dict(profile.get('sampling') or {})
    if not effective:
        if profile.get('max_tokens') is not None:pp['max_tokens']=profile['max_tokens']
        if 'enable_thinking' in profile:pp['chat_template_kwargs']={'enable_thinking':profile['enable_thinking']}
    for key in ['context_length','reasoning_parser','tool_parser']:
        if key in profile:pp[key]=profile[key]
    pp['origem']='requisicao_efetiva' if effective else 'perfil_registrado_da_execucao'
    messages=first.get('messages') or field(response,'input_messages')
    if isinstance(messages,dict) and 'value' in messages:messages=messages['value']
    system=None
    if isinstance(messages,list):system='\n\n'.join(str(m.get('content') or '') for m in messages if m.get('role')=='system')
    if task=='lumen_pt' and system is None:system=case.get('context')
    usage=sum_usage([g.get('usage') for g in gens])
    http,raws=native.judgments(qid,j,record.get('judge'))
    cultural_llm=task=='culturalbench' and (j.get('extraction') or {}).get('src')=='llm'
    if cultural_llm:
        text=response['final'].split('</think>',1)[-1]
        prompt=CULTURAL_PROMPT.format(text=text)
        matches=[h for h in native.http if (h.get('request') or {}).get('messages')==[{'role':'user','content':prompt}] and isinstance(parsed(output_text(h.get('response'))),dict) and parsed(output_text(h.get('response'))).get('answer')==j['extraction']['answer_extracted']]
        http=matches[:1]
    judgecalls=calls_from_http(http) or fallback_calls(raws,native.judge.get(str(qid),[])+native.raw.get(str(qid),[]),record.get('judge'))
    if task not in LLM_JUDGES:
        jc={'valor':0,'moeda':'USD','origem':'correcao_deterministica_sem_api'};jp=None
    elif task=='harmbench':
        jc={'valor':0,'moeda':'USD','origem':'classificador_local_sem_custo_de_api_gpu_excluida'};jp=None
    elif task=='lumen_pt' and isinstance(j,dict) and j.get('label')=='NOT_L2':
        jc={'valor':0,'moeda':'USD','origem':'regra_nativa_sem_chamada_ao_juiz'};jp=None
    else:
        jc=sum_cost([c['custo'] for c in judgecalls]);ps=[c['parametros'] for c in judgecalls]
        jp=ps[0] if ps and all(p==ps[0] for p in ps) else ps or None
        if jp is None and record.get('judge_effort'):
            jp={'reasoning_effort':record['judge_effort'],'origem':'configuracao_registrada_da_execucao'}
    verdict={'tipo':'modelo' if task in LLM_JUDGES else 'deterministico',
             'modelo':record.get('judge') or response['judgment'].get('judge'),'veredito':clean(j)}
    if task=='harmbench':verdict['tipo']='classificador_local'
    if task=='harmbench':
        verdict['modelo']='cais/HarmBench-Llama-2-13b-cls'
        jp={'temperature':0.0,'max_tokens':1,'origem':'protocolo_registrado'}
    if cultural_llm:
        verdict['tipo']='extracao_por_modelo_e_correcao_deterministica';verdict['modelo']='gpt-4o-mini-2024-07-18'
        jc=sum_cost([c['custo'] for c in judgecalls])
        jp=judgecalls[0]['parametros'] if judgecalls else {'temperature':0.0,'max_tokens':256,'origem':'protocolo_registrado'}
    if task=='lumen_pt' and isinstance(j,dict) and j.get('label')=='NOT_L2':verdict['tipo']='regra_deterministica';verdict['modelo']=None
    if isinstance(j,dict) and j.get('context_zero'):
        verdict['tipo']='regra_contexto';verdict['modelo']=None;jp=None
        jc={'valor':0,'moeda':'USD','origem':'zero_por_contexto_sem_chamada_ao_juiz'}
    if case.get('criteria'):verdict['criterios']=case['criteria']
    if case.get('reference') is not None:verdict['resposta_referencia']=case['reference']
    if response['judgment'].get('hits') is not None:verdict['criterios_atingidos']=response['judgment']['hits']
    if judgecalls:verdict['chamadas']=judgecalls
    score=response['score']
    if task in {'harmbench','lumen_pt'} and score is not None:score=100-score
    if record.get('averages_exclusion'):score=None
    if task=='assin_rte':score=100*int(j['f1'][0]==j['f1'][1])
    row={'id':f'{number:06d}','system':system,'pergunta':case['question'],'resposta':response['final'] or '',
         'parametros_inferencia':pp,'total_tokens':usage_total(usage),
         'custo':{'valor':0,'moeda':'USD','origem':'geracao_local_sem_custo_de_api_gpu_excluida'},
         'julgamento':verdict,'parametros_inferencia_julgamento':jp,'custo_julgamento':jc,'score':score}
    row['total_tokens_julgamento']=sum(c['total_tokens'] for c in judgecalls) if judgecalls and all(c['total_tokens'] is not None for c in judgecalls) else 0 if verdict['tipo'] in ('deterministico','regra_deterministica','regra_contexto') else None
    if case.get('context') and task!='lumen_pt':row['contexto']=case['context']
    if case.get('schema'):row['schema_esperado']=case['schema']
    if messages:row['mensagens_enviadas']=messages
    if first.get('tools'):row['ferramentas_disponiveis']=first['tools']
    if usage:row['tokens']=usage
    if last.get('reasoning'):row['reasoning']=last['reasoning']
    if last.get('finish_reason'):row['motivo_encerramento']=last['finish_reason']
    if last.get('error'):row['erro_geracao']=last['error']
    if last.get('context_exhausted'):row['contexto_insuficiente']=True
    if first.get('wire_turns'):
        row['inferencias_por_turno']=[{'turno':i+1,'parametros_inferencia':t.get('parameters'),
            'total_tokens':usage_total(t.get('usage')),'tokens':clean(t.get('usage')),
            'reasoning':t.get('reasoning'),'motivo_encerramento':t.get('finish_reason')} for i,t in enumerate(first['wire_turns'])]
        if len(first['wire_turns'])>1:row['parametros_inferencia']['escopo']='primeiro_turno; detalhes em inferencias_por_turno'
    if len(gens)>1:
        row['turnos']=[{'turno':i+1,'mensagens_enviadas':g.get('messages'),'resposta':g.get('final'),
            'reasoning':g.get('reasoning'),'parametros_inferencia':g.get('parameters'),
            'total_tokens':usage_total(g.get('usage')),'tokens':clean(g.get('usage')),'motivo_encerramento':g.get('finish_reason')} for i,g in enumerate(gens)]
    elif response.get('turns'):row['turnos']=clean(response['turns'])
    trace=field(response,'tool_trace')
    if isinstance(trace,dict) and 'value' in trace:trace=trace['value']
    if trace:row['conversa_com_ferramentas']=trace
    return row

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
