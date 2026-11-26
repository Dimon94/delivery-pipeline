import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import type {BoardSnapshot,Lane,Mmf,Ticket} from './board';
import {GRAPH_GEOMETRY,applyHoverChain,dependencyChain,renderGraph,scrollTargetForNode,ticketLayers,type GraphGroup} from './board-graph';

const sample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board.json',import.meta.url),'utf8')) as BoardSnapshot;
const cssText=readFileSync(new URL('./style.css',import.meta.url),'utf8');
const win=new Window({width:1440,height:900});
const doc=win.document;
const sheet=new win.CSSStyleSheet();
sheet.replaceSync(cssText);

const makeLane=(overrides:Partial<Lane>):Lane=>({
 lane_id:'lane-x',
 role:'frontend',
 state:'running',
 group:'active',
 agent:'pi',
 model:'gpt-6.1-sol',
 worktree:null,
 branch:null,
 blocked_reason:null,
 updated_at:'2026-01-15T12:00:00+00:00',
 live:'unknown',
 ...overrides,
});

const makeTicket=(id:string,overrides:Partial<Ticket>={}):Ticket=>({
 id,
 title:`票 ${id}`,
 deps:[],
 stage:'implement',
 lane:null,
 executing:false,
 linear:null,
 ...overrides,
});

const makeMmf=(tickets:Ticket[],overrides:Partial<Mmf>={}):Mmf=>({
 map:'sample-map',
 title:'示例 MMF',
 stage:'implement',
 halt:null,
 links:{plan_review:null,merge_review:null,linear:null},
 updated_at:'2026-01-15T12:00:00+00:00',
 direct_lanes:[],
 executing:false,
 tickets,
 ...overrides,
});

test('S11 12 票 4 层 MMF 悬停只保留上下游链高亮，其余节点与非链边淡出，离开后恢复',()=>{
 const mmf=sample.repos[0]!.epics[0]!.mmfs[0]!;
 expect(mmf.tickets.length).toBe(12);
 const layers=ticketLayers(mmf.tickets);
 expect(Math.max(...layers.values())).toBe(3); // 0..3 共 4 层

 // 票 05 位于第 2 层：上游 02，下游 07, 08, 10, 11, 12
 const chain=dependencyChain(mmf.tickets,'05');
 expect([...chain.nodes].sort()).toEqual(['02','05','07','08','10','11','12']);
 expect([...chain.edges].sort()).toEqual(['02>05','05>07','05>08','07>10','08>11','08>12']);

 const group:GraphGroup={id:'example/dispatch|DEMO-1',label:'DEMO-1',url:null,mmfs:[mmf]};
 const box=doc.createElement('div');
 box.innerHTML=renderGraph(group,mmf,mmf.tickets[0]);

 applyHoverChain(box,group,{map:mmf.map,ticket:'05'});
 expect(box.querySelector('.graph')!.classList.contains('has-hover')).toBe(true);
 const highlighted=[...box.querySelectorAll<HTMLElement>('.graph-ticket.chain')].map(el=>el.dataset.ticket).sort();
 const dimmed=[...box.querySelectorAll<HTMLElement>('.graph-ticket.dimmed')].map(el=>el.dataset.ticket).sort();
 expect(highlighted).toEqual(['02','05','07','08','10','11','12']);
 expect(dimmed).toEqual(['01','03','04','06','09']);

 const chainPaths=[...box.querySelectorAll('path[data-dep].chain')].map(p=>p.getAttribute('data-dep')).sort();
 const dimmedPaths=[...box.querySelectorAll('path[data-dep].dimmed')].map(p=>p.getAttribute('data-dep')).sort();
 expect(chainPaths).toEqual(['02>05','05>07','05>08','07>10','08>11','08>12']);
 expect(dimmedPaths).toEqual(['01>04','02>04','03>06','04>07','06>08','06>09','09>10','09>12']);

 // 鼠标离开后恢复
 applyHoverChain(box,group,undefined);
 expect(box.querySelector('.graph')!.classList.contains('has-hover')).toBe(false);
 expect(box.querySelectorAll('.chain,.dimmed').length).toBe(0);
});

test('S15 同 MMF 只有 executing 为真有虚线环与“执行中”，running+live unknown 显示静态“running · 现场 Unknown”，MMF 不跟亮',()=>{
 const tExec=makeTicket('01',{executing:true,lane:makeLane({state:'running',group:'active',live:'working'})});
 const tBlocked=makeTicket('02',{executing:false,lane:makeLane({state:'blocked',group:'problem',live:'unknown'})});
 const tHuman=makeTicket('03',{executing:false,lane:makeLane({state:'awaiting_human',group:'active',live:'unknown'})});
 const tRunUnknown=makeTicket('04',{executing:false,lane:makeLane({state:'running',group:'active',live:'unknown'})});
 const mmf=makeMmf([tExec,tBlocked,tHuman,tRunUnknown],{executing:false});
 const group:GraphGroup={id:'repo|E1',label:'E1',url:null,mmfs:[mmf]};

 const box=doc.createElement('div');
 box.innerHTML=renderGraph(group,mmf,tExec);

 const card=(id:string)=>box.querySelector<HTMLElement>(`.graph-ticket[data-ticket="${id}"]`)!;
 expect(card('01').classList.contains('is-executing')).toBe(true);
 expect(card('01').querySelector('.exec-ring .exec-ring-path')).not.toBeNull();
 expect(card('01').textContent).toContain('执行中');

 for(const id of ['02','03','04']){
  expect(card(id).classList.contains('is-executing')).toBe(false);
  expect(card(id).querySelector('.exec-ring')).toBeNull();
  expect(card(id).textContent).not.toContain('执行中');
 }
 expect(card('04').textContent).toContain('running · 现场 Unknown');

 const mmfEl=box.querySelector<HTMLElement>('.graph-mmf')!;
 expect(mmfEl.classList.contains('is-executing')).toBe(false);
 expect(mmfEl.querySelector('.exec-ring')).toBeNull();
 expect(mmfEl.textContent).not.toContain('执行中');
});

test('S16 换快照重渲染后 A 虚线环消失并显示待收口，B 出现虚线环',()=>{
 const mmf1=makeMmf([
  makeTicket('A',{executing:true,lane:makeLane({lane_id:'a',state:'running',group:'active',live:'working'})}),
  makeTicket('B',{executing:false,lane:makeLane({lane_id:'b',state:'created',group:'active',live:'unknown'})}),
 ]);
 const box=doc.createElement('div');
 box.innerHTML=renderGraph({id:'repo|E1',label:'E1',url:null,mmfs:[mmf1]},mmf1,mmf1.tickets[0]);
 expect(box.querySelector('[data-ticket="A"] .exec-ring')).not.toBeNull();
 expect(box.querySelector('[data-ticket="A"]')!.textContent).toContain('执行中');
 expect(box.querySelector('[data-ticket="B"] .exec-ring')).toBeNull();

 const mmf2=makeMmf([
  makeTicket('A',{executing:false,lane:makeLane({lane_id:'a',state:'terminal',group:'review',live:'unknown'})}),
  makeTicket('B',{executing:true,lane:makeLane({lane_id:'b',state:'running',group:'active',live:'working'})}),
 ]);
 box.innerHTML=renderGraph({id:'repo|E1',label:'E1',url:null,mmfs:[mmf2]},mmf2,mmf2.tickets[0]);
 expect(box.querySelector('[data-ticket="A"] .exec-ring')).toBeNull();
 expect(box.querySelector('[data-ticket="A"]')!.classList.contains('is-executing')).toBe(false);
 expect(box.querySelector('[data-ticket="A"]')!.textContent).toContain('待收口');
 expect(box.querySelector('[data-ticket="B"] .exec-ring')).not.toBeNull();
 expect(box.querySelector('[data-ticket="B"]')!.classList.contains('is-executing')).toBe(true);
 expect(box.querySelector('[data-ticket="B"]')!.textContent).toContain('执行中');
});

test('S17 prefers-reduced-motion: reduce 时虚线环静止无动画，虚线样式与“执行中”文字保留',()=>{
 const mmf=makeMmf([makeTicket('01',{executing:true,lane:makeLane({state:'running',group:'active',live:'working'})})]);
 const box=doc.createElement('div');
 box.innerHTML=renderGraph({id:'repo|E1',label:'E1',url:null,mmfs:[mmf]},mmf,mmf.tickets[0]);
 const ringPath=box.querySelector('.exec-ring-path')!;
 expect(ringPath).not.toBeNull();
 expect(box.querySelector('[data-ticket="01"]')!.textContent).toContain('执行中');

 let baseRule:CSSStyleRule|undefined;
 let reducedRule:CSSStyleRule|undefined;
 for(const rule of sheet.cssRules){
  if(rule.type===1){
   const r=rule as CSSStyleRule;
   if(r.selectorText==='.exec-ring-path')baseRule=r;
  }else if(rule.type===4){
   const m=rule as CSSMediaRule;
   const cond=(m.conditionText||m.media?.mediaText||'').replace(/\s+/g,'');
   if(cond.includes('prefers-reduced-motion:reduce')){
    for(const sub of m.cssRules){
     const sr=sub as CSSStyleRule;
     if(sr.selectorText==='.exec-ring-path')reducedRule=sr;
    }
   }
  }
 }
 expect(baseRule).toBeDefined();
 expect(baseRule!.style.getPropertyValue('stroke-dasharray')).toBeTruthy();
 expect(baseRule!.style.getPropertyValue('animation')).toContain('exec-dash');
 expect(reducedRule).toBeDefined();
 expect(reducedRule!.style.getPropertyValue('animation')).toBe('none');
});

test('S18 4 层超宽图视口滚动目标：初始可见根与第 1 层，点第 4 层票后滚动到该票',()=>{
 const mmf=sample.repos[0]!.epics[0]!.mmfs[0]!;
 const box=doc.createElement('div');
 box.innerHTML=renderGraph({id:'example/dispatch|DEMO-1',label:'DEMO-1',url:null,mmfs:[mmf]},mmf,mmf.tickets[0]);
 const graphWidth=parseFloat(box.querySelector<HTMLElement>('.graph')!.style.width);
 const viewportWidth=600;
 expect(graphWidth).toBeGreaterThan(viewportWidth);

 const rootX=Number(box.querySelector<HTMLElement>('.graph-root')!.dataset.x);
 const mmfX=Number(box.querySelector<HTMLElement>('.graph-mmf')!.dataset.x);
 expect(rootX).toBe(0);
 expect(mmfX+GRAPH_GEOMETRY.card).toBeLessThan(viewportWidth);

 const layer4Card=box.querySelector<HTMLElement>('.graph-ticket[data-ticket="10"]')!;
 const x=Number(layer4Card.dataset.x),y=Number(layer4Card.dataset.y);
 expect(x+GRAPH_GEOMETRY.card).toBeGreaterThan(viewportWidth);

 const target=scrollTargetForNode(
  {scrollLeft:0,scrollTop:0,clientWidth:viewportWidth,clientHeight:400,scrollWidth:graphWidth,scrollHeight:400},
  {x,y,width:GRAPH_GEOMETRY.card,height:GRAPH_GEOMETRY.h}
 );
 expect(target.scrollLeft).toBeGreaterThan(0);
 expect(x).toBeGreaterThanOrEqual(target.scrollLeft);
 expect(x+GRAPH_GEOMETRY.card).toBeLessThanOrEqual(target.scrollLeft+viewportWidth);
});

test('DD-668 视觉对齐与溢出反例：长中英文混排标题与 80 字符无空格标识符不挤出状态行，完整标题由 title 可读，EP 深色根与 MMF 横带存在',()=>{
 const longMixedTitle='生产只读带 ANALYZE 补测素材 1/7 日基线、表规模与方案 A 计划形状（已完成，JB-459 超长中英文混排标题）';
 const longId='lane_delivery_pipeline_dd668_unbroken_identifier_without_any_spaces_0123456789abcdef';
 const t1=makeTicket('01',{title:longMixedTitle,executing:false,lane:makeLane({state:'integrated',group:'done',live:'unknown'})});
 const t2=makeTicket('02',{title:longId,deps:['01'],executing:false,lane:makeLane({state:'blocked',group:'problem',live:'unknown'})});
 const mmf=makeMmf([t1,t2],{map:longId,title:longMixedTitle});
 const box=doc.createElement('div');
 box.innerHTML=renderGraph({id:'repo|EP-101',label:'EP-101',url:null,mmfs:[mmf]},mmf,t1);

 // MMF 横带与实体卡片存在
 expect(box.querySelectorAll('.graph-band').length).toBe(1);
 const mmfEl=box.querySelector<HTMLElement>('.graph-mmf')!;
 expect(mmfEl.getAttribute('title')).toContain(longMixedTitle);

 // 卡片内标题与状态行分离渲染，完整标题在 title 属性可读
 const card1=box.querySelector<HTMLElement>('.graph-ticket[data-ticket="01"]')!;
 const card2=box.querySelector<HTMLElement>('.graph-ticket[data-ticket="02"]')!;
 expect(card1.getAttribute('title')).toContain(longMixedTitle);
 expect(card1.querySelector('.tk-t')!.textContent).toBe(longMixedTitle);
 expect(card1.querySelector('.tk-st')!.textContent).toContain('已完成');
 expect(card2.getAttribute('title')).toContain(longId);
 expect(card2.querySelector('.tk-t')!.textContent).toBe(longId);
 expect(card2.querySelector('.tk-st')!.textContent).toContain('blocked');

 // 样式规则：标题单行省略，EP 根使用深色 var(--ink) 背景
 const rules=[...sheet.cssRules].filter((r):r is CSSStyleRule=>r.type===1);
 const tkTRule=rules.find(r=>r.selectorText?.split(',').some(s=>s.trim()==='.tk-t'));
 expect(tkTRule).toBeDefined();
 expect(tkTRule!.style.getPropertyValue('white-space')).toBe('nowrap');
 expect(tkTRule!.style.getPropertyValue('text-overflow')).toBe('ellipsis');
 expect(tkTRule!.style.getPropertyValue('overflow')).toBe('hidden');
 const rootRules=rules.filter(r=>r.selectorText?.split(',').some(s=>s.trim()==='.graph-root'));
 expect(rootRules.some(r=>(r.style.getPropertyValue('background')||r.style.getPropertyValue('background-color')).includes('var(--ink)'))).toBe(true);
});
