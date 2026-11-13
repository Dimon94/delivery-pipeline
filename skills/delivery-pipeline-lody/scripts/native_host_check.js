/** 外部 Lody 边界替身；宿主到 Python 的 stdin/stdout 使用真实子进程。 */
const {spawn} = require('node:child_process');
const {runNativeReplacement} = require(process.argv[2] || './native_host.js');
const assert = require('node:assert/strict');
async function check(wrap, fixture) {
  let child;
  let pending = [];
  let waiter;
  const deliver = value => { if (waiter) { const resolve=waiter; waiter=null; resolve(value); } else pending.push(value); };
  const read = () => pending.length ? Promise.resolve(pending.shift()) : new Promise(resolve => {waiter=resolve;});
  const io = {
    exec: async () => {
      child=spawn('python3',[__dirname+'/native_replacement.py'],{stdio:['pipe','pipe','pipe']});
      child.stdout.on('data', data => deliver({output:data.toString(),session_id:1}));
      child.stderr.on('data', data => deliver({output:data.toString()}));
      child.on('exit', () => deliver({output:''}));
      return {session_id:1};
    },
    write: async ({chars}) => { if(chars) child.stdin.write(chars); return read(); }
  };
  const seen=[];
  const native = {
    lody_session_create_options: async args => {seen.push(['options',args]);return wrap({current:{sessionId:'caller',workspaceId:'workspace',machineId:'machine'}});},
    lody_operation_get: async args => {seen.push(['get',args]);return wrap({id:'adopted',kind:'session_create',state:'active',items:[]});}
  };
  if (fixture) {
    native.lody_session_create_options=async () => wrap(fixture.options);
    native.lody_operation_get=async () => wrap({id:'original',state:'finished',completion:{type:'result',value:{items:[{status:'succeeded',target:{sessionId:'old'}}]}}});
    native.lody_session_status_many=async () => wrap({items:[{sessionId:'old',ok:true,value:{summary:{id:'old',machineId:'machine'},execution:{executionState:'idle',phase:'idle',queuedTurnCount:0},machine:{state:'online'},observation:{quality:'fresh'}}}]});
    native.lody_session_create=async args => {
      seen.push(['create',args]);
      assert.equal(args.workContext.branch,'frozen-source');
      const {execFileSync}=require('node:child_process');
      const dest=fixture.binding.sourceRepo+'/host-child';
      execFileSync('git',['-C',fixture.binding.sourceRepo,'worktree','add','-qb','host-native',dest,args.workContext.branch]);
      assert.equal(execFileSync('git',['-C',dest,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),fixture.base);
      return wrap({id:'host-adopted',kind:'session_create',state:'active',items:[]});
    };
  }
  try {
    if (fixture) {
      const claimed=await runNativeReplacement('python3',fixture.invocation,io,native);
      assert.equal(claimed.result.replacement_intent.status,'accepted');
      assert.equal(claimed.result.model,'B');
      assert.equal(claimed.result.effort,'high');
      assert.equal(seen.filter(x=>x[0]==='create').length,0);
      // 每次 JSON-lines 请求使用独立 Python 进程，先排空前次退出事件。
      if (child.exitCode === null) await new Promise(resolve=>child.once('exit',resolve));
      pending=[];
      const value=await runNativeReplacement('python3',{
        action:'execute',registry:fixture.invocation.registry,lane:claimed.result.lane_id,
        prompt:'host nonce',binding:fixture.binding
      },io,native);
      assert.equal(value.result.replacement_intent.receipt.gap,undefined,'host create must preserve frozen base: '+JSON.stringify(value.result.replacement_intent.receipt));
      assert.equal(value.result.replacement_intent.receipt.native.id,'host-adopted');
      assert.equal(seen.filter(x=>x[0]==='create').length,1);
      return;
    }
    const value=await runNativeReplacement('python3', {action:'inspect',binding:{sessionId:'caller',workspaceId:'workspace',machineId:'machine'},operationId:'adopted'},io,native);
    assert.equal(value.result.operation.id,'adopted');
    assert.deepEqual(seen,[['options',{}],['get',{operationId:'adopted'}]]);
    assert.equal(value.transcript.length,2);
  } finally {child?.kill();}
}
(async()=>{
  if (process.argv[3]) await check(x=>({content:[{type:'text',text:JSON.stringify(x)}]}),JSON.parse(require('node:fs').readFileSync(process.argv[3],'utf8')));
  await check(x=>x);
  await check(x=>({content:[{type:'text',text:JSON.stringify(x)}]}));
  console.log('Lody host → real Python → official-tool boundary: pass (native Unknown)');
})().catch(error=>{console.error(error);process.exitCode=1;});
