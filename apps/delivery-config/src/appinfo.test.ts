import {expect, test} from 'bun:test';
import {instanceLabel, loadAppInfo} from './appinfo';

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
