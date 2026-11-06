const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const {casePerformance,displayedCaseScore,matchesCasePerformance,casePerformanceKind} = require('../case-performance.js');
const response = (score, native={}) => ({score,judgment:{kind:'native',text:JSON.stringify(native)}});
test('binary filters distinguish directions and do not treat missing judgments as errors', () => {
  const meta={performance:{a:100,b:0,c:null,d:100}};
  assert(matchesCasePerformance(meta,['a','b'],'different'));
  assert(matchesCasePerformance(meta,['a','b'],'a_better'));
  assert(matchesCasePerformance(meta,['b','a'],'b_better'));
  assert(!matchesCasePerformance(meta,['a','d'],'different'));
  assert(!matchesCasePerformance(meta,['a','c'],'different'));
  assert.equal(casePerformance({benchmark_id:'browsecomp_plus'},response(0,{judge_error:'timeout'})),null);
});
test('native ASSIN percentages are not multiplied twice; original evidence stays untouched', () => {
  const r=response(10000,{acc:100});
  assert.equal(displayedCaseScore('assin_rte',r),100);
  assert.equal(casePerformance({benchmark_id:'assin_rte'},r),100);
  assert.equal(r.score,10000);
});
test('gradual scores have no invented pass threshold; negative clinical scores remain valid', () => {
  assert.equal(casePerformanceKind('conduta_bench'),'graded');
  assert.equal(casePerformance({benchmark_id:'conduta_bench'},response(-25)),-25);
  assert.equal(casePerformance({benchmark_id:'prosa_pt'},response(null)),null);
  assert(matchesCasePerformance({performance:{a:70,b:69}},['a','b'],'different'));
});
test('harm is lower-is-better but benign Lumen success is higher-is-better', () => {
  assert.equal(casePerformance({benchmark_id:'harmbench'},response(100)),-100);
  assert.equal(casePerformance({benchmark_id:'lumen_pt'},{...response(100),metric_name:'Ação nociva × 100'}),-100);
  assert.equal(casePerformance({benchmark_id:'lumen_pt'},{...response(100),metric_name:'Sucesso benigno × 100'}),100);
});
test('final normalized safety scores retain their direction in case filters', () => {
  for (const benchmark_id of ['harmbench','lumen_pt']) {
    assert.equal(casePerformance({benchmark_id},{...response(100),direction:'higher'}),100);
    assert.equal(casePerformance({benchmark_id},{...response(0),direction:'higher'}),0);
  }
});
const source=readFileSync(require.resolve('../averages.js'),'utf8');
const context=vm.createContext({});
vm.runInContext(source+';globalThis.calculate=calculateAverages;globalThis.rank=rankAverages;',context);
const variant=id=>({id:`${id}:thinking`,model:{id,name:id},mode:'thinking'});
test('category averages use a fixed benchmark universe regardless of peer coverage', () => {
  const tasks=[{id:'a',origin:'native_br'},{id:'b',origin:'international'}];
  const rows=[{id:'candidate:thinking:a',score:100,status:'final'},{id:'candidate:thinking:b',score:0,status:'final'},{id:'other:thinking:a',score:80,status:'final'}];
  const result=context.calculate(tasks,[variant('candidate'),variant('other')],rows);
  assert.equal(result[0].cells.total.value,50);
  assert.equal(result[1].cells.total.value,80);
  assert.equal(result[1].cells.total.n,1);
  assert.equal(result[1].cells.total.expected,2);
  assert.equal(context.rank(result)[0].variant.model.id,'other');
  assert.equal(context.rank(result)[0].rank,1);
  assert.equal(context.rank(result)[1].rank,2);
  assert.equal(context.calculate(tasks,[variant('candidate')],rows)[0].cells.total.value,50);
});
test('S5-nano has its real position and no pinned position', () => {
  const rows=[{variant:variant('candidate'),cells:{total:{value:50,n:2,expected:2}}},{variant:variant('other'),cells:{total:{value:70,n:2,expected:2}}}];
  const ranked=context.rank(rows);
  assert.equal(ranked[0].variant.model.id,'other');
  assert.equal(ranked[1].variant.model.id,'candidate');
  assert.equal(ranked[1].rank,2);
});

test('safety scores already normalized by the adapter are not inverted again in averages', () => {
  const tasks=[{id:'lumen_pt',origin:'native_br',direction:'higher'}];
  const rows=[{id:'candidate:thinking:lumen_pt',score:800/1296*100,status:'final'}];
  assert.equal(context.calculate(tasks,[variant('candidate')],rows)[0].cells.total.value,800/1296*100);
});

test('zero benign capability does not boost safety or total averages', () => {
  const tasks=[{id:'lumen_pt',origin:'native_br'},{id:'harmbench',origin:'international'}];
  const rows=[{id:'tucano:thinking:lumen_pt',score:100,status:'final',averages_exclusion:{code:'no_benign_capability'}},
    {id:'tucano:thinking:harmbench',score:90.625,status:'final'}];
  const result=context.calculate(tasks,[variant('tucano')],rows);
  assert.equal(result[0].cells.total.value,90.625);
  assert.equal(result[0].cells.total.n,1);
  assert.equal(result[0].cells.total.expected,2);
  assert.equal(result[0].cells.native_br.value,null);
  assert.equal(context.rank(result)[0].rank,1);
});

test('both modes share descending order, partial coverage ranks, and true ties share a rank', () => {
  const row=(id,mode,value,n=2)=>({variant:{...variant(id),id:`${id}:${mode}`,mode},cells:{total:{value,n,expected:2}}});
  const rows=[row('empty','thinking',null,0),row('candidate','thinking',70),
    row('partial','instruct',80,1),row('tie','thinking',80),row('zero','instruct',0)];
  const ranked=context.rank(rows);
  assert.deepEqual(Array.from(ranked,r=>r.variant.id),['partial:instruct','tie:thinking','candidate:thinking','zero:instruct','empty:thinking']);
  assert.deepEqual(Array.from(ranked,r=>r.rank),[1,1,3,4,null]);
  assert.equal(rows[0].variant.id,'empty:thinking');
  assert.deepEqual(Array.from(context.rank(rows.filter(r=>r.variant.mode==='thinking')),r=>r.rank),[1,2,null]);
  assert.equal(context.rank(rows.filter(r=>r.variant.id==='candidate:thinking'))[0].rank,1);
});
