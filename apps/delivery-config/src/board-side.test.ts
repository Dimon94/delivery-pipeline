import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import type {BoardSnapshot} from './board';
import {buildBoardGroups,epicHasRunningTicket,inboxItemExecuting,renderLeftColumn} from './board-side';

const boardSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board.json',import.meta.url),'utf8')) as BoardSnapshot;
const probedSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/probed.json',import.meta.url),'utf8')) as BoardSnapshot;

function mount(html:string) {
 const win=new Window({width:1440,height:900});
 win.document.body.innerHTML=html;
 return win.document;
}

test('S6 全部合入的 Epic 在默认折叠的“已结束”组，展开可见；有 running 票的 Epic 默认展开，无 running 票的未结束 Epic 默认折叠',()=>{
 const snap:BoardSnapshot=structuredClone(boardSample);
 snap.repos[0]!.epics.push({
  key:'DEMO-9',
  url:'https://linear.app/example/issue/DEMO-9',
  title:'静默需求',
  ended:false,
  mmfs:[{
   map:'quiet-map',
   title:'等待排期',
   stage:'tickets',
   halt:null,
   links:{plan_review:null,merge_review:null,linear:null},
   updated_at:'2026-01-15T12:00:00+00:00',
   direct_lanes:[],
   executing:false,
   tickets:[{id:'01',title:'待派发',deps:[],stage:'tickets',lane:null,executing:false,linear:null}],
  }],
 });

 const groups=buildBoardGroups(snap);
 expect(epicHasRunningTicket(snap.repos[0]!.epics[0]!)).toBe(true);
 expect(epicHasRunningTicket(snap.repos[0]!.epics[1]!)).toBe(false);
 expect(groups.ended.map(e=>e.epic.key)).toEqual(['DEMO-3']);

 const doc=mount(renderLeftColumn({
  groups,
  selectedGroupId:groups.all[0]!.id,
  selectedMap:groups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  expandedEpics:new Map(),
 }));

 // DEMO-1 有 running 票，默认展开
 const demo1=doc.querySelector<HTMLElement>('.board-epic[data-epic="example/dispatch|DEMO-1"]')!;
 expect(demo1.dataset.expanded).toBe('true');
 expect(demo1.querySelector<HTMLElement>('.epic-mmfs')!.hidden).toBe(false);
 expect(demo1.querySelector('.board-mmf-entry')!.textContent).toContain('交付规则');

 // DEMO-9 无 running 票，默认折叠
 const demo9=doc.querySelector<HTMLElement>('.board-epic[data-epic="example/dispatch|DEMO-9"]')!;
 expect(demo9.dataset.expanded).toBe('false');
 expect(demo9.querySelector<HTMLElement>('.epic-mmfs')!.hidden).toBe(true);

 // DEMO-3 全部合入，位于默认折叠的“已结束”组
 const ended=doc.querySelector<HTMLDetailsElement>('details[data-board-ended]')!;
 expect(ended.open).toBe(false);
 expect(ended.querySelector('summary')!.textContent).toContain('已结束 1');
 expect(ended.textContent).toContain('DEMO-3');

 // 展开“已结束”组可见
 const docOpen=mount(renderLeftColumn({
  groups,
  selectedGroupId:groups.all[0]!.id,
  selectedMap:groups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:true,
  expandedEpics:new Map(),
 }));
 const endedOpened=docOpen.querySelector<HTMLDetailsElement>('details[data-board-ended]')!;
 expect(endedOpened.open).toBe(true);
 expect(endedOpened.querySelector('.board-entry')!.textContent).toContain('DEMO-3');
});

test('S19 Inbox 三条各显示来源仓库、交付阶段、执行状态与 issue 链接，“待归属”与执行状态分开，running+working 带执行中标识，无分配或标记按钮',()=>{
 const groups=buildBoardGroups(probedSample);
 expect(groups.inbox.items.length).toBe(3);
 expect(inboxItemExecuting(groups.inbox.items[0]!)).toBe(true);
 expect(inboxItemExecuting(groups.inbox.items[1]!)).toBe(false);
 expect(inboxItemExecuting(groups.inbox.items[2]!)).toBe(false);

 const doc=mount(renderLeftColumn({
  groups,
  selectedGroupId:groups.all[0]!.id,
  selectedMap:groups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  expandedEpics:new Map(),
 }));

 const section=doc.querySelector<HTMLElement>('.board-inbox')!;
 const items=[...section.querySelectorAll<HTMLElement>('.inbox-item')];
 expect(items.length).toBe(3);

 const expected=[
  {map:'check-notices',repo:'example/dispatch',stage:'实施',status:'执行中',href:'https://linear.app/example/issue/DEMO-6',executing:true},
  {map:'repair-input',repo:'example/publisher',stage:'实施',status:'需处理 · blocked',href:'https://linear.app/example/issue/DEMO-7',executing:false},
  {map:'reconcile',repo:'example/dispatch',stage:'合入',status:'已完成',href:'https://linear.app/example/issue/DEMO-8',executing:false},
 ];

 items.forEach((el,i)=>{
  const exp=expected[i]!;
  expect(el.dataset.inboxMap).toBe(exp.map);
  expect(el.querySelector('.inbox-repo')!.textContent).toBe(exp.repo);
  expect(el.querySelector('.inbox-stage')!.textContent).toBe(exp.stage);
  const attr=el.querySelector('.inbox-attribution')!;
  const status=el.querySelector('.inbox-status')!;
  // “待归属”与执行状态分开显示在不同节点
  expect(attr.textContent).toBe('待归属');
  expect(status.textContent).toBe(exp.status);
  expect(attr).not.toBe(status);
  expect(status.textContent).not.toContain('待归属');

  const link=el.querySelector<HTMLAnchorElement>('.inbox-link')!;
  expect(link.getAttribute('href')).toBe(exp.href);

  expect(el.classList.contains('is-executing')).toBe(exp.executing);
  expect(Boolean(el.querySelector('.exec-dot'))).toBe(exp.executing);
  expect(status.classList.contains('exec-label')).toBe(exp.executing);

  // 每条 Inbox 只有 1 个查看选择按钮，无任何分配/归属/标记按钮
  const buttons=[...el.querySelectorAll('button')];
  expect(buttons.length).toBe(1);
  expect(buttons[0]!.dataset.board).toBe('side-mmf');
  expect(el.textContent).not.toMatch(/分配|归属到|标记|忽略|移入/);
 });
});

test('S12/R3 左栏独立渲染读取失败分组并显示条数、map 名与原因原文，无按钮；errors 为空时不渲染该分组',()=>{
 const withErrors:BoardSnapshot=structuredClone(boardSample);
 withErrors.errors=[{map:'tkada-jb416',reason:'缺少可读的 driver.json 与 registry'}];
 const groups=buildBoardGroups(withErrors);
 const doc=mount(renderLeftColumn({
  groups,
  selectedGroupId:groups.all[0]!.id,
  selectedMap:groups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  expandedEpics:new Map(),
 }));
 const section=doc.querySelector<HTMLElement>('.board-errors')!;
 expect(section).not.toBeNull();
 expect(section.hidden).toBe(false);
 expect(section.querySelector('h3')!.textContent).toBe('读取失败');
 expect(section.querySelector('small')!.textContent).toBe('1');
 const item=section.querySelector<HTMLElement>('.board-error-item[data-error-map="tkada-jb416"]')!;
 expect(item).not.toBeNull();
 expect(item.textContent).toContain('tkada-jb416');
 expect(item.textContent).toContain('缺少可读的 driver.json 与 registry');
 expect(section.querySelectorAll('button').length).toBe(0);
 expect(doc.querySelector('.board-epic[data-epic="example/dispatch|DEMO-1"]')).not.toBeNull();

 const emptyGroups=buildBoardGroups({...structuredClone(boardSample),errors:[]});
 const emptyDoc=mount(renderLeftColumn({
  groups:emptyGroups,
  selectedGroupId:emptyGroups.all[0]!.id,
  selectedMap:emptyGroups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  expandedEpics:new Map(),
 }));
 expect(emptyDoc.querySelector('.board-errors')).toBeNull();
 expect(emptyDoc.body.textContent).not.toContain('读取失败');
});
