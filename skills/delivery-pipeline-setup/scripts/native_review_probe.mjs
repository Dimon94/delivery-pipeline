// 只调用已安装 Pi 的原生纯解析接口（不限版本）；不运行 main/session/auth/inference。
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const load = p => import(pathToFileURL(`${input.package}/${p}`).href);
const {parseArgs} = await load('dist/cli/args.js');
const {ModelConfig} = await load('dist/core/model-config.js');
const {resolveCliModel, findExactModelReferenceMatch} = await load('dist/core/model-resolver.js');
const {getSupportedThinkingLevels, clampThinkingLevel} = await load('node_modules/@earendil-works/pi-ai/dist/models.js');
const config = await ModelConfig.load(input.models_path);
if (config.getError()) throw Error('native models.json validation failed');
const models = config.getProviderIds().flatMap(provider => {
  const c = config.getProvider(provider);
  return (c.models ?? []).map(m => ({...m, provider, api: m.api ?? c.api}));
});
const results = input.identities.map(identity => {
  const args = parseArgs(['--approve', '--model', identity.model, '--thinking', identity.effort]);
  const exact = findExactModelReferenceMatch(identity.model, models);
  // 本合同只覆盖 models.json 注册项，不把缺少 built-in 目录当正面不可用。
  if (!exact) return {identity, status:'unknown', reason:'exact registered native model source missing'};
  const resolved = resolveCliModel({cliModel:args.model, cliThinking:args.thinking,
    modelRuntime:{getModels:()=>models, hasConfiguredAuth:()=>false}});
  if (args.model !== identity.model || args.thinking !== identity.effort ||
      args.diagnostics.length || args.unknownFlags.size || resolved.error || resolved.warning ||
      resolved.model?.provider !== exact.provider || resolved.model?.id !== exact.id)
    return {identity,status:'unavailable',reason:'native argument/model parser rejected exact target'};
  if (!exact.api || !exact.thinkingLevelMap)
    return {identity,status:'unknown',reason:'native per-model API/thinking mapping source missing'};
  const levels = getSupportedThinkingLevels(exact);
  if (!levels.includes(identity.effort) || clampThinkingLevel(exact, identity.effort) !== identity.effort ||
      exact.thinkingLevelMap[identity.effort] !== identity.effort)
    return {identity,status:'unavailable',reason:'native model thinking level rejected or remapped'};
  return {identity,status:'runnable',reason:'native exact CLI parse, model resolution and unchanged thinking level accepted'};
});
console.log(JSON.stringify(results));
