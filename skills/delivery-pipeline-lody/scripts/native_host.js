/** 原 Lody requester 的公开工具转发；只等待本地协议 I/O，不轮询原生 Operation。 */
async function runNativeReplacement(command, invocation, processIO, native) {
  const started = await processIO.exec({cmd: command, tty: true, yield_time_ms: 1000, max_output_tokens: 4000});
  if (!started.session_id) throw new Error('Adapter process did not start');
  let output = await processIO.write({session_id: started.session_id, chars: JSON.stringify(invocation)+'\n', yield_time_ms: 1000, max_output_tokens: 8000});
  const transcript = [];
  let buffer = '';
  const allowed = ['lody_session_create_options','lody_session_status_many','lody_session_history','lody_operation_get','lody_session_create'];
  while (true) {
    buffer += output.output;
    output = {...output, output: ''};
    const end = buffer.indexOf('\n');
    if (end < 0) {
      if (!output.session_id) throw new Error('Adapter exited before a complete protocol message: '+buffer);
      output = await processIO.write({session_id: started.session_id, chars: '', yield_time_ms: 1000, max_output_tokens: 12000});
      continue;
    }
    const line = buffer.slice(0,end).trim();
    buffer = buffer.slice(end+1);
    if (!line) continue;
    const message = JSON.parse(line);
    if (Object.hasOwn(message,'result')) return {result: message.result, transcript};
    if (!allowed.includes(message.tool)) throw new Error('Unsupported native tool');
    let reply;
    try {
      const raw = await native[message.tool](message.arguments);
      if (raw.isError) throw new Error(JSON.stringify(raw.content));
      const result = raw.structuredContent ?? (raw.content ? JSON.parse(raw.content.find(x=>x.type==='text').text) : raw);
      if (result.ok === false) throw new Error(JSON.stringify(result));
      reply = {result};
    } catch (error) { reply = {error: String(error)}; }
    transcript.push({request: message, reply});
    output = await processIO.write({session_id: started.session_id, chars: JSON.stringify(reply)+'\n', yield_time_ms: 1000, max_output_tokens: 12000});
  }
}
if (typeof module !== 'undefined') module.exports = {runNativeReplacement};
