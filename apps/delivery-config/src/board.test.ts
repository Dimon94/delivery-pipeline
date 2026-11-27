import { expect, test } from 'bun:test';
import type { BoardSnapshot } from './board';

const samples = new URL('../../../skills/delivery-pipeline/scripts/board_samples/', import.meta.url);

test('按看板类型读取 Python 与 Host 共用的快照样本', async () => {
  const board: BoardSnapshot = await Bun.file(new URL('board.json', samples)).json();
  const [active, ended] = board.repos.flatMap((repo) => repo.epics);
  const mmf = active?.mmfs[0];

  expect(board.schema).toBe(1);
  expect(board.repos).toHaveLength(2);
  expect(ended?.ended).toBe(true);
  expect(mmf?.tickets).toHaveLength(12);
  expect(mmf?.tickets.find((ticket) => ticket.id === '10')?.deps).toEqual(['07', '09']);
  expect(mmf?.tickets.find((ticket) => ticket.id === '03')?.lane).toBeNull();
  expect(mmf?.tickets.find((ticket) => ticket.lane?.state === 'running')?.lane?.live).toBe('unknown');
  expect(mmf?.direct_lanes[0]?.state).toBe('close_pending');
  expect(mmf?.halt?.options).toEqual(['retry', 'stop']);
  expect(board.inbox.map((item) => item.attribution)).toEqual(['unassigned', 'unassigned', 'unassigned']);
  expect(board.errors[0]?.map).toBe('reading-error');
});

test('现场样本区分 MMF 直挂 lane 和子票的执行中状态', async () => {
  const board: BoardSnapshot = await Bun.file(new URL('probed.json', samples)).json();
  const mmf = board.repos[0]?.epics[0]?.mmfs[0];
  const [running, blocked, merged] = board.inbox;

  expect(mmf?.direct_lanes[0]?.live).toBe('working');
  expect(mmf?.executing).toBe(true);
  expect(mmf?.tickets[0]?.executing).toBe(false);
  expect(running?.executing).toBe(false);
  expect(running?.tickets[0]?.executing).toBe(true);
  expect(blocked?.tickets[0]?.lane?.state).toBe('blocked');
  expect(merged?.stage).toBe('merged');
  expect(new Set(board.inbox.map((item) => item.repo)).size).toBe(2);
  expect(board.probes.map((probe) => probe.status)).toEqual(['ok', 'missing', 'failed']);
});
