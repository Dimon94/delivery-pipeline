/** 当前 T3 宿主调用方。native 是官方工具绑定，processIO 是终端 I/O。
 * 不解析模型规则、不另存 receipt。遇 async next 只完成本地落盘并交还宿主。
 */
async function runNativeReplacement(command, invocation, processIO, native) {
  const started = await processIO.exec({cmd: command, tty: true, yield_time_ms: 1000, max_output_tokens: 4000});
  if (!started.session_id) throw new Error('Adapter process did not start');
  let output = await processIO.write({session_id: started.session_id, chars: JSON.stringify(invocation)+'\n', yield_time_ms: 1000, max_output_tokens: 8000});
  const transcript = [];
  while (true) {
    const lines = output.output.split(/\r?\n/).filter(Boolean);
    const message = lines.map(line => {try {return JSON.parse(line);} catch {return null;}}).find(value => value && (value.tool || value.result));
    if (!message) throw new Error('Adapter protocol failed: '+output.output);
    if (message.result) return {result: message.result, transcript};
    if (!['task_status','t3_thread_read','t3_worktree_status','task_cancel','delegate_task','orchestrator_capabilities'].includes(message.tool)) throw new Error('Unsupported native tool');
    let reply;
    try {
      const raw = await native[message.tool](message.arguments);
      if (raw.isError) throw new Error(JSON.stringify(raw.content));
      reply = {result: raw.structuredContent || JSON.parse(raw.content.find(x=>x.type==='text').text)};
    } catch (error) { reply = {error: String(error)}; }
    transcript.push({request: message, reply});
    output = await processIO.write({session_id: started.session_id, chars: JSON.stringify(reply)+'\n', yield_time_ms: 1000, max_output_tokens: 12000});
  }
}

// Pi bash 每次运行一个独立命令。用一对临时管道复用原 JSON lines 协议。
async function runWorkDispatchWithBash(command, invocation, bash, native) {
  const quote = value => "'" + value.replace(/'/g, "'\"'\"'") + "'";
  async function shell(command) {
    const result = await bash({command, timeout: 20});
    if (result.exit_code !== 0) throw new Error(result.output);
    return result.output;
  }
  const dir = (await shell('mktemp -d')).trim();
  const enter = 'cd ' + quote(dir) + ' && ';
  try {
    const processIO = {
      async exec({cmd}) {
        await shell(enter + 'mkfifo input output && { ' +
          '(exec 3<>input 4<>output && exec ' + cmd + ' <&3 >&4 2>error) </dev/null >/dev/null 2>&1 & ' +
          'printf "%s\n" "$!" > pid; }');
        return {session_id: dir};
      },
      async write({chars}) {
        const output = await shell(enter + 'exec 3<>input 4<>output && printf %s ' + quote(chars) +
          ' >&3 && { IFS= read -r -t 12 reply <&4 && printf "%s\n" "$reply"; }');
        return {output};
      },
    };
    return await runNativeReplacement(command.map(quote).join(' '), invocation, processIO, native);
  } finally {
    await shell(enter + '{ if [ -f pid ]; then kill "$(<pid)" 2>/dev/null || true; fi; } && ' +
      'rm -f input output pid error && cd / && rmdir ' + quote(dir));
  }
}

if (typeof module !== 'undefined') {
  module.exports = {runNativeReplacement, runReviewDispatch: runNativeReplacement,
                    runWorkDispatch: runNativeReplacement, runWorkDispatchWithBash};
}
