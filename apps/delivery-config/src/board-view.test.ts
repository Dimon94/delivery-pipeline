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
