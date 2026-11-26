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
 expect(ticketDoc.querySelector('#board-right h2')!.textContent).toBe('01');
 expect(ticketDoc.querySelector('.detail-title')!.textContent).toBe('冻结接口');
 expect(ticketDoc.querySelector('.stage-step.current')!.getAttribute('data-stage')).toBe('integrate');
 const ticketLinks=[...ticketDoc.querySelectorAll<HTMLAnchorElement>('.detail-links a')];
 expect(ticketLinks.map(a=>a.getAttribute('href'))).toEqual(['https://linear.app/example/issue/DEMO-11']);
 const ticketMore=ticketDoc.querySelector<HTMLDetailsElement>('details.detail-more')!;
 expect(ticketMore.open).toBe(false);
 expect(ticketMore.querySelector('summary')!.textContent).toBe('更多现场信息');
 expect(ticketMore.textContent).toContain('dispatch-01');
 expect(ticketMore.textContent).toContain('feat/sample-01');
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
 expect(mmfMore.textContent).toContain('dispatch-review');

 // 右栏仅含收起按钮，无回复 Halt / 确认 Merge Review / 触发 Driver 按钮
 for(const doc of [ticketDoc,mmfDoc]){
  const buttons=[...doc.querySelectorAll('#board-right button')];
  expect(buttons.length).toBe(1);
  expect(buttons[0]!.textContent).toBe('收起右栏');
  expect(doc.querySelector('#board-right')!.textContent).not.toMatch(/回复 Halt|确认 Merge Review|触发 Driver/);
 }
});
