import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import type {BoardSnapshot} from './board';
import {buildBoardGroups,epicHasRunningTicket,inboxItemExecuting,renderLeftColumn} from './board-side';

const boardSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board.json',import.meta.url),'utf8')) as BoardSnapshot;
const probedSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/probed.json',import.meta.url),'utf8')) as BoardSnapshot;
const linearSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board-linear.json',import.meta.url),'utf8')) as BoardSnapshot;

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
  expect(Boolean(el.querySelector('svg.exec-ring rect.exec-ring-path'))).toBe(exp.executing);
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

test('DD-668 溢出反例：80 字符无空格 map 名与长错误原因全文可读，长 MMF 标题通过 title 保留全称',()=>{
 const longMap='broken_map_with_extremely_long_unbroken_identifier_without_spaces_0123456789abcdef';
 const longReason='JSONDecodeError: Expecting property name enclosed in double quotes at line 1 column 2 (char 1) ' + 'segment_without_spaces_0123456789'.repeat(3);
 const longMmfTitle='生产只读带 ANALYZE 补测素材 1/7 日基线、表规模与方案 A 计划形状与全链路校验回归';
 const snap:BoardSnapshot=structuredClone(boardSample);
 snap.repos[0]!.epics[0]!.mmfs[0]!.title=longMmfTitle;
 snap.errors=[{map:longMap,reason:longReason}];
 const groups=buildBoardGroups(snap);
 const doc=mount(renderLeftColumn({
  groups,
  selectedGroupId:groups.all[0]!.id,
  selectedMap:groups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  expandedEpics:new Map(),
 }));
 const mmfBtn=doc.querySelector<HTMLElement>('.board-mmf-entry')!;
 expect(mmfBtn.getAttribute('title')).toContain(longMmfTitle);
 const errItem=doc.querySelector<HTMLElement>(`.board-error-item[data-error-map="${longMap}"]`)!;
 expect(errItem.querySelector('.board-error-map')!.textContent).toBe(longMap);
 expect(errItem.querySelector('.board-error-map')!.classList.contains('mono')).toBe(true);
 expect(errItem.querySelector('.board-error-reason')!.textContent).toBe(longReason);
});

test('DD-668 visual-fix-2 项1：左栏 Inbox 位于顶部第一组、默认折叠且标题行带展开控件，随后进行中、已结束与读取失败，R6 进行中 Epic 默认展开保留',()=>{
 const snap:BoardSnapshot=structuredClone(probedSample);
 snap.repos[0]!.epics.push({
  key:'DEMO-ENDED',
  url:null,
  title:'已结束需求',
  ended:true,
  mmfs:[],
 });
 snap.errors=[{map:'broken-map',reason:'缺少可读的 driver.json'}];
 const groups=buildBoardGroups(snap);
 const doc=mount(renderLeftColumn({
  groups,
  selectedGroupId:groups.all[0]!.id,
  selectedMap:groups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  expandedEpics:new Map(),
 }));

 const sections=[...doc.querySelectorAll<HTMLElement>('.board-left-body > *')];
 expect(sections.length).toBeGreaterThanOrEqual(4);
 expect(sections[0]!.classList.contains('board-inbox')).toBe(true);
 expect(sections[1]!.hasAttribute('data-repo')).toBe(true);
 expect(sections[sections.length-2]!.classList.contains('board-ended')).toBe(true);
 expect(sections[sections.length-1]!.classList.contains('board-errors')).toBe(true);

 const inboxToggle=sections[0]!.querySelector<HTMLButtonElement>('[data-board="toggle-inbox"]');
 expect(inboxToggle).not.toBeNull();
 expect(inboxToggle!.getAttribute('aria-expanded')).toBe('false');
 expect(inboxToggle!.textContent).toContain('▸');
 expect(inboxToggle!.textContent).toContain('Inbox · 待归属');
 expect(inboxToggle!.textContent).toContain(String(groups.inbox.items.length));
 expect(sections[0]!.querySelector<HTMLElement>('.inbox-list')!.hidden).toBe(true);

 // R6：有 running 票的进行中 Epic 仍默认展开
 const activeEpic=doc.querySelector<HTMLElement>('.board-epic[data-epic="example/dispatch|DEMO-1"]')!;
 expect(activeEpic.dataset.expanded).toBe('true');
 expect(activeEpic.querySelector<HTMLElement>('.epic-mmfs')!.hidden).toBe(false);

 // 展开 Inbox 后列表可见
 const docOpen=mount(renderLeftColumn({
  groups,
  selectedGroupId:groups.all[0]!.id,
  selectedMap:groups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  inboxOpen:true,
  expandedEpics:new Map(),
 } as Parameters<typeof renderLeftColumn>[0]));
 const openToggle=docOpen.querySelector<HTMLButtonElement>('[data-board="toggle-inbox"]')!;
 expect(openToggle.getAttribute('aria-expanded')).toBe('true');
 expect(openToggle.textContent).toContain('▾');
 expect(docOpen.querySelector<HTMLElement>('.board-inbox .inbox-list')!.hidden).toBe(false);
});

test('S2/S3 M1 样本左栏不显示 Linear 状态标签；带成功 Linear 缓存的 Epic 显示 Linear 标题与状态',()=>{
 for(const snap of [boardSample,probedSample]){
  const groups=buildBoardGroups(snap);
  expect(groups.all.every(g=>!g.hasLinear)).toBe(true);
  const doc=mount(renderLeftColumn({
   groups,
   selectedGroupId:groups.all[0]?.id,
   selectedMap:groups.all[0]?.mmfs[0]?.map,
   open:true,
   endedOpen:true,
   expandedEpics:new Map(),
  }));
  expect(doc.querySelector('.epic-linear-status')).toBeNull();
 }

 const linearGroups=buildBoardGroups(linearSample);
 expect(linearGroups.repos[0]!.epics[0]!.group.label).toBe('DEMO-1 · 交付看板');
 expect(linearGroups.repos[0]!.epics[0]!.group.hasLinear).toBe(true);
 expect(linearGroups.repos[0]!.epics[0]!.group.linearStatus).toBe('In Progress');
 const linearDoc=mount(renderLeftColumn({
  groups:linearGroups,
  selectedGroupId:linearGroups.all[0]!.id,
  selectedMap:linearGroups.all[0]!.mmfs[0]!.map,
  open:true,
  endedOpen:false,
  expandedEpics:new Map(),
 }));
 expect(linearDoc.querySelector('.board-entry-label')!.textContent).toBe('DEMO-1 · 交付看板');
 expect(linearDoc.querySelector('.epic-linear-status')!.textContent).toBe('In Progress');
});
