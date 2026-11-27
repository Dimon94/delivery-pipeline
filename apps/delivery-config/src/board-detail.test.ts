import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import type {BoardSnapshot} from './board';
import {renderRightColumn,renderStageBar} from './board-detail';

const boardSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board.json',import.meta.url),'utf8')) as BoardSnapshot;

function mount(html:string) {
 const win=new Window({width:1440,height:900});
 win.document.body.innerHTML=html;
 return win.document;
}

test('S11 七步条正确标识已完成、当前与待进行阶段；Unknown 阶段原样展示且无误亮',()=>{
 const doc=mount(renderStageBar('integrate'));
 const steps=[...doc.querySelectorAll<HTMLElement>('.stage-step')];
 expect(steps.length).toBe(7);
 expect(steps.map(s=>s.dataset.stage)).toEqual(['spec','tickets','implement','integrate','review','merge_review','merged']);
 expect(steps.slice(0,3).every(s=>s.classList.contains('done'))).toBe(true);
 expect(steps[3]!.classList.contains('current')).toBe(true);
 expect(steps[3]!.getAttribute('aria-current')).toBe('step');
 expect(steps.slice(4).every(s=>s.classList.contains('pending'))).toBe(true);

 const unknownDoc=mount(renderStageBar('Unknown'));
 expect(unknownDoc.querySelector('.stage-step.current')).toBeNull();
 expect(unknownDoc.querySelector('.stage-step.done')).toBeNull();
 expect(unknownDoc.querySelector('.stage-unknown')!.textContent).toBe('Unknown');
});

test('S11 票详情与 MMF 详情显示对应七步条、现场与链接，“更多现场信息”默认折叠，无写操作按钮',()=>{
 const mmf=boardSample.repos[0]!.epics[0]!.mmfs[0]!;
 const ticket01=mmf.tickets[0]!;

 // 票详情
 const ticketDoc=mount(renderRightColumn({mmf,ticket:ticket01,inbox:false,open:true}));
 expect(ticketDoc.querySelector('#board-right h2')!.textContent).toBe('dispatch-rules · 01');
 expect(ticketDoc.querySelector('.detail-title')!.textContent).toBe('冻结接口');
 expect(ticketDoc.querySelector('.stage-step.current')!.getAttribute('data-stage')).toBe('integrate');
 const ticketLinks=[...ticketDoc.querySelectorAll<HTMLAnchorElement>('.detail-links a')];
 expect(ticketLinks.map(a=>a.getAttribute('href'))).toEqual(['/fixture/artifacts/plan-review.html','https://linear.app/example/issue/DEMO-11']);
 expect(ticketDoc.querySelector('.detail-core')!.textContent).toContain('feat/sample-01');
 const ticketMore=ticketDoc.querySelector<HTMLDetailsElement>('details.detail-more')!;
 expect(ticketMore.open).toBe(false);
 expect(ticketMore.querySelector('summary')!.textContent).toBe('更多现场信息');
 expect(ticketMore.textContent).toContain('dispatch-01');
 expect(ticketMore.textContent).toContain('/fixture/worktrees/demo-01');

 // MMF 详情（带 Halt 与 Plan Review 链接）
 const mmfDoc=mount(renderRightColumn({mmf,ticket:undefined,inbox:false,open:true}));
 expect(mmfDoc.querySelector('#board-right h2')!.textContent).toBe('MMF');
 expect(mmfDoc.querySelector('.detail-title')!.textContent).toBe('交付规则');
 expect(mmfDoc.querySelector('.stage-step.current')!.getAttribute('data-stage')).toBe('implement');
 expect(mmfDoc.body.textContent).toContain('工作会话待关闭');
 expect(mmfDoc.body.textContent).toContain('等待确认会话上的当前执行者');
 const mmfLinks=[...mmfDoc.querySelectorAll<HTMLAnchorElement>('.detail-links a')].map(a=>a.getAttribute('href'));
 expect(mmfLinks).toEqual(['/fixture/artifacts/plan-review.html','https://linear.app/example/issue/DEMO-2']);
 const mmfMore=mmfDoc.querySelector<HTMLDetailsElement>('details.detail-more')!;
 expect(mmfMore.open).toBe(false);
 expect(mmfDoc.querySelector('.detail-core')!.textContent).toContain('dispatch-review');

 // 右栏不含写操作按钮（仅收起按钮与上下游只读导航芯片），无回复 Halt / 确认 Merge Review / 触发 Driver 按钮
 for(const doc of [ticketDoc,mmfDoc]){
  const buttons=[...doc.querySelectorAll('#board-right button:not(.detail-chip)')];
  expect(buttons.length).toBe(1);
  expect(buttons[0]!.textContent).toBe('收起右栏');
  for(const btn of doc.querySelectorAll('#board-right button')){
   expect(btn.textContent).not.toMatch(/回复 Halt|确认 Merge Review|触发 Driver/);
  }
 }
});

test('DD-668 视觉对齐与溢出反例：右栏纵向七步全称不截断，长中英文标题与 80 字符无空格标识符全文可读且防撑栏',()=>{
 const cssText=readFileSync(new URL('./style.css',import.meta.url),'utf8');
 const win=new Window({width:1440,height:900});
 const sheet=new win.CSSStyleSheet();
 sheet.replaceSync(cssText);
 const rules=[...sheet.cssRules].filter((r):r is CSSStyleRule=>r.type===1);

 // 阶段名全称对齐原型（spec、tickets、实施、集成、审查、Merge Review、合入）
 const stageDoc=mount(renderStageBar('merge_review'));
 const labels=[...stageDoc.querySelectorAll('.stage-step .step-label')].map(el=>el.textContent?.trim());
 expect(labels).toEqual(['spec','tickets','实施','集成','审查','Merge Review','合入']);

 // 样式为纵向步骤（非 7 等分横排），不截断阶段名
 const barRule=rules.find(r=>r.selectorText?.split(',').some(s=>s.trim()==='.stage-bar'));
 expect(barRule).toBeDefined();
 expect(barRule!.style.getPropertyValue('grid-template-columns')).not.toContain('repeat(7');
 const stepRule=rules.find(r=>r.selectorText?.split(',').some(s=>s.trim()==='.stage-step'));
 expect(stepRule).toBeDefined();
 expect(stepRule!.style.getPropertyValue('text-overflow')).not.toBe('ellipsis');

 // 长中英文标题 + 80 字符无空格 lane_id / branch / worktree 全文可读
 const longTitle='生产只读带 ANALYZE 补测素材 1/7 日基线、表规模与方案 A 计划形状（已完成，JB-459）';
 const longId='lane_delivery_pipeline_dd668_unbroken_identifier_without_any_spaces_0123456789abcdef';
 const mmf=structuredClone(boardSample.repos[0]!.epics[0]!.mmfs[0]!);
 const tk=structuredClone(mmf.tickets[0]!);
 tk.title=longTitle;
 tk.lane={...tk.lane!,lane_id:longId,branch:`feat/${longId}`,worktree:`/tmp/${longId}`,blocked_reason:`阻塞原因全文：${longId}`};
 const doc=mount(renderRightColumn({mmf,ticket:tk,inbox:false,open:true}));
 expect(doc.querySelector('.detail-title')!.textContent).toBe(longTitle);
 expect(doc.body.textContent).toContain(longId);
 expect(doc.body.textContent).toContain(`feat/${longId}`);
 expect(doc.body.textContent).toContain(`阻塞原因全文：${longId}`);
 expect(doc.querySelectorAll('.mono').length).toBeGreaterThanOrEqual(2);
});

function makeProtoLikeMmf() {
 const mmf=structuredClone(boardSample.repos[0]!.epics[0]!.mmfs[0]!);
 mmf.map='ep-101-m3';
 mmf.title='投放执行与重试';
 mmf.stage='implement';
 mmf.halt={
  id:'halt-t7',
  kind:'plan_change',
  label:'计划变更',
  reason:'needs-decision：重试上限由谁定未写进 Spec',
  options:['补充 Spec/验收来源后重派','改范围','放弃该票'],
 };
 mmf.links={
  plan_review:'/fixture/ep-101-m3/plan-review.html',
  merge_review:null,
  linear:'https://linear.app/demo/issue/EP-101',
 };
 mmf.tickets=[
  {
   id:'T1',title:'执行队列表',deps:[],stage:'integrate',executing:false,linear:null,
   lane:{lane_id:'ep-101-m3-t1',role:'backend',state:'integrated',group:'done',agent:'pi',model:'sonnet-5-5',worktree:'/tmp/sample/t1',branch:'feat/ep-101-m3-t1',blocked_reason:null,updated_at:'2026-11-26T09:10:00+00:00',live:'unknown'},
  },
  {
   id:'T5',title:'失败分类',deps:['T1'],stage:'implement',executing:false,linear:null,
   lane:{lane_id:'ep-101-m3-t5',role:'frontend',state:'terminal',group:'review',agent:'pi',model:'sonnet-5-5',worktree:'/tmp/sample/t5',branch:'feat/ep-101-m3-t5',blocked_reason:null,updated_at:'2026-11-26T15:38:00+00:00',live:'unknown'},
  },
  {
   id:'T6',title:'指数退避重试',deps:['T5'],stage:'implement',executing:false,linear:null,
   lane:{lane_id:'ep-101-m3-t6',role:'frontend',state:'running',group:'active',agent:'codex',model:'gpt-5.5',worktree:'/tmp/sample/t6',branch:'feat/ep-101-m3-t6',blocked_reason:'registry 写着 running，但本机找不到匹配的活 agent（现场 Unknown）',updated_at:'2026-11-26T16:45:00+00:00',live:'unknown'},
  },
  {
   id:'T7',title:'人工重试入口',deps:['T5'],stage:'implement',executing:false,linear:null,
   lane:{lane_id:'ep-101-m3-t7',role:'frontend',state:'blocked',group:'problem',agent:'claude',model:'opus-5-5',worktree:'/tmp/sample/t7',branch:'feat/ep-101-m3-t7',blocked_reason:'needs-decision：重试上限由谁定未写进 Spec',updated_at:'2026-11-26T09:52:00+00:00',live:'unknown'},
  },
 ];
 return mmf;
}

function cssRules() {
 const cssText=readFileSync(new URL('./style.css',import.meta.url),'utf8');
 const win=new Window({width:1440,height:900});
 const sheet=new win.CSSStyleSheet();
 sheet.replaceSync(cssText);
 return [...sheet.cssRules].filter((r):r is CSSStyleRule=>r.type===1);
}

test('DD-668 visual-fix-3 项10：票详情头部为 Epic·MMF·票路径，正文票名无 MMF 副行',()=>{
 const mmf=makeProtoLikeMmf();
 const t7=mmf.tickets.find(t=>t.id==='T7')!;
 const doc=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t7,inbox:false,open:true}));
 expect(doc.querySelector('#board-right h2')!.textContent).toBe('EP-101 · M3 · T7');
 expect(doc.querySelector('.detail-title')!.textContent).toBe('人工重试入口');
 expect(doc.querySelector('.detail-sub')).toBeNull();
 const titleRule=cssRules().find(r=>r.selectorText?.split(',').some(s=>s.trim()==='.detail-title'));
 expect(titleRule).toBeDefined();
 expect(titleRule!.style.getPropertyValue('margin')).toBe('0px 0px 12px');
});

test('DD-668 visual-fix-3 项11：七步条紧接票名无副行，纵排 min-height 24px 对齐原型密度',()=>{
 const mmf=makeProtoLikeMmf();
 const t7=mmf.tickets.find(t=>t.id==='T7')!;
 const doc=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t7,inbox:false,open:true}));
 const title=doc.querySelector('.detail-title')!;
 expect(title.nextElementSibling?.classList.contains('stage-bar-wrap')).toBe(true);
 const stepRule=cssRules().find(r=>r.selectorText?.split(',').some(s=>s.trim()==='.stage-step'));
 expect(stepRule!.style.getPropertyValue('min-height')).toBe('24px');
 expect(stepRule!.style.getPropertyValue('column-gap')).toBe('10px');
});

test('DD-668 visual-fix-3 项12：Halt 卡命中时红系显示种类、原因、全部 options 与回复指引，非 halt blocked 保持琥珀系',()=>{
 const mmf=makeProtoLikeMmf();
 const t7=mmf.tickets.find(t=>t.id==='T7')!;
 const t6=mmf.tickets.find(t=>t.id==='T6')!;
 const t1=mmf.tickets.find(t=>t.id==='T1')!;

 const doc7=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t7,inbox:false,open:true}));
 const halt7=doc7.querySelector('.detail-halt');
 expect(halt7).not.toBeNull();
 expect(halt7!.classList.contains('soft')).toBe(false);
 expect(halt7!.textContent).toContain('Halt · 计划变更');
 expect(halt7!.textContent).toContain('needs-decision：重试上限由谁定未写进 Spec');
 expect(halt7!.textContent).toContain('补充 Spec/验收来源后重派 / 改范围 / 放弃该票');
 expect(halt7!.textContent).toContain('回复 Halt 不在本看板（链接到 Driver 现场）');

 const doc6=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t6,inbox:false,open:true}));
 const halt6=doc6.querySelector('.detail-halt');
 expect(halt6).not.toBeNull();
 expect(halt6!.classList.contains('soft')).toBe(true);
 expect(halt6!.textContent).not.toContain('Halt ·');
 expect(halt6!.textContent).toContain('registry 写着 running');

 const doc1=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t1,inbox:false,open:true}));
 expect(doc1.querySelector('.detail-halt')).toBeNull();
});

test('DD-668 visual-fix-3 项13：默认呈现状态+时间、Agent/模型、分支；缺省字段显示 Unknown 不填原型值',()=>{
 const mmf=makeProtoLikeMmf();
 const t7=mmf.tickets.find(t=>t.id==='T7')!;
 const doc7=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t7,inbox:false,open:true}));
 const core=doc7.querySelector('.detail-core')!;
 const dts=[...core.querySelectorAll('dt')].map(el=>el.textContent?.trim());
 const dds=[...core.querySelectorAll('dd')].map(el=>el.textContent?.trim());
 expect(dts).toEqual(['状态','Agent','分支']);
 expect(dds[0]).toContain('11-26 09:52');
 expect(dds[1]).toBe('claude · opus-5-5');
 expect(dds[2]).toBe('feat/ep-101-m3-t7');

 const missing={...structuredClone(t7),lane:null};
 const docMissing=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:missing,inbox:false,open:true}));
 const ddsMissing=[...docMissing.querySelectorAll('.detail-core dd')].map(el=>el.textContent?.trim());
 expect(ddsMissing[0]).toContain('Unknown');
 expect(ddsMissing[1]).toBe('Unknown');
 expect(ddsMissing[2]).toBe('Unknown');
 expect(docMissing.body.textContent).not.toContain('codex · gpt-5.5');
});

test('DD-668 visual-fix-3 项14：「更多现场信息」默认收起，展开只含 lane/registry/工作树，位于上下游之上',()=>{
 const mmf=makeProtoLikeMmf();
 const t7=mmf.tickets.find(t=>t.id==='T7')!;
 const doc=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t7,inbox:false,open:true}));
 const more=doc.querySelector<HTMLDetailsElement>('details.detail-more')!;
 expect(more.open).toBe(false);
 expect(more.querySelector('summary')!.textContent).toBe('更多现场信息');
 const extraDts=[...more.querySelectorAll('dt')].map(el=>el.textContent?.trim());
 const extraDds=[...more.querySelectorAll('dd')].map(el=>el.textContent?.trim());
 expect(extraDts).toEqual(['lane','registry','工作树']);
 expect(extraDds).toEqual(['ep-101-m3-t7','blocked','/tmp/sample/t7']);
 const firstRel=doc.querySelector('.detail-rel')!;
 expect(more.compareDocumentPosition(firstRel)&4).toBe(4);
});

test('DD-668 visual-fix-3 项15与16：上游独立标题+可点芯片，下游独立区含空态「无」',()=>{
 const mmf=makeProtoLikeMmf();
 const t7=mmf.tickets.find(t=>t.id==='T7')!;
 const doc7=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t7,inbox:false,open:true}));
 const rels7=[...doc7.querySelectorAll('.detail-rel')];
 expect(rels7.length).toBe(2);
 expect(rels7[0]!.textContent).toContain('上游');
 const upChip=rels7[0]!.querySelector<HTMLButtonElement>('button.detail-chip');
 expect(upChip).not.toBeNull();
 expect(upChip!.textContent).toBe('T5 失败分类');
 expect(upChip!.dataset.board).toBe('ticket');
 expect(upChip!.dataset.map).toBe('ep-101-m3');
 expect(upChip!.dataset.ticket).toBe('T5');
 expect(rels7[1]!.textContent).toContain('下游');
 expect(rels7[1]!.textContent).toContain('无');

 const t5=mmf.tickets.find(t=>t.id==='T5')!;
 const doc5=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t5,inbox:false,open:true}));
 const rels5=[...doc5.querySelectorAll('.detail-rel')];
 expect([...rels5[0]!.querySelectorAll('button.detail-chip')].map(b=>b.textContent)).toEqual(['T1 执行队列表']);
 expect([...rels5[1]!.querySelectorAll('button.detail-chip')].map(b=>b.textContent)).toEqual(['T6 指数退避重试','T7 人工重试入口']);
});

test('DD-668 visual-fix-3 项17：链接区固定呈现 Plan Review / Merge Review / Linear 三行，缺省显示「尚无」',()=>{
 const mmf=makeProtoLikeMmf();
 const t7=mmf.tickets.find(t=>t.id==='T7')!;
 const doc=mount(renderRightColumn({epicKey:'EP-101',mmf,ticket:t7,inbox:false,open:true}));
 const links=doc.querySelector('.detail-links')!;
 const items=[...links.children];
 expect(items.length).toBe(3);
 expect(items[0]!.tagName).toBe('A');
 expect(items[0]!.getAttribute('href')).toBe('/fixture/ep-101-m3/plan-review.html');
 expect(items[0]!.textContent).toContain('Plan Review');
 expect(items[1]!.classList.contains('off')).toBe(true);
 expect(items[1]!.textContent).toContain('Merge Review');
 expect(items[1]!.textContent).toContain('尚无');
 expect(items[2]!.classList.contains('off')).toBe(true);
 expect(items[2]!.textContent).toContain('Linear');
 expect(items[2]!.textContent).toContain('尚无');
});
