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
};

export type Mmf = {
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

export type InboxItem = Mmf & { repo: string; attribution: 'unassigned' };

export type Epic = {
  key: string;
  url: string | null;
  title: string;
  ended: boolean;
  mmfs: Mmf[];
};

export type Repo = { name: string; epics: Epic[] };
export type ProbeResult = { runtime: string; status: 'ok' | 'missing' | 'failed'; reason: string | null };
export type BoardError = { map: string; reason: string };

export type BoardSnapshot = {
  schema: 1;
  generated_at: string;
  lanes_root: string;
  repos: Repo[];
  inbox: InboxItem[];
  probes: ProbeResult[];
  errors: BoardError[];
};
