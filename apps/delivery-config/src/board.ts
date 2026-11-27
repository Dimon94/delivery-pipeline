export type Stage = 'spec' | 'tickets' | 'implement' | 'integrate' | 'review' | 'merge_review' | 'merged';
export type LiveStatus = 'working' | 'not_working' | 'unknown';
export type LaneGroup = 'done' | 'active' | 'review' | 'problem' | 'void';

export type Lane = {
  lane_id: string;
  role: string;
  state: string;
  group: LaneGroup;
  agent: string;
  model: string;
  worktree: string | null;
  branch: string | null;
  blocked_reason: string | null;
  updated_at: string | null;
  live: LiveStatus;
};

export type Halt = {
  id: string;
  kind: string;
  label: string;
  reason: string;
  options: string[];
};

export type Ticket = {
  id: string;
  title: string;
  deps: string[];
  stage: Stage | 'Unknown';
  lane: Lane | null;
  executing: boolean;
  linear: string | null;
  linear_issue?: { title: string; status: string };
};

export type Mmf = {
  archived_at?: string;
  mmf_id?: string;
  attribution_source?: 'linear';
  map: string;
  title: string;
  stage: Stage | 'Unknown';
  halt: Halt | null;
  links: { plan_review: string | null; merge_review: string | null; linear: string | null };
  updated_at: string | null;
  direct_lanes: Lane[];
  executing: boolean;
  tickets: Ticket[];
};

export function isFinishedMmf(mmf:Mmf):boolean {
  return mmf.stage==='merged'||Boolean(mmf.archived_at);
}

export type InboxItem = Mmf & { repo: string; attribution: 'unassigned'; kind?: 'spec' | 'item' };

export type MmfCandidate = {
  mmf_id: string;
  title: string;
  spec: { key: string; url: string; status: string } | null;
  source: 'epic_table' | 'linear_child';
};

export type MmfEdge = {
  from: string;
  to: string;
  kind: '开工' | '上线' | 'Unknown';
  text: string;
};

export type Epic = {
  key: string;
  url: string | null;
  title: string;
  ended: boolean;
  mmfs: Mmf[];
  linear_status?: string;
  candidates?: MmfCandidate[];
  mmf_edges?: MmfEdge[];
};

export type Repo = { name: string; epics: Epic[] };
export type ProbeResult = { runtime: string; status: 'ok' | 'missing' | 'failed'; reason: string | null };
export type BoardError = { map: string; reason: string };

export type BoardLinear = {
  status: 'ok' | 'partial' | 'failed';
  fetched_at: string | null;
  attempted_at: string;
  reason: string | null;
};

export type BoardSnapshot = {
  schema: 1;
  generated_at: string;
  lanes_root: string;
  repos: Repo[];
  inbox: InboxItem[];
  probes: ProbeResult[];
  errors: BoardError[];
  linear?: BoardLinear;
};

const isObj = (v: unknown): v is Record<string, unknown> => Boolean(v) && typeof v === 'object' && !Array.isArray(v);

type FieldCheck = (raw: unknown, path: string) => string | null;
const stringField: FieldCheck = (raw, path) => typeof raw === 'string' ? null : `${path}：需要字符串`;
const nullable = (check: FieldCheck): FieldCheck => (raw, path) => raw === null ? null : check(raw, path);
const choice = (...values: string[]): FieldCheck => (raw, path) =>
  typeof raw === 'string' && values.includes(raw) ? null : `${path}：取值必须为 ${values.join('、')}`;

function checkFields(raw: Record<string, unknown>, path: string, fields: Record<string, FieldCheck>,
                     optional = false): string | null {
  for (const [field, check] of Object.entries(fields)) {
    if (optional && raw[field] === undefined) continue;
    const error = check(raw[field], `${path}.${field}`);
    if (error) return error;
  }
  return null;
}

const objectOf = (fields: Record<string, FieldCheck>): FieldCheck => (raw, path) =>
  isObj(raw) ? checkFields(raw, path, fields) : `${path}：需要对象`;

const arrayOf = (check: FieldCheck): FieldCheck => (raw, path) => {
  if (!Array.isArray(raw)) return `${path}：需要数组`;
  for (let i = 0; i < raw.length; i++) {
    const error = check(raw[i], `${path}[${i}]`);
    if (error) return error;
  }
  return null;
};

const epicLinearFields = {
  linear_status: stringField,
  candidates: arrayOf(objectOf({
    mmf_id: stringField,
    title: stringField,
    spec: nullable(objectOf({ key: stringField, url: stringField, status: stringField })),
    source: choice('epic_table', 'linear_child'),
  })),
  mmf_edges: arrayOf(objectOf({
    from: stringField, to: stringField, kind: choice('开工', '上线', 'Unknown'), text: stringField,
  })),
};
const mmfLinearFields = { mmf_id: stringField, attribution_source: choice('linear') };
const ticketLinearFields = { linear_issue: objectOf({ title: stringField, status: stringField }) };
const boardLinearFields = {
  linear: objectOf({
    status: choice('ok', 'partial', 'failed'), fetched_at: nullable(stringField),
    attempted_at: stringField, reason: nullable(stringField),
  }),
};

function validateMmfShape(raw: unknown, path: string): string | null {
  if (!isObj(raw)) return `${path}：需要对象`;
  for (const field of ['map', 'title', 'stage'] as const) {
    if (typeof raw[field] !== 'string') return `${path}.${field}：需要字符串`;
  }
  if (typeof raw.executing !== 'boolean') return `${path}.executing：需要布尔值`;
  if (!isObj(raw.links)) return `${path}.links：需要对象`;
  if (!Array.isArray(raw.direct_lanes)) return `${path}.direct_lanes：需要数组`;
  if (!Array.isArray(raw.tickets)) return `${path}.tickets：需要数组`;
  for (let i = 0; i < raw.tickets.length; i++) {
    const t = raw.tickets[i];
    const tp = `${path}.tickets[${i}]`;
    if (!isObj(t)) return `${tp}：需要对象`;
    for (const field of ['id', 'title', 'stage'] as const) {
      if (typeof t[field] !== 'string') return `${tp}.${field}：需要字符串`;
    }
    if (!Array.isArray(t.deps)) return `${tp}.deps：需要数组`;
    if (typeof t.executing !== 'boolean') return `${tp}.executing：需要布尔值`;
    const err = checkFields(t, tp, ticketLinearFields, true);
    if (err) return err;
  }
  return checkFields(raw, path, mmfLinearFields, true);
}

// 校验 schema 1 内部结构，避免坏快照进入渲染抛异常或停在读取中。
export function validateBoardSnapshot(raw: unknown): string | null {
  if (!isObj(raw)) return '$：看板快照必须是 JSON 对象';
  if (raw.schema !== 1) return '$.schema：看板快照 schema 必须为 1';
  if (!Array.isArray(raw.repos)) return '$.repos：需要数组';
  for (let i = 0; i < raw.repos.length; i++) {
    const repo = raw.repos[i];
    const rp = `$.repos[${i}]`;
    if (!isObj(repo)) return `${rp}：需要对象`;
    if (typeof repo.name !== 'string') return `${rp}.name：需要字符串`;
    if (!Array.isArray(repo.epics)) return `${rp}.epics：需要数组`;
    for (let j = 0; j < repo.epics.length; j++) {
      const epic = repo.epics[j];
      const ep = `${rp}.epics[${j}]`;
      if (!isObj(epic)) return `${ep}：需要对象`;
      if (typeof epic.key !== 'string') return `${ep}.key：需要字符串`;
      if (typeof epic.title !== 'string') return `${ep}.title：需要字符串`;
      if (typeof epic.ended !== 'boolean') return `${ep}.ended：需要布尔值`;
      if (!Array.isArray(epic.mmfs)) return `${ep}.mmfs：需要数组`;
      const linearError = checkFields(epic, ep, epicLinearFields, true);
      if (linearError) return linearError;
      for (let k = 0; k < epic.mmfs.length; k++) {
        const err = validateMmfShape(epic.mmfs[k], `${ep}.mmfs[${k}]`);
        if (err) return err;
      }
    }
  }
  if (!Array.isArray(raw.inbox)) return '$.inbox：需要数组';
  for (let i = 0; i < raw.inbox.length; i++) {
    const err = validateMmfShape(raw.inbox[i], `$.inbox[${i}]`);
    if (err) return err;
  }
  if (raw.errors !== undefined) {
    if (!Array.isArray(raw.errors)) return '$.errors：需要数组';
    for (let i = 0; i < raw.errors.length; i++) {
      const item = raw.errors[i];
      if (!isObj(item) || typeof item.map !== 'string' || typeof item.reason !== 'string') {
        return `$.errors[${i}]：需要包含 map 与 reason`;
      }
    }
  }
  return checkFields(raw, '$', boardLinearFields, true);
}
