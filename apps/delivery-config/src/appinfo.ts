export type AppInfo = {build: string; config_path: string; config_kind: string};

export function isTestConfig(info?: Pick<AppInfo, 'config_kind'>): boolean {
  return info?.config_kind === 'test';
}

// 页面右上角标签；取不到构建号时如实说“构建号未知”，不影响读配置。
export function instanceLabel(info?: Pick<AppInfo, 'build' | 'config_kind'>): string {
  return (isTestConfig(info) ? '测试配置 · ' : '本机设置 · ') + (info?.build || '构建号未知');
}

// 悬停提示：完整配置路径；取不到时为空。
export function instanceTitle(info?: Pick<AppInfo, 'config_path'>): string {
  return info?.config_path || '';
}

// 调用失败一律当作未知，绝不向外抛：标签是辅助信息，不得阻断设置读取。
export async function loadAppInfo(call: () => Promise<AppInfo>): Promise<AppInfo | undefined> {
  try {
    return await call();
  } catch {
    return undefined;
  }
}
