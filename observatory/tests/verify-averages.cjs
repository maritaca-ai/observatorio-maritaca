// Check the real UI arithmetic against the independently recorded Git verifier.
const {readFileSync}=require('node:fs');
const {resolve}=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const root=resolve(__dirname,'../..');
const read=p=>JSON.parse(readFileSync(p,'utf8'));
const data=read(process.argv[2]);
const catalog=read(resolve(root,'observatory/catalog.json'));
const reference=read(resolve(root,'verifier/reported.json'));
const context=vm.createContext({document:{addEventListener(){}}});
for(const name of ['model-controls.js','averages.js'])
  vm.runInContext(readFileSync(resolve(root,'observatory',name),'utf8'),context);
for(const [selection,expected] of Object.entries(reference.medias)) {
  const [category,size,mode]=selection.split('/');
  const variants=data.models.filter(m=>context.inSizeGroup(m,size))
    .flatMap(model=>model.modes.filter(m=>mode==='both'||m===mode)
      .map(mode=>({id:`${model.id}:${mode}`,model,mode})));
  const tasks=data.benchmarks.filter(b=>category==='all'||b.categories.includes(category));
  const actual=context.rankAverages(context.calculateAverages(tasks,variants,data.records));
  assert.equal(actual.length,expected.length,selection);
  actual.forEach((row,i)=>{
    const want=expected[i];
    assert.deepEqual([catalog.model_directories[row.variant.model.id],row.variant.mode,row.rank],
                     [want.modelo,want.modo,want.ranking],selection);
    for(const [group,cell] of Object.entries(row.cells)) {
      const target=want.medias[group];
      assert(cell.value===null&&target.valor===null||Math.abs(cell.value-target.valor)<1e-8,selection);
      assert.deepEqual([cell.n,cell.expected],[target.n,target.total],selection);
      assert.deepEqual(Array.from(cell.entries,e=>catalog.benchmark_directories[e.task.id]).sort(),
                       [...target.benchmarks].sort(),selection);
    }
  });
}
console.log(JSON.stringify({average_filters:Object.keys(reference.medias).length,passed:true}));
