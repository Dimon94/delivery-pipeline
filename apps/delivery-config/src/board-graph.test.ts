import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {readFileSync} from 'node:fs';
import type {BoardSnapshot,Lane,Mmf,Ticket} from './board';
import {GRAPH_GEOMETRY,applyHoverChain,dependencyChain,missingMmfEdges,renderGraph,scrollTargetForNode,ticketLayers,type GraphGroup} from './board-graph';
import {buildBoardGroups} from './board-side';

const sample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board.json',import.meta.url),'utf8')) as BoardSnapshot;
const probedSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/probed.json',import.meta.url),'utf8')) as BoardSnapshot;
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
 expect(mmfX+GRAPH_GEOMETRY.mmfW).toBeLessThan(viewportWidth);

 const layer4Card=box.querySelector<HTMLElement>('.graph-ticket[data-ticket="10"]')!;
 const x=Number(layer4Card.dataset.x),y=Number(layer4Card.dataset.y);
 expect(x+GRAPH_GEOMETRY.ticketW).toBeGreaterThan(viewportWidth);

 const target=scrollTargetForNode(
  {scrollLeft:0,scrollTop:0,clientWidth:viewportWidth,clientHeight:400,scrollWidth:graphWidth,scrollHeight:400},
  {x,y,width:GRAPH_GEOMETRY.ticketW,height:GRAPH_GEOMETRY.ticketH}
 );
 expect(target.scrollLeft).toBeGreaterThan(0);
 expect(x).toBeGreaterThanOrEqual(target.scrollLeft);
 expect(x+GRAPH_GEOMETRY.ticketW).toBeLessThanOrEqual(target.scrollLeft+viewportWidth);
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

test('DD-668 visual-fix-2 项2-5：GRAPH_GEOMETRY 分离票卡 150×45.48、MMF 卡 170×85.39、EP 根 150×75.69 及全部间距，4行带高对齐 221.94 且连线端点随几何更新',()=>{
 const G=GRAPH_GEOMETRY as Record<string,number>;
 expect(G.ticketW).toBe(150);
 expect(G.ticketH).toBeCloseTo(45.48,2);
 expect(G.mmfW).toBe(170);
 expect(G.mmfH).toBeCloseTo(85.39,2);
 expect(G.root).toBe(150);
 expect(G.rootH).toBeCloseTo(75.69,2);
 expect(G.gx).toBe(34);
 expect(G.gy).toBe(8);
 expect(G.rootGap).toBe(56);
 expect(G.mmfGap).toBe(44);
 expect(G.pad).toBe(8);
 expect(G.band).toBe(14);

 // 构造同列 4 张票的 M3 形状（第 1 列 1 票，第 2 列 4 票）
 const t1=makeTicket('T1');
 const t4=makeTicket('T4',{deps:['T1']});
 const t6=makeTicket('T6',{deps:['T1']});
 const t7=makeTicket('T7',{deps:['T1']});
 const t8=makeTicket('T8',{deps:['T1']});
 const mmf=makeMmf([t1,t4,t6,t7,t8],{map:'ep-101-m3',title:'投放执行与重试'});
 const box=doc.createElement('div');
 box.innerHTML=renderGraph({id:'repo|EP-101',label:'EP-101',url:null,mmfs:[mmf]},mmf,t7);

 const band=box.querySelector<HTMLElement>('.graph-band')!;
 expect(parseFloat(band.style.left)).toBe(206); // 150 + 56
 expect(parseFloat(band.style.height)).toBeCloseTo(221.94,1);

 const mmfEl=box.querySelector<HTMLElement>('.graph-mmf')!;
 expect(Number(mmfEl.dataset.x)).toBe(214); // 206 + 8

 const card1=box.querySelector<HTMLElement>('.graph-ticket[data-ticket="T1"]')!;
 const card7=box.querySelector<HTMLElement>('.graph-ticket[data-ticket="T7"]')!;
 expect(Number(card1.dataset.x)).toBe(428); // 214 + 170 + 44
 expect(Number(card7.dataset.x)).toBe(612); // 428 + 150 + 34

 // 验证连线端点对齐新几何
 const depPath=box.querySelector('path[data-dep="T1>T7"]')!;
 const nums=depPath.getAttribute('d')!.match(/-?\d+(\.\d+)?/g)!.map(Number);
 expect(nums[0]).toBe(Number(card1.dataset.x)+150);
 expect(nums[1]).toBeCloseTo(Number(card1.dataset.y)+G.ticketH!/2,2);
 expect(nums[nums.length-2]).toBe(Number(card7.dataset.x));
 expect(nums[nums.length-1]).toBeCloseTo(Number(card7.dataset.y)+G.ticketH!/2,2);
});

test('DD-668 visual-fix-2 项6-8：横带白 50% 无描边圆角 12；票卡字体与行高、padding 5×8、行间 2、标题行 gap 6 匹配原型',()=>{
 const rules=[...sheet.cssRules].filter((r):r is CSSStyleRule=>r.type===1);
 const findProp=(selector:string,prop:string)=>{
  let val='';
  for(const r of rules){
   if(r.selectorText?.split(',').some(s=>s.trim()===selector)){
    const v=r.style.getPropertyValue(prop);
    if(v)val=v.trim();
   }
  }
  return val;
 };

 // 项 6：横带底白 50%、无描边、圆角 12
 const bandCss=cssText.match(/\.graph-band\{[^}]+\}/)?.[0]??'';
 expect(bandCss).toContain('color-mix(in srgb,var(--card) 50%,transparent)');
 expect(findProp('.graph-band','border-radius')).toBe('12px');
 expect(bandCss).toContain('border:0');

 // 项 2/3/4：卡片尺寸样式
 expect(findProp('.graph-ticket','width')).toBe('150px');
 expect(findProp('.graph-mmf','width')).toBe('170px');
 expect(findProp('.graph-root','width')).toBe('150px');

 // 项 7：票卡字体与行高（12/16.8 400、10.5/14.7 400、10.5/14.7 600）
 expect(findProp('.graph-ticket','line-height')).toBe('1.4');
 expect(findProp('.tk-t','font-size')).toBe('12px');
 expect(findProp('.tk-id','font-size')).toBe('10.5px');
 expect(findProp('.tk-id','font-weight')).toBe('400');
 expect(findProp('.tk-st','font-size')).toBe('10.5px');
 expect(findProp('.tk-st','line-height')).toBe('1.4');

 // 项 8：padding 5×8、行间 2、标题行 gap 6
 expect(findProp('.graph-ticket','padding')).toBe('5px 8px');
 expect(findProp('.graph-ticket','gap')).toBe('2px');
 expect(findProp('.tk-row','gap')).toBe('6px');
});

test('DD-668 visual-fix-2 项9：MMF 快照 halt 非空且命中该票时卡片标题行显示红底白字 Halt 徽标，未命中或无 halt 不显示',()=>{
 const haltReason='needs-decision：重试上限由谁定未写进 Spec';
 const t5=makeTicket('T5',{lane:makeLane({lane_id:'ep-101-m3-t5',state:'terminal',group:'review'})});
 const t6=makeTicket('T6',{deps:['T5'],lane:makeLane({lane_id:'ep-101-m3-t6',state:'running',group:'active',blocked_reason:'registry 写着 running，但本机找不到匹配的活 agent'})});
 const t7=makeTicket('T7',{deps:['T5'],lane:makeLane({lane_id:'ep-101-m3-t7',state:'blocked',group:'problem',blocked_reason:haltReason})});
 const mmfHalted=makeMmf([t5,t6,t7],{
  map:'ep-101-m3',
  halt:{id:'halt-t7',kind:'plan_change',label:'计划变更',reason:haltReason,options:['补充 Spec']},
 });
 const tOther=makeTicket('T1',{lane:makeLane({lane_id:'ep-101-m4-t1',state:'blocked',group:'problem',blocked_reason:'普通阻塞无 halt'})});
 const mmfNoHalt=makeMmf([tOther],{map:'ep-101-m4',halt:null});

 const box=doc.createElement('div');
 box.innerHTML=renderGraph({id:'repo|EP-101',label:'EP-101',url:null,mmfs:[mmfHalted,mmfNoHalt]},mmfHalted,t7);

 const t7Badge=box.querySelector('.graph-ticket[data-map="ep-101-m3"][data-ticket="T7"] .tk-row .tk-h');
 expect(t7Badge).not.toBeNull();
 expect(t7Badge!.textContent).toBe('Halt');

 expect(box.querySelector('.graph-ticket[data-map="ep-101-m3"][data-ticket="T5"] .tk-h')).toBeNull();
 expect(box.querySelector('.graph-ticket[data-map="ep-101-m3"][data-ticket="T6"] .tk-h')).toBeNull();
 expect(box.querySelector('.graph-ticket[data-map="ep-101-m4"][data-ticket="T1"] .tk-h')).toBeNull();

 const rules=[...sheet.cssRules].filter((r):r is CSSStyleRule=>r.type===1);
 const tkHRule=rules.find(r=>r.selectorText?.split(',').some(s=>s.trim()==='.tk-h'));
 expect(tkHRule).toBeDefined();
 expect(tkHRule!.style.getPropertyValue('font-size')).toBe('10px');
 expect(tkHRule!.style.getPropertyValue('border-radius')).toBe('4px');
 expect(tkHRule!.style.getPropertyValue('background')||tkHRule!.style.getPropertyValue('background-color')).toContain('var(--red)');
 expect(tkHRule!.style.getPropertyValue('color')).toMatch(/#fff|rgb\(255,\s*255,\s*255\)/i);
});

test('S2 M1 样本渲染不含候选卡、跨 MMF 边与 Linear 状态标签',()=>{
 for(const snap of [sample,probedSample]){
  const groups=buildBoardGroups(snap);
  for(const group of groups.all){
   const box=doc.createElement('div');
   box.innerHTML=renderGraph(group,group.mmfs[0],group.mmfs[0]?.tickets[0]);
   expect(box.querySelector('.tk-linear-status')).toBeNull();
   expect(box.querySelector('[data-candidate]')).toBeNull();
   expect(box.querySelector('[data-mmf-edge]')).toBeNull();
  }
 }
});

test('S6 票 01 显示 Linear 标题与状态，票 02 无 key、票 03 缓存无记录的状态标签均为 Unknown',()=>{
 const t01=makeTicket('01',{
  title:'本地 01',
  stage:'implement',
  linear:'https://linear.app/demo/issue/DEMO-101',
  linear_issue:{title:'Linear 票 01',status:'In Review'},
 });
 const t02=makeTicket('02',{title:'本地 02',deps:['01'],stage:'implement',linear:null});
 const t03=makeTicket('03',{title:'本地 03',deps:['02'],stage:'implement',linear:'https://linear.app/demo/issue/DEMO-103'});
 const mmf=makeMmf([t01,t02,t03]);
 const group:GraphGroup={id:'demo|DEMO-E',label:'DEMO-E · Epic E 标题',url:null,mmfs:[mmf],linearStatus:'In Progress',hasLinear:true};
 const box=doc.createElement('div');
 box.innerHTML=renderGraph(group,mmf,t01);

 const card=(id:string)=>box.querySelector<HTMLElement>(`.graph-ticket[data-ticket="${id}"]`)!;
 expect(card('01').querySelector('.tk-t')!.textContent).toBe('Linear 票 01');
 expect(card('01').querySelector('.tk-linear-status')!.textContent).toBe('In Review');
 expect(card('02').querySelector('.tk-t')!.textContent).toBe('本地 02');
 expect(card('02').querySelector('.tk-linear-status')!.textContent).toBe('Unknown');
 expect(card('03').querySelector('.tk-t')!.textContent).toBe('本地 03');
 expect(card('03').querySelector('.tk-linear-status')!.textContent).toBe('Unknown');
 expect(box.querySelector('.graph-root')!.textContent).toBe('DEMO-E · Epic E 标题');
 expect(box.querySelector('.graph-root')!.getAttribute('data-meta')).toContain('In Progress');
});

test('S3/S4 候选卡以虚线框未开工出现在 MMF 列，有 Spec 显示标识与状态、无 Spec 标尚无 Spec，Unknown 候选不计入 Epic 的 MMF 数',()=>{
 const linearSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board-linear.json',import.meta.url),'utf8')) as BoardSnapshot;
 const group=buildBoardGroups(linearSample).repos[0]!.epics[0]!.group;
 const box=doc.createElement('div');
 box.innerHTML=renderGraph(group,group.mmfs[0],undefined,false,group.candidates![1]);

 const cards=[...box.querySelectorAll<HTMLElement>('.graph-candidate[data-candidate]')];
 expect(cards.length).toBe(3);
 // 位于 MMF 同一列（x 与本地 MMF 相同）且为虚线框未开工
 const mmfX=Number(box.querySelector<HTMLElement>('.graph-mmf[data-map="demo-m1"]')!.dataset.x);
 for(const c of cards){
  expect(Number(c.dataset.x)).toBe(mmfX);
  expect(c.style.borderStyle).toBe('dashed');
  expect(c.textContent).toContain('未开工');
 }

 // M2 有 Spec：显示 Spec 标识和 Linear 状态
 const m2=box.querySelector<HTMLElement>('.graph-candidate[data-candidate="M2"]')!;
 expect(m2.querySelector('.mmf-key')!.textContent).toBe('M2');
 expect(m2.querySelector('.cand-spec-key')!.textContent).toBe('DEMO-3');
 expect(m2.querySelector('.cand-spec-status')!.textContent).toBe('Todo');

 // M3 无 Spec 且当前选中
 const m3=box.querySelector<HTMLElement>('.graph-candidate[data-candidate="M3"]')!;
 expect(m3.classList.contains('selected')).toBe(true);
 expect(m3.querySelector('.cand-spec-key')).toBeNull();
 expect(m3.textContent).toContain('尚无 Spec');

 // Unknown 候选出现，但不计入 Epic 根节点的 MMF 数（1 本地 + M2 + M3 = 3 MMF）
 const unk=box.querySelector<HTMLElement>('.graph-candidate[data-mmf-id="Unknown"]')!;
 expect(unk.dataset.candidateSource).toBe('linear_child');
 expect(unk.querySelector('.cand-spec-key')!.textContent).toBe('DEMO-4');
 expect(box.querySelector('.graph-root')!.getAttribute('data-meta')).toContain('3 MMF');
});

test('S13（R5）跨 MMF 边按类型画出；悬停 M2 卡片时 M1→M2 边与两端高亮并显示“开工”与依赖原文；端点缺失的边不画由 missingMmfEdges 返回',()=>{
 const linearSample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board-linear.json',import.meta.url),'utf8')) as BoardSnapshot;
 const group=buildBoardGroups(linearSample).repos[0]!.epics[0]!.group;
 // 追加一条端点 M9 缺失的边，验证图上不画、missingMmfEdges 返回
 const groupWithMissing:GraphGroup={
  ...group,
  mmfEdges:[
   {from:'M1',to:'M2',kind:'开工',text:'开工 · 依赖 M1 定下的快照 JSON 结构'},
   {from:'M1',to:'M3',kind:'Unknown',text:'M1，可与 M2 并行'},
   {from:'M1',to:'M9',kind:'上线',text:'上线依赖 M1'},
  ],
 };
 const box=doc.createElement('div');
 box.innerHTML=renderGraph(groupWithMissing,groupWithMissing.mmfs[0],undefined,false);

 const drawnEdges=[...box.querySelectorAll('path[data-mmf-edge]')].map(p=>p.getAttribute('data-mmf-edge'));
 expect(drawnEdges).toEqual(['M1>M2','M1>M3']);
 expect(box.querySelector('path[data-mmf-edge="M2>M3"]')).toBeNull();
 expect(box.querySelector('path[data-mmf-edge="M1>M9"]')).toBeNull();
 expect(missingMmfEdges(groupWithMissing)).toEqual([
  {from:'M1',to:'M9',kind:'上线',text:'上线依赖 M1'},
 ]);

 // 悬停 M2 卡片：M1→M2 边、标签、M1 与 M2 卡片保持高亮；M1→M3 与 M3 淡出
 applyHoverChain(box,groupWithMissing,{candidate:'M2'});
 expect(box.querySelector('.graph')!.classList.contains('has-hover')).toBe(true);
 const edgePath=box.querySelector('path[data-mmf-edge="M1>M2"]')!;
 const edgeLabel=box.querySelector<HTMLElement>('.mmf-edge-label[data-mmf-edge-label="M1>M2"]')!;
 expect(edgePath.classList.contains('chain')).toBe(true);
 expect(edgeLabel.classList.contains('chain')).toBe(true);
 expect(edgeLabel.querySelector('.mmf-edge-kind')!.textContent).toBe('开工');
 expect(edgeLabel.querySelector('.mmf-edge-text')!.textContent).toBe('开工 · 依赖 M1 定下的快照 JSON 结构');

 expect(box.querySelector('.graph-mmf[data-mmf-id="M1"]')!.classList.contains('chain')).toBe(true);
 expect(box.querySelector('.graph-candidate[data-candidate="M2"]')!.classList.contains('chain')).toBe(true);
 expect(box.querySelector('.graph-candidate[data-candidate="M3"]')!.classList.contains('dimmed')).toBe(true);
 expect(box.querySelector('path[data-mmf-edge="M1>M3"]')!.classList.contains('dimmed')).toBe(true);

 // 离开后恢复
 applyHoverChain(box,groupWithMissing,undefined);
 expect(box.querySelector('.graph')!.classList.contains('has-hover')).toBe(false);
 expect(box.querySelectorAll('.chain,.dimmed').length).toBe(0);
});
