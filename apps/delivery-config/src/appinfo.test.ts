import {expect, test} from 'bun:test';
import {instanceLabel, instanceTitle, isTestConfig, loadAppInfo} from './appinfo';

// R3：页面标签 = “本机设置 · <构建号>”，期望文案来自 Spec。
test('R3：标签显示构建号', () => {
  expect(instanceLabel({build: '658b108 · 2026-11-16 06:40Z'})).toBe('本机设置 · 658b108 · 2026-11-16 06:40Z');
  expect(instanceLabel({build: '658b108+未提交 · 2026-11-16 06:40Z'})).toBe('本机设置 · 658b108+未提交 · 2026-11-16 06:40Z');
});

test('R3：取不到构建号显示“构建号未知”', async () => {
  expect(instanceLabel(undefined)).toBe('本机设置 · 构建号未知');
  expect(instanceLabel({build: ''})).toBe('本机设置 · 构建号未知'); // 开发运行：未注入
  const failed = await loadAppInfo(() => Promise.reject(new Error('Host.AppInfo 不存在')));
  expect(failed).toBeUndefined();
  expect(instanceLabel(failed)).toBe('本机设置 · 构建号未知');
});

test('R3：调用成功原样返回', async () => {
  const info = {build: 'abc1234 · 2026-11-16 06:40Z', config_path: '', config_kind: ''};
  expect(await loadAppInfo(() => Promise.resolve(info))).toEqual(info);
});

// R4：测试配置时标签为“测试配置 · <构建号>”，悬停显示完整路径；正式配置保持“本机设置”。
test('R4：测试配置标签与路径提示', () => {
  const test = {build: 'abc1234 · 2026-11-16 06:40Z', config_path: '/tmp/x/model-roles.json', config_kind: 'test'};
  expect(instanceLabel(test)).toBe('测试配置 · abc1234 · 2026-11-16 06:40Z');
  expect(isTestConfig(test)).toBe(true);
  expect(instanceTitle(test)).toBe('/tmp/x/model-roles.json');
  const formal = {build: 'abc1234 · 2026-11-16 06:40Z', config_path: '/Users/a/.config/delivery-pipeline/model-roles.json', config_kind: 'formal'};
  expect(instanceLabel(formal)).toBe('本机设置 · abc1234 · 2026-11-16 06:40Z');
  expect(isTestConfig(formal)).toBe(false);
  expect(instanceTitle(formal)).toBe('/Users/a/.config/delivery-pipeline/model-roles.json');
  // 测试配置但构建号未知：仍标出测试配置
  expect(instanceLabel({build: '', config_path: '/tmp/x.json', config_kind: 'test'})).toBe('测试配置 · 构建号未知');
  // 取不到 AppInfo：不判断为测试配置，无路径提示
  expect(isTestConfig(undefined)).toBe(false);
  expect(instanceTitle(undefined)).toBe('');
});
