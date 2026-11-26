import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {readFileSync} from 'fs';

// 经真实入口 main.ts 启动；外部边界只有 Host（mygo.call）。
const sample=JSON.parse(readFileSync(new URL('../../../skills/delivery-pipeline/scripts/board_samples/board.json',import.meta.url),'utf8'));
const config={version:7,work:Object.fromEntries(['planning','design','frontend','backend','testing','research','coordinator'].map(n=>[n,{agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high',fallbacks:[]}])),review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(a=>[a,{agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high',candidates:[]}]))])),modes:{}};
let boardCalls=0;
let answer:()=>Promise<unknown>=()=>Promise.resolve(sample);
let release:()=>void=()=>{};
const win=new Window({width:1440,height:900}),doc=win.document;
Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call:async(name:string)=>{
 if(name==='Host.ReadBoard'){boardCalls++;return answer();}
 if(name==='Host.AppInfo')return {config_path:'/tmp/dd672/model-roles.json'};
 if(name==='Host.ReadConfig')return {file_state:'ready',config,base_hash:'hash',cells:{}};
 throw Error(name);
}}});
// 第一次读取挂起，好看到“读取中”。
answer=()=>new Promise(r=>{release=()=>r(sample);});
doc.body.innerHTML='<div id="app"></div>';
await import('./main?dd672');
const settle=()=>new Promise(r=>setTimeout(r,20));
const q=<T extends Element=HTMLElement>(s:string)=>doc.querySelector<T>(s as never) as T|null;
const board=()=>q('#board-view')!;
const settings=()=>q('#settings-view')!;
const click=(el:Element|null)=>{expect(el).not.toBeNull();(el as HTMLElement).click();};
const button=(text:string)=>[...board().querySelectorAll('button')].find(b=>b.textContent===text)??null;

test('S8 启动先显示读取中，随后三栏：左栏按仓库列 Epic，中栏 Epic→MMF→票，右栏第一张票',async()=>{
 expect(board().hidden).toBe(false);
 expect(settings().hidden).toBe(true);
 expect(board().textContent).toContain('读取中');
 answer=()=>Promise.resolve(sample);release();await settle();
 const left=q('#board-left')!;
 expect(left.textContent).toContain('example/dispatch');
 expect(left.textContent).toContain('DEMO-1');
 expect(left.textContent).toContain('DEMO-3');
 const center=q('.board-center')!;
 expect(center.querySelector('.graph-root')!.textContent).toBe('DEMO-1');
 const first=sample.repos[0].epics[0].mmfs[0];
 expect(center.querySelector('.graph-mmf')!.textContent).toContain(first.title);
 expect(center.querySelectorAll('.graph-ticket').length).toBe(first.tickets.length);
 expect(q('#board-right')!.querySelector('h2')!.textContent).toBe(first.tickets[0].id);
 expect(q('#board-right')!.textContent).toContain(first.tickets[0].title);
});

test('S8 设置进原配置页，返回看板保留选择',async()=>{
 const pickId=sample.repos[0].epics[0].mmfs[0].tickets[2].id;
 click(q(`[data-ticket="${pickId}"]`));
 click(button('设置'));
 expect(board().hidden).toBe(true);
 expect(settings().hidden).toBe(false);
 expect(settings().querySelector('h1')!.textContent).toBe('模型设置');
 expect(settings().querySelector('#refresh')).not.toBeNull();
 const before=boardCalls;
 click(q('#btn-back-board'));await settle();
 expect(boardCalls).toBe(before+1);
 expect(board().hidden).toBe(false);
 expect(settings().hidden).toBe(true);
 expect(q('#board-right')!.querySelector('h2')!.textContent).toBe(pickId);
 expect(q(`[data-ticket="${pickId}"]`)!.classList.contains('selected')).toBe(true);
});

test('S9 读取超时显示读取失败与原因；重试回到读取中；失败态回前台重读',async()=>{
 const reason='看板读取超时（5 秒）';
 answer=()=>Promise.reject(Error(reason));
 window.dispatchEvent(new win.Event('focus'));await settle();
 expect(q('.board-failed')!.textContent).toContain('读取失败');
 expect(q('.board-reason')!.textContent).toBe(reason);
 answer=()=>new Promise(r=>{release=()=>r(sample);});
 click(button('重试'));
 expect(board().textContent).toContain('读取中');
 expect(q('.board-failed')).toBeNull();
 answer=()=>Promise.reject(Error(reason));release();await settle();
 expect(q('.board-grid')).not.toBeNull();
 window.dispatchEvent(new win.Event('focus'));await settle();
 expect(q('.board-reason')!.textContent).toBe(reason);
 answer=()=>Promise.resolve(sample);
 const before=boardCalls;
 window.dispatchEvent(new win.Event('focus'));await settle();
 expect(boardCalls).toBe(before+1);
 expect(q('.board-failed')).toBeNull();
 expect(q('.board-grid')).not.toBeNull();
});

// 栏宽来自样式表：按 data-left/data-right 取 grid-template-columns，中栏是 minmax(0,1fr) 那一列。
const sheet=new win.CSSStyleSheet();sheet.replaceSync(readFileSync(new URL('./style.css',import.meta.url),'utf8'));
function columns(grid:Element):string {
 let best='',score=-1;
 for(const rule of sheet.cssRules){const r=rule as CSSStyleRule;
  if(!r.selectorText||!r.style.getPropertyValue('grid-template-columns'))continue;
  if(!grid.matches(r.selectorText))continue;
  const s=(r.selectorText.match(/\[|\./g)||[]).length;
  if(s>=score){score=s;best=r.style.getPropertyValue('grid-template-columns');}
 }
 return best.replace(/\s+/g,' ');
}
// 每条依赖连线的两端落在对应卡片的边上。
function linksAligned() {
 const cards=new Map([...doc.querySelectorAll<HTMLElement>('.graph-ticket')].map(c=>[`${c.dataset.map}/${c.dataset.ticket}`,{x:Number(c.dataset.x),y:Number(c.dataset.y)}]));
 const paths=[...doc.querySelectorAll('path[data-dep]')];
 expect(paths.length).toBeGreaterThan(0);
 for(const p of paths){
  const [from,to]=p.getAttribute('data-dep')!.split('>');
  const map=p.getAttribute('data-map');
  const a=cards.get(`${map}/${from}`)!,b=cards.get(`${map}/${to}`)!;
  const nums=p.getAttribute('d')!.match(/-?\d+(\.\d+)?/g)!.map(Number);
  expect([nums[0],nums[1]]).toEqual([a.x+176,a.y+28]);
  expect(nums.slice(-2)).toEqual([b.x,b.y+28]);
 }
}

test('S22 1440 宽：收起左栏中栏变宽；收起右栏中栏占满、选择保持、连线对齐；右栏收起时点票自动展开；展开左栏复原',()=>{
 expect(win.innerWidth).toBe(1440);
 const grid=()=>q('.board-grid')!;
 const selected=q('#board-right h2')!.textContent;
 expect(columns(grid())).toBe('240px minmax(0,1fr) 320px');
 click(button('收起左栏'));
 expect(q('#board-left')!.hidden).toBe(true);
 expect(columns(grid())).toBe('minmax(0,1fr) 320px');
 click(button('收起右栏'));
 expect(q('#board-right')!.hidden).toBe(true);
 expect(columns(grid())).toBe('minmax(0,1fr)');
 expect(q('.graph-ticket.selected')!.dataset.ticket).toBe(selected!);
 linksAligned();
 const other=[...doc.querySelectorAll<HTMLElement>('.graph-ticket')].find(c=>c.dataset.ticket!==selected)!;
 const id=other.dataset.ticket!;
 click(other);
 expect(q('#board-right')!.hidden).toBe(false);
 expect(q('#board-right h2')!.textContent).toBe(id);
 expect(columns(grid())).toBe('minmax(0,1fr) 320px');
 click(button('展开左栏'));
 expect(q('#board-left')!.hidden).toBe(false);
 expect(columns(grid())).toBe('240px minmax(0,1fr) 320px');
 expect(q('.graph-ticket.selected')!.dataset.ticket).toBe(id);
 linksAligned();
});

test('S11 悬停 4 层 MMF 中的票只高亮上下游链，点 MMF 与点票切换中栏选中态',async()=>{
 answer=()=>Promise.resolve(sample);
 window.dispatchEvent(new win.Event('focus'));await settle();

 const ticket05=q<HTMLElement>('.graph-ticket[data-ticket="05"]')!;
 ticket05.dispatchEvent(new win.MouseEvent('mouseover',{bubbles:true}));
 expect(q('.graph')!.classList.contains('has-hover')).toBe(true);
 expect([...doc.querySelectorAll<HTMLElement>('.graph-ticket.chain')].map(el=>el.dataset.ticket).sort()).toEqual(['02','05','07','08','10','11','12']);
 expect([...doc.querySelectorAll<HTMLElement>('.graph-ticket.dimmed')].map(el=>el.dataset.ticket).sort()).toEqual(['01','03','04','06','09']);

 ticket05.dispatchEvent(new win.MouseEvent('mouseout',{bubbles:true,relatedTarget:q('.board-center')}));
 expect(q('.graph')!.classList.contains('has-hover')).toBe(false);
 expect(doc.querySelectorAll('.graph-ticket.dimmed').length).toBe(0);

 click(q('.graph-mmf'));
 expect(q('.graph-mmf')!.classList.contains('selected')).toBe(true);
 expect(q('.graph-ticket.selected')).toBeNull();

 click(q('.graph-ticket[data-ticket="07"]'));
 expect(q('.graph-mmf')!.classList.contains('selected')).toBe(false);
 expect(q('.graph-ticket.selected')!.dataset.ticket).toBe('07');
});

test('S16 通过重新读取快照切换执行中动画：A 停止并显示待收口，B 出现虚线环',async()=>{
 const baseLane={role:'backend',agent:'pi',model:'gpt-6.1-sol',worktree:null,branch:null,blocked_reason:null,updated_at:'2026-01-15T12:00:00+00:00'};
 const snap=(a:{state:string;group:string;live:string;executing:boolean},b:{state:string;group:string;live:string;executing:boolean})=>({
  schema:1,generated_at:'2026-01-15T12:00:00+00:00',lanes_root:'/fixture/lanes',
  repos:[{name:'example/dispatch',epics:[{key:'DEMO-1',url:null,title:'Unknown',ended:false,mmfs:[{
   map:'dispatch-rules',title:'交付规则',stage:'implement',halt:null,links:{plan_review:null,merge_review:null,linear:null},
   updated_at:'2026-01-15T12:00:00+00:00',direct_lanes:[],executing:false,
   tickets:[
    {id:'A',title:'票 A',deps:[],stage:'implement',lane:{...baseLane,lane_id:'a',state:a.state,group:a.group,live:a.live},executing:a.executing,linear:null},
    {id:'B',title:'票 B',deps:['A'],stage:'implement',lane:{...baseLane,lane_id:'b',state:b.state,group:b.group,live:b.live},executing:b.executing,linear:null},
   ],
  }]}]}],inbox:[],probes:[],errors:[],
 });
 answer=()=>Promise.resolve(snap({state:'running',group:'active',live:'working',executing:true},{state:'created',group:'active',live:'unknown',executing:false}));
 window.dispatchEvent(new win.Event('focus'));await settle();
 expect(q('[data-ticket="A"] .exec-ring')).not.toBeNull();
 expect(q('[data-ticket="A"]')!.textContent).toContain('执行中');
 expect(q('[data-ticket="B"] .exec-ring')).toBeNull();

 answer=()=>Promise.resolve(snap({state:'terminal',group:'review',live:'unknown',executing:false},{state:'running',group:'active',live:'working',executing:true}));
 window.dispatchEvent(new win.Event('focus'));await settle();
 expect(q('[data-ticket="A"] .exec-ring')).toBeNull();
 expect(q('[data-ticket="A"]')!.textContent).toContain('待收口');
 expect(q('[data-ticket="B"] .exec-ring')).not.toBeNull();
 expect(q('[data-ticket="B"]')!.textContent).toContain('执行中');
});

test('S18 4 层超宽图首次打开与切 Epic 可见根与第一层 MMF，点第 4 层票后滚动到该票',async()=>{
 answer=()=>Promise.resolve(sample);
 window.dispatchEvent(new win.Event('focus'));await settle();

 const center=q<HTMLElement>('.board-center')!;
 Object.defineProperty(center,'clientWidth',{value:600,configurable:true});
 Object.defineProperty(center,'clientHeight',{value:500,configurable:true});

 expect(center.scrollLeft).toBe(0);
 const graphW=parseFloat(q<HTMLElement>('.graph')!.style.width);
 expect(graphW).toBeGreaterThan(600);
 expect(Number(q<HTMLElement>('.graph-root')!.dataset.x)).toBe(0);
 expect(Number(q<HTMLElement>('.graph-mmf')!.dataset.x)+176).toBeLessThan(600);

 // 点第 4 层票（10），视口滚动到该票可见
 click(q<HTMLElement>('.graph-ticket[data-ticket="10"]'));
 const afterClickCenter=q<HTMLElement>('.board-center')!;
 const card10=q<HTMLElement>('.graph-ticket[data-ticket="10"]')!;
 const x10=Number(card10.dataset.x);
 expect(afterClickCenter.scrollLeft).toBeGreaterThan(0);
 expect(x10).toBeGreaterThanOrEqual(afterClickCenter.scrollLeft);
 expect(x10+176).toBeLessThanOrEqual(afterClickCenter.scrollLeft+600);

 // 切到另一个 Epic（DEMO-3），视口回到根与第一层 MMF
 const otherEpic=[...doc.querySelectorAll<HTMLElement>('.board-entry')].find(b=>b.dataset.group?.includes('DEMO-3'))!;
 click(otherEpic);
 const afterSwitchCenter=q<HTMLElement>('.board-center')!;
 expect(afterSwitchCenter.scrollLeft).toBe(0);
 expect(afterSwitchCenter.scrollTop).toBe(0);
 expect(q('.graph-root')!.textContent).toContain('DEMO-3');
 expect(q('.graph-mmf')).not.toBeNull();
});
