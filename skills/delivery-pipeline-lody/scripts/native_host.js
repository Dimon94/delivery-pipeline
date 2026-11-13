/** 原 Lody requester 宿主调用方。native 是官方工具绑定，processIO 是终端 I/O。
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
    if (!['lody_session_create_options','lody_session_status_many','lody_operation_get','lody_session_create'].includes(message.tool)) throw new Error('Unsupported native tool');
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

if (typeof module !== "undefined") module.exports = {runNativeReplacement};
