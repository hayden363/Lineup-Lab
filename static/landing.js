(function(){
const {useState,useEffect,useRef,useMemo,useCallback,Fragment}=React;
const M=window.Motion; const {motion,AnimatePresence,useScroll,useTransform,useSpring,useMotionValue,useVelocity,useAnimationFrame,useInView,animate,MotionConfig}=M;
const html=htm.bind(React.createElement);
const L=window.LucideReact||{};
const Ico=(name,props)=>{const C=L[name];return C?React.createElement(C,props):React.createElement('span',{style:{display:'inline-block',width:props&&props.size||16}})};
const APP_URL='/?auth=login';
const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
const fmt=(n,d=1)=>Number(n).toFixed(d);
const money=n=>'$'+Math.round(n).toLocaleString('en-US');
function normCdf(z){ // Abramowitz-Stegun
  const t=1/(1+0.2316419*Math.abs(z));const d=0.3989423*Math.exp(-z*z/2);
  let p=d*t*(0.3193815+t*(-0.3565638+t*(1.781478+t*(-1.821256+t*1.330274))));
  return z>0?1-p:p;}
const PROB_ABOVE=(mean,sd,x)=>1-normCdf((x-mean)/sd);
const smooth={type:'spring',stiffness:260,damping:26};

/* ---------- number ticker: counts from the shown value to the new one ---------- */
function Ticker({value,decimals=1,prefix='',suffix='',className=''}){
  const [shown,setShown]=useState(value); const from=useRef(value);
  useEffect(()=>{const c=animate(from.current,value,{duration:.7,ease:[.16,1,.3,1],onUpdate:v=>{from.current=v;setShown(v)}});return()=>c.stop()},[value]);
  return html`<span className=${'mono '+className}>${prefix}${Number(shown).toLocaleString('en-US',{minimumFractionDigits:decimals,maximumFractionDigits:decimals})}${suffix}</span>`;
}

/* ---------- logo ---------- */
function Logo({size=40,animateKey=0}){
  const [hov,setHov]=useState(0);
  const k=animateKey+'-'+hov;
  const bars=[{x:37,h:9},{x:47,h:15},{x:57,h:21}];
  return html`<svg width=${size} height=${size} viewBox="0 0 100 100" role="img" aria-label="Lineup Lab logo" onMouseEnter=${()=>setHov(h=>h+1)} style=${{display:'block',overflow:'visible'}}>
    <defs>
      <linearGradient id="lgBadge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#246B54"/><stop offset="1" stop-color="#0D2B22"/></linearGradient>
      <linearGradient id="lgBorder" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7CF2A6" stop-opacity=".55"/><stop offset=".5" stop-color="#7CF2A6" stop-opacity=".06"/><stop offset="1" stop-color="#7CF2A6" stop-opacity=".18"/></linearGradient>
    </defs>
    <rect x="0" y="0" width="100" height="100" rx="26" fill="url(#lgBadge)"/>
    <rect x="1.5" y="1.5" width="97" height="97" rx="24.5" fill="none" stroke="url(#lgBorder)" stroke-width="2"/>
    <g transform="rotate(-18 50 50)">
      <path d="M8 50 Q50 4 92 50 Q50 96 8 50 Z" fill="rgba(4,20,14,.35)" stroke="#fff" stroke-width="3.6" stroke-linejoin="round"/>
      <path d="M13 38 Q27 17 50 13" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" opacity=".95"/>
      <path d="M17 33 Q31 12 54 8" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" opacity=".5"/>
      <path d="M87 62 Q73 83 50 87" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" opacity=".95"/>
      <path d="M83 67 Q69 88 46 92" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" opacity=".5"/>
      ${[38,46,54,62].map(x=>html`<line key=${x} x1=${x} y1=${x<50?30.5:30.5} y2="35.5" x2=${x} stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>`)}
      ${bars.map((b,i)=>html`<${motion.rect} key=${k+'b'+i} x=${b.x} width="6.4" rx="1.6" fill="#7CF2A6" y=${67-b.h} height=${b.h}
        style=${{originX:.5,originY:1}} initial=${{scaleY:0}} animate=${{scaleY:1}} transition=${{delay:.15+i*.12,duration:.6,ease:[.16,1,.3,1]}}/>`)}
      <${motion.path} key=${k+'t'} d="M33 55 L41 47.5 L46 51 L55 42 L59.5 45 L67 37" fill="none" stroke="#7CF2A6" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"
        initial=${{pathLength:0}} animate=${{pathLength:1}} transition=${{delay:.5,duration:.8,ease:'easeInOut'}}/>
      <${motion.path} key=${k+'a'} d="M62 36.4 L68.6 36 L68 42.6" fill="none" stroke="#7CF2A6" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"
        initial=${{opacity:0}} animate=${{opacity:1}} transition=${{delay:1.2,duration:.2}}/>
    </g>
  </svg>`;
}

/* ---------- 3D tilt wrapper ---------- */
function Tilt({children,className='',max=7,style={},spot=true}){
  const ref=useRef(null);
  const rx=useSpring(0,{stiffness:170,damping:18}),ry=useSpring(0,{stiffness:170,damping:18});
  const mx=useMotionValue(50),my=useMotionValue(50);
  const bg=useTransform([mx,my],([x,y])=>`radial-gradient(420px circle at ${x}% ${y}%,rgba(124,242,166,.16),transparent 60%)`);
  const move=e=>{const r=ref.current.getBoundingClientRect();const px=(e.clientX-r.left)/r.width,py=(e.clientY-r.top)/r.height;
    ry.set((px-.5)*max*2);rx.set(-(py-.5)*max*2);mx.set(px*100);my.set(py*100)};
  const leave=()=>{rx.set(0);ry.set(0)};
  return html`<${motion.div} ref=${ref} onMouseMove=${move} onMouseLeave=${leave} className=${className}
    style=${{...style,rotateX:rx,rotateY:ry,transformPerspective:1100,transformStyle:'preserve-3d'}}>
    ${spot&&html`<${motion.div} style=${{background:bg}} className="absolute inset-0 pointer-events-none rounded-[inherit] z-0" aria-hidden="true"/>`}
    ${children}
  <//>`;
}

/* ---------- magnetic button ---------- */
function Magnetic({children,className='',onClick,href}){
  const ref=useRef(null);const x=useSpring(0,{stiffness:220,damping:16}),y=useSpring(0,{stiffness:220,damping:16});
  const move=e=>{const r=ref.current.getBoundingClientRect();x.set((e.clientX-(r.left+r.width/2))*.3);y.set((e.clientY-(r.top+r.height/2))*.4)};
  const leave=()=>{x.set(0);y.set(0)};
  const Tag=href?motion.a:motion.button;
  return html`<${Tag} ref=${ref} onMouseMove=${move} onMouseLeave=${leave} onClick=${onClick} href=${href} style=${{x,y}} whileTap=${{scale:.95}} className=${className}>${children}<//>`;
}

/* ---------- sample data (illustrative projections, not live) ---------- */
const SLATE=[
 // id,name,pos,proj,floor,ceil,own
 ['jallen','Josh Allen','QB',24.6,17.5,36.0,17],['lamar','Lamar Jackson','QB',24.1,16.0,37.5,15],['burrow','Joe Burrow','QB',21.8,13.5,34.0,9],
 ['hurts','Jalen Hurts','QB',21.2,14.0,33.0,11],['goff','Jared Goff','QB',19.4,13.0,29.5,6],['maye','Drake Maye','QB',19.9,12.0,31.0,5],
 ['bijan','Bijan Robinson','RB',20.9,12.5,32.0,24],['saquon','Saquon Barkley','RB',19.6,11.0,31.5,21],['gibbs','Jahmyr Gibbs','RB',18.8,10.0,31.0,18],
 ['jcook','James Cook','RB',16.7,9.0,27.0,13],['kyren','Kyren Williams','RB',15.1,8.5,24.5,10],['hall','Breece Hall','RB',14.2,7.0,25.0,7],
 ['achane',"De'Von Achane",'RB',16.0,6.5,30.0,8],['bucky','Bucky Irving','RB',13.0,7.0,22.0,4],['mccaffrey','Christian McCaffrey','RB',17.9,9.0,30.0,14],
 ['chase',"Ja'Marr Chase",'WR',20.6,10.5,35.0,22],['jeff','Justin Jefferson','WR',19.8,9.5,34.0,19],['puka','Puka Nacua','WR',19.1,9.0,33.0,17],
 ['lamb','CeeDee Lamb','WR',18.4,9.5,31.0,15],['amon','Amon-Ra St. Brown','WR',17.7,10.5,28.5,16],['flowers','Zay Flowers','WR',14.9,6.5,28.0,6],
 ['nico','Nico Collins','WR',16.4,7.0,30.0,9],['higgins','Tee Higgins','WR',14.0,5.5,27.5,5],['mclaurin','Terry McLaurin','WR',13.4,6.0,25.0,7],
 ['dkmet','DK Metcalf','WR',12.2,4.5,24.0,4],['jsn','Jaxon Smith-Njigba','WR',16.9,8.0,30.0,12],['tmac','Trey McBride','TE',15.6,8.5,24.5,20],
 ['kittle','George Kittle','TE',13.1,5.5,25.0,12],['laporta','Sam LaPorta','TE',10.7,4.0,20.0,6],['bowers','Brock Bowers','TE',16.2,7.5,27.0,16],
 ['kincaid','Dalton Kincaid','TE',9.4,3.0,19.0,3],['dstbuf','Bills D/ST','DST',8.2,1.0,17.0,12],['dstbal','Ravens D/ST','DST',8.0,0.0,16.0,10],
 ['dstden','Broncos D/ST','DST',8.9,1.0,18.0,14],['dstphi','Eagles D/ST','DST',7.4,-1.0,15.0,5],
].map(a=>({id:a[0],name:a[1],pos:a[2],proj:a[3],floor:a[4],ceil:a[5],own:a[6]}));
const BYID=Object.fromEntries(SLATE.map(p=>[p.id,p]));

/* ---------- sample roster for the sandbox: your team plus a few free agents ---------- */
/* Sample games. Weather and matchup are illustrative, and each player's projection already includes them. */
const GAMES={
 DET:{vs:'@ CHI',e:'❄️',t:31,w:16},BUF:{vs:'vs NE',e:'🌨️',t:27,w:12},DEN:{vs:'vs LV',e:'☀️',t:61,w:6},MIA:{vs:'vs NYJ',e:'☀️',t:79,w:7},
 NYJ:{vs:'@ MIA',e:'☀️',t:79,w:7},LAR:{vs:'@ SEA',e:'🌧️',t:49,w:9},HOU:{vs:'vs JAX',e:'🏟️',t:72,w:0,dome:true},BAL:{vs:'@ CIN',e:'☁️',t:44,w:8},
 CIN:{vs:'vs BAL',e:'☁️',t:44,w:8},WAS:{vs:'vs DAL',e:'⛅',t:52,w:10},PIT:{vs:'@ CLE',e:'🌧️',t:46,w:14},SF:{vs:'vs ARI',e:'☀️',t:68,w:5},
 LAC:{vs:'vs KC',e:'☀️',t:72,w:6},NYG:{vs:'@ PHI',e:'☁️',t:43,w:9},CAR:{vs:'vs TB',e:'⛅',t:66,w:8},TB:{vs:'@ CAR',e:'⛅',t:66,w:8},GB:{vs:'vs MIN',e:'❄️',t:24,w:15}};
function wxAdj(pos,g){
  if(g.dome)return (pos==='QB'||pos==='K')?0.2:0.1;
  let a=0;
  if(g.w>=15)a+=({QB:-.9,WR:-.5,K:-.8})[pos]||0;
  if(g.t<=32)a+=({QB:-.4,K:-.5})[pos]||0;
  if(g.e==='🌧️'||g.e==='🌨️')a+=({QB:-.3,WR:-.2,K:-.4})[pos]||0;
  return a;
}
const r1=x=>Math.round(x*10)/10;
const SB=[
 // id, name, pos, projection, floor, ceiling, team game, matchup rank (1 = toughest, 32 = softest), % rostered if a free agent
 ['goff','Jared Goff','QB',19.4,13.0,29.5,'DET',24],['nix','Bo Nix','QB',18.2,11.0,28.5,'DEN',19],
 ['cook','James Cook','RB',16.7,9.0,27.0,'BUF',27],['achane',"De'Von Achane",'RB',16.0,6.5,30.0,'MIA',15],['kyren','Kyren Williams','RB',15.1,8.5,24.5,'LAR',8],['hall','Breece Hall','RB',14.2,7.0,25.0,'NYJ',21],
 ['nico','Nico Collins','WR',16.4,7.0,30.0,'HOU',29],['flowers','Zay Flowers','WR',14.9,6.5,28.0,'BAL',12],['higgins','Tee Higgins','WR',14.0,5.5,27.5,'CIN',26],['mclaurin','Terry McLaurin','WR',13.4,6.0,25.0,'WAS',17],['dkmet','DK Metcalf','WR',12.2,4.5,24.0,'PIT',6],
 ['kittle','George Kittle','TE',13.1,5.5,25.0,'SF',22],['laporta','Sam LaPorta','TE',10.7,4.0,20.0,'DET',24],['kincaid','Dalton Kincaid','TE',9.4,3.0,19.0,'BUF',18],
 ['dicker','Cameron Dicker','K',7.1,2.0,14.0,'LAC',20],['dstbuf','Bills D/ST','DST',8.2,0.0,17.0,'BUF',9],['dstbal','Ravens D/ST','DST',8.0,0.0,16.0,'BAL',14],
 ['tracy','Tyrone Tracy Jr.','RB',12.4,5.0,22.0,'NYG',25,38],['coker','Jalen Coker','WR',14.4,5.0,26.0,'CAR',28,14],['kraft','Tucker Kraft','TE',11.6,4.0,21.0,'GB',16,41],
 ['mclaughlin','Chase McLaughlin','K',8.4,3.0,15.0,'TB',18,33],['dsthou','Texans D/ST','DST',8.6,1.0,17.0,'HOU',23,29]
].map(a=>{const g=GAMES[a[6]];const mu=r1(((a[7]-16.5)/15.5)*0.1*a[3]);const wx=r1(wxAdj(a[2],g));
  return {id:a[0],name:a[1],pos:a[2],proj:a[3],floor:a[4],ceil:a[5],g,rank:a[7],mu,wx,base:r1(a[3]-mu-wx),fa:a.length>8,rostered:a[8]||0,sd:(a[5]-a[4])/3.3}});
const SBID=Object.fromEntries(SB.map(p=>[p.id,p]));
const mEm=p=>p.rank>=22?'🟢':p.rank>=11?'🟡':'🔴';
const mTier=p=>p.rank>=22?'Soft matchup':p.rank>=11?'Neutral matchup':'Tough matchup';
const wxText=g=>g.dome?'Dome, '+g.t+'°F':g.t+'°F, wind '+g.w+' mph';
const sgn=x=>(x>=0?'+':'−')+Math.abs(x).toFixed(1);
const NEED={QB:1,RB:2,WR:3,TE:1,K:1,DST:1}, FLEX_POS=['RB','WR','TE'], FLEX_SLOTS=2;
const choose=(n,k)=>{if(k<0||k>n)return 0;let r=1;for(let i=1;i<=k;i++)r=r*(n-k+i)/i;return Math.round(r)};
/* Exact best lineup. With no cap, the optimum is: locked players first, then the best remaining
   player at each position, then the best remaining RB/WR/TE for the two flex slots. */
function optimizeRoster(pool,locked,excluded){
  const av=pool.filter(p=>!excluded.has(p.id));
  const byPos=pos=>av.filter(p=>p.pos===pos).sort((a,b)=>b.proj-a.proj);
  const lockedBy={};let excess=0;
  for(const pos of Object.keys(NEED)){lockedBy[pos]=byPos(pos).filter(p=>locked.has(p.id));
    const over=lockedBy[pos].length-NEED[pos];
    if(over>0){if(!FLEX_POS.includes(pos))return {error:'You can only start '+NEED[pos]+' '+pos+'. Unlock one.'};excess+=over}}
  if(excess>FLEX_SLOTS)return {error:'Too many locked players for the flex spots. Unlock someone.'};
  const chosen=[];
  for(const pos of Object.keys(NEED)){const free=byPos(pos).filter(p=>!locked.has(p.id));
    const rem=Math.max(0,NEED[pos]-lockedBy[pos].length);
    if(free.length<rem)return {error:'Not enough '+pos+' available. Bring one back from Out.'};
    chosen.push(...lockedBy[pos],...free.slice(0,rem))}
  const ids=new Set(chosen.map(p=>p.id));
  const flexPool=av.filter(p=>FLEX_POS.includes(p.pos)&&!ids.has(p.id)).sort((a,b)=>b.proj-a.proj);
  const flexLeft=FLEX_SLOTS-excess;
  if(flexPool.length<flexLeft)return {error:'Not enough flex players available.'};
  const flex=[...flexPool.slice(0,flexLeft)];
  const players=[];
  for(const pos of ['QB','RB','WR','TE']){
    const mine=chosen.filter(p=>p.pos===pos).sort((a,b)=>b.proj-a.proj);
    mine.slice(0,NEED[pos]).forEach(p=>players.push({...p,slot:pos}));
    mine.slice(NEED[pos]).forEach(p=>flex.push(p))}
  flex.sort((a,b)=>b.proj-a.proj).forEach(p=>players.push({...p,slot:'FLEX'}));
  for(const pos of ['K','DST'])chosen.filter(p=>p.pos===pos).forEach(p=>players.push({...p,slot:pos}));
  const ordered=['QB','RB','WR','TE','FLEX','K','DST'].flatMap(sl=>players.filter(p=>p.slot===sl));
  const used=new Set(ordered.map(p=>p.id));
  // how many different legal lineups exist for this pool and these locks
  const cnt=pos=>({n:av.filter(p=>p.pos===pos&&!locked.has(p.id)).length,l:lockedBy[pos].length});
  let space=0;
  for(let r=2;r<=4;r++)for(let w=3;w<=5;w++){const t=8-r-w;if(t<1)continue;
    const c={RB:r,WR:w,TE:t,QB:1,K:1,DST:1};let prod=1;
    for(const pos of Object.keys(c)){const x=cnt(pos);prod*=choose(x.n,c[pos]-x.l);if(!prod)break}
    space+=prod}
  return {players:ordered,bench:av.filter(p=>!used.has(p.id)).sort((a,b)=>b.proj-a.proj),pts:ordered.reduce((a,p)=>a+p.proj,0),space};
}

/* ---------- NAV + AUTH ---------- */
function Nav({user,onOpenAuth,onLogout}){
  const links=[['Product','#product'],['Try it','#sandbox'],['Edges','#edges'],['Pricing','#pricing']];
  const go=(e,h)=>{e.preventDefault();const el=document.querySelector(h);if(el)el.scrollIntoView({behavior:'smooth',block:'start'})};
  const [open,setOpen]=useState(false);
  return html`<header className="sticky top-0 z-50 gutter" style=${{top:'env(safe-area-inset-top,0px)'}}>
    <div className="wrap pt-3">
      <nav className="glass rounded-2xl flex items-center justify-between px-3 sm:px-4 py-2.5" aria-label="Main">
        <a href="#top" onClick=${e=>go(e,'#top')} className="flex items-center gap-2.5 no-underline text-white">
          <${Logo} size=${34}/><span className="font-extrabold tracking-tight text-[16px] sm:text-[17px] whitespace-nowrap">Lineup Lab</span>
        </a>
        <div className="hidden md:flex items-center gap-1">
          ${links.map(([t,h])=>html`<a key=${h} href=${h} onClick=${e=>go(e,h)} className="px-3.5 py-2 rounded-full text-[14px] font-semibold text-[#B6CBBF] hover:text-white hover:bg-white/5 no-underline transition-colors">${t}</a>`)}
          <a href="/play" className="px-3.5 py-2 rounded-full text-[14px] font-semibold hover:text-white hover:bg-white/5 no-underline transition-colors" style=${{color:'#7CF2A6'}}>The Daily Drive</a>
        </div>
        <div className="flex items-center gap-2">
          ${user?html`
            <div className="flex items-center gap-2.5">
              <div className="hidden sm:block text-right leading-tight"><div className="text-[13px] font-bold">${user.name}</div><div className="mono text-[10.5px] mint">${user.via} · ${user.leagues} sample leagues</div></div>
              <div className="w-9 h-9 rounded-full grid place-items-center font-extrabold text-[#04140D]" style=${{background:'linear-gradient(180deg,#8CF7B2,#4ADE80)'}}>${user.name[0].toUpperCase()}</div>
              <button className="btn btn-ghost btn-sm" onClick=${onLogout} aria-label="Log out">${Ico('LogOut',{size:15})}<span className="hidden sm:inline">Log out</span></button>
            </div>`:html`
            <button className="hidden sm:inline-flex btn btn-ghost btn-sm" onClick=${()=>onOpenAuth('login')}>Log In</button>
            <${Magnetic} className="btn btn-mint btn-sm" onClick=${()=>onOpenAuth('signup')}><span className="sm:hidden">Start Free</span><span className="hidden sm:inline">Start Free</span><span className="hidden sm:inline-flex">${Ico('ArrowRight',{size:15})}</span><//>`}
          <button className="md:hidden btn btn-ghost btn-sm" aria-label="Menu" aria-expanded=${open} onClick=${()=>setOpen(o=>!o)}>${Ico(open?'X':'Menu',{size:16})}</button>
        </div>
      </nav>
      <${AnimatePresence}>${open&&html`<${motion.div} key="m" initial=${{opacity:0,y:-8}} animate=${{opacity:1,y:0}} exit=${{opacity:0,y:-8}} className="glass rounded-2xl mt-2 p-2 md:hidden">
        ${links.map(([t,h])=>html`<a key=${h} href=${h} onClick=${e=>{go(e,h);setOpen(false)}} className="block px-4 py-3 rounded-xl text-[15px] font-semibold no-underline text-white hover:bg-white/5">${t}</a>`)}
        <a href="/play" className="block px-4 py-3 rounded-xl text-[15px] font-semibold no-underline hover:bg-white/5" style=${{color:'#7CF2A6'}}>The Daily Drive</a>
        ${!user&&html`<button className="w-full text-left px-4 py-3 rounded-xl text-[15px] font-semibold hover:bg-white/5" onClick=${()=>{setOpen(false);onOpenAuth('login')}}>Log In</button>`}
      <//>`}<//>
    </div>
  </header>`;
}

/* ---------- HERO ---------- */
const WORDS=['Stop','losing','weeks','you','should','have','won.'];
const HERO_LINEUP=[['QB','goff'],['RB','cook','hall'],['RB','kyren'],['WR','nico'],['WR','higgins','dkmet'],['WR','mclaurin'],['TE','kittle','kincaid'],['FLEX','tracy','laporta'],['W/R/T','flowers'],['K','mclaughlin','dicker'],['DST','dstbuf']]
 .map(([slot,id,from])=>({slot,id,name:SBID[id].name,base:SBID[id].proj,from:from?SBID[from].name:null,gain:from?SBID[id].proj-SBID[from].proj:0,pickup:SBID[id].fa}));
function seededShuffle(seed){let s=seed;return()=>{s=(s*1664525+1013904223)%4294967296;return s/4294967296}}
function heroModel(seed){
  const r=seededShuffle(seed*7919);
  const rows=HERO_LINEUP.map(p=>{const proj=seed===1?p.base:Math.max(3,p.base+(r()-.45)*3.6);
    const fromProj=p.from?(seed===1?p.base-p.gain:proj-p.gain*(0.7+r()*0.6)):null;
    return {...p,proj,fromProj,gain:p.from?proj-fromProj:0}});
  const total=rows.reduce((a,p)=>a+p.proj,0);
  const baseTotal=rows.reduce((a,p)=>a+(p.from?p.fromProj:p.proj),0);
  const sd=Math.sqrt(rows.reduce((a,p)=>a+Math.pow(p.proj*.36,2),0)+60);
  const winP=t=>PROB_ABOVE(t-146,Math.sqrt(sd*sd+144),0)*100;
  return {rows,total,baseTotal,sd,winNow:winP(baseTotal),winOpt:winP(total),swaps:rows.filter(p=>p.from).length};
}

function HeroApp({model,seed,busy,reopt}){
  const [tab,setTab]=useState('lineup');
  const {rows,total,baseTotal,sd,winNow,winOpt}=model;
  const sims=useMemo(()=>{const r=seededShuffle(seed*104729+3);const bins=new Array(24).fill(0);
    for(let i=0;i<4000;i++){let u=0;for(let k=0;k<6;k++)u+=r();const z=(u-3)/Math.sqrt(.5);const x=total+z*sd;const b=clamp(Math.floor((x-(total-3.2*sd))/(6.4*sd/24)),0,23);bins[b]++}return bins},[seed,total,sd]);
  const maxBin=Math.max(...sims);
  const p90=total+1.2816*sd;
  const stacks=[['Goff','St. Brown','LaPorta'],['Burrow','Chase','Higgins'],['Allen','Cook','Kincaid']];
  const tabs=[['lineup','Optimal Lineup'],['sims','Monte Carlo 10k Sims'],['stacks','QB-WR Stacks']];
  return html`<div className="relative z-10 rounded-[22px] overflow-hidden" style=${{background:'#08130E',border:'1px solid rgba(124,242,166,.18)'}}>
    <div className="flex items-center gap-2 px-4 py-3" style=${{borderBottom:'1px solid rgba(255,255,255,.06)'}}>
      <span className="w-2.5 h-2.5 rounded-full" style=${{background:'#FF6B6B'}}></span><span className="w-2.5 h-2.5 rounded-full" style=${{background:'#F5C26B'}}></span><span className="w-2.5 h-2.5 rounded-full" style=${{background:'#4ADE80'}}></span>
      <span className="mono text-[11px] dim ml-3 truncate">lineuplab / week 11 / sample league</span>
      <span className="ml-auto tag">Sample data</span>
    </div>
    <div className="p-3 sm:p-5">
      <div className="flex flex-wrap items-center gap-2 mb-3" role="tablist">
        ${tabs.map(([id,t])=>html`<button key=${id} role="tab" aria-selected=${tab===id} onClick=${()=>setTab(id)} className="chip" style=${{color:tab===id?'#04140D':undefined}}>
          ${tab===id&&html`<${motion.span} layoutId="heroTab" className="pill-bg" transition=${smooth}/>`}<span className="relative font-bold">${t}</span></button>`)}
        <button onClick=${reopt} className="btn btn-ghost btn-sm ml-auto" style=${{padding:'7px 13px'}} aria-label="Re-optimize">
          <${motion.span} animate=${{rotate:busy?360:0}} transition=${{duration:.65,ease:'easeInOut'}} style=${{display:'inline-flex'}}>${Ico('RefreshCw',{size:14})}<//>Re-Optimize</button>
      </div>
      <div style=${{minHeight:450}}>
      <${AnimatePresence} mode="wait">
      ${tab==='lineup'&&html`<${motion.div} key="l" initial=${{opacity:0,x:16}} animate=${{opacity:1,x:0}} exit=${{opacity:0,x:-16}} transition=${{duration:.25}}>
        <div className="flex items-center justify-between rounded-xl px-3 py-2 mb-2" style=${{background:'rgba(124,242,166,.08)',border:'1px solid rgba(124,242,166,.2)'}}>
          <span className="mono text-[11.5px] mint">${model.swaps} changes to your current lineup</span>
          <span className="mono text-[11.5px] muted">+<${Ticker} value=${total-baseTotal} className="mint font-bold"/> pts</span>
        </div>
        <div className="grid gap-1">
          ${rows.map((p,i)=>html`<${motion.div} layout key=${p.slot+p.name} className="row gap-2.5 px-2.5 py-1.5 rounded-lg" style=${{gridTemplateColumns:'44px minmax(0,1fr) auto',background:p.from?'rgba(124,242,166,.07)':'rgba(255,255,255,.03)',border:'1px solid '+(p.from?'rgba(124,242,166,.22)':'transparent')}}
            animate=${{opacity:busy?.35:1}} transition=${{delay:i*.02}}>
            <span className="mono text-[10px] font-bold px-1 py-1 rounded-md text-center" style=${{background:'rgba(124,242,166,.1)',color:'var(--mint)'}}>${p.slot}</span>
            <div className="min-w-0"><div className="font-semibold text-[13.5px] truncate leading-tight">${p.name}${p.pickup?html` <span className="tag" style=${{marginLeft:4,color:'var(--mint)',borderColor:'rgba(124,242,166,.4)'}}>Waiver add</span>`:''}</div>
              ${p.from&&html`<div className="mono text-[10.5px] mint truncate">in for ${p.from} · +${fmt(p.gain)}</div>`}</div>
            <div className="flex items-center gap-2"><span className="text-[13px]" title=${mTier(SBID[p.id])+' · '+wxText(SBID[p.id].g)} aria-label=${mTier(SBID[p.id])+', '+wxText(SBID[p.id].g)}>${mEm(SBID[p.id])}${SBID[p.id].g.e}</span><${Ticker} value=${p.proj} className="text-[13.5px] font-bold w-[46px] text-right"/></div>
          <//>`)}
        </div>
        <div className="mono text-[10.5px] dim mt-2 px-1">🟢 soft · 🟡 neutral · 🔴 tough matchup, with that game's weather</div>
        <div className="flex items-end justify-between mt-2 px-1">
          <div><div className="eyebrow">Projected total</div><div className="flex items-baseline gap-2"><${Ticker} value=${total} className="text-[28px] font-bold leading-none"/><span className="mono text-[11px] dim">was ${fmt(baseTotal)}</span></div></div>
          <div className="text-right"><div className="eyebrow">Chance to win</div><div className="flex items-baseline justify-end gap-2"><span className="mono text-[11px] dim line-through">${Math.round(winNow)}%</span><${Ticker} value=${winOpt} decimals=${0} suffix="%" className="text-[28px] font-bold leading-none mint"/></div></div>
        </div>
      </${motion.div}>`}
      ${tab==='sims'&&html`<${motion.div} key="s" initial=${{opacity:0,x:16}} animate=${{opacity:1,x:0}} exit=${{opacity:0,x:-16}} transition=${{duration:.25}}>
        <div className="flex items-end gap-[3px] h-[230px] px-1" role="img" aria-label="Histogram of simulated lineup scores">
          ${sims.map((v,i)=>html`<${motion.div} key=${i} className="flex-1 rounded-t" initial=${{height:0}} animate=${{height:Math.max(3,(v/maxBin)*100)+'%'}} transition=${{delay:i*.012,duration:.5,ease:[.16,1,.3,1]}}
             style=${{background:i>=19?'linear-gradient(180deg,#B8FFD0,#4ADE80)':'linear-gradient(180deg,#1C5E49,#0E3226)',boxShadow:i>=19?'0 0 18px rgba(124,242,166,.5)':'none'}}/>`)}
        </div>
        <div className="grid grid-cols-3 gap-2 mt-4">
          ${[['Typical score',total],['Great week',p90],['Sims run',4000]].map(([l,v],i)=>html`<div key=${l} className="rounded-xl p-3" style=${{background:'rgba(255,255,255,.03)'}}><div className="eyebrow">${l}</div><${Ticker} value=${v} decimals=${i===2?0:1} className="text-[22px] font-bold"/></div>`)}
        </div>
        <p className="text-[12px] dim mt-3">This page runs 4,000 draws in your browser from the lineup's projected total and its spread. Lineup Lab runs 10,000 on your real roster.</p>
      <//>`}
      ${tab==='stacks'&&html`<${motion.div} key="k" initial=${{opacity:0,x:16}} animate=${{opacity:1,x:0}} exit=${{opacity:0,x:-16}} transition=${{duration:.25}} className="grid gap-2">
        ${stacks.map((s,i)=>html`<${motion.div} key=${s.join()} className="flex items-center gap-3 rounded-xl p-3.5" style=${{background:'rgba(255,255,255,.03)',border:'1px solid rgba(124,242,166,.1)'}} initial=${{opacity:0,y:10}} animate=${{opacity:1,y:0}} transition=${{delay:i*.08}}>
          <div className="flex -space-x-2">${s.map((n,j)=>html`<div key=${n} className="w-9 h-9 rounded-full grid place-items-center text-[12px] font-extrabold" style=${{background:'#0F2A20',border:'2px solid #08130E',color:'var(--mint)',zIndex:3-j}}>${n[0]}</div>`)}</div>
          <div className="min-w-0 flex-1"><div className="font-bold text-[14px] truncate">${s.join(' + ')}</div><div className="mono text-[11px] muted">scores together · correlation +0.${[41,52,38][i]}</div></div>
          <div className="mono text-[15px] font-bold mint">+${[3.9,5.2,2.8][i]}</div>
        <//>`)}
        <p className="text-[12px] dim mt-1">A stack pairs a quarterback with his pass catchers, so one big play lifts every slot. Values are sample points of upside over a random pairing.</p>
      <//>`}
      <//>
      </div>
    </div>
  </div>`;
}

function Hero(){
  const [seed,setSeed]=useState(1);const [busy,setBusy]=useState(false);
  const model=useMemo(()=>heroModel(seed),[seed]);
  const reopt=()=>{if(busy)return;setBusy(true);setTimeout(()=>{setSeed(x=>x+1);setBusy(false)},650)};
  const stageRef=useRef(null);
  const rx=useSpring(0,{stiffness:120,damping:16}),ry=useSpring(0,{stiffness:120,damping:16});
  const mx=useMotionValue(50),my=useMotionValue(40);
  const spot=useTransform([mx,my],([x,y])=>`radial-gradient(520px circle at ${x}% ${y}%,rgba(124,242,166,.22),transparent 62%)`);
  const move=e=>{const r=stageRef.current.getBoundingClientRect();const px=(e.clientX-r.left)/r.width,py=(e.clientY-r.top)/r.height;
    ry.set((px-.5)*14);rx.set(-(py-.5)*10);mx.set(px*100);my.set(py*100)};
  const leave=()=>{rx.set(0);ry.set(0);mx.set(50);my.set(40)};
  const {scrollY}=useScroll();
  const flat=useTransform(scrollY,[0,520],[1,0]);
  const rxs=useTransform([rx,flat],([a,f])=>a*f), rys=useTransform([ry,flat],([a,f])=>a*f);
  const scl=useTransform(scrollY,[0,520],[1,1.04]);
  return html`<section id="top" className="gutter pt-10 sm:pt-16 pb-10">
    <div className="wrap grid grid-cols-1 gap-12 lg:gap-8 lg:grid-cols-[1.02fr_1fr] items-center">
      <div className="min-w-0">
        <${motion.div} initial=${{opacity:0,y:10}} animate=${{opacity:1,y:0}} transition=${{delay:.1}} className="inline-flex items-center gap-2 rounded-full pl-2.5 pr-3.5 py-1.5 mb-6" style=${{border:'1px solid var(--line)',background:'rgba(124,242,166,.06)'}}>
          <span className="w-2 h-2 rounded-full" style=${{background:'var(--mint)',animation:'pulse 2s infinite'}}></span>
          <span className="mono text-[11.5px] mint font-medium">Sleeper and ESPN leagues sync in 30 seconds</span>
        <//>
        <h1 className="font-extrabold tracking-[-0.035em] leading-[.98] text-[clamp(42px,6.2vw,80px)]" aria-label="Stop losing weeks you should have won.">
          ${WORDS.map((w,i)=>html`<${Fragment} key=${i}><span className="kinetic" aria-hidden="true"><${motion.span} style=${{display:'inline-block'}} className=${i>=4?'hl':''}
            initial=${{y:'115%',rotate:4}} animate=${{y:0,rotate:0}} transition=${{delay:.15+i*.09,duration:.8,ease:[.16,1,.3,1]}}>${w}<//></span>${' '}<//>`)}
        </h1>
        <${motion.p} initial=${{opacity:0,y:14}} animate=${{opacity:1,y:0}} transition=${{delay:.85}} className="text-[18px] leading-[1.6] max-w-[520px] mt-6" style=${{color:'#B6CBBF'}}>
          Somewhere on your roster or the waiver wire is a better lineup than the one you set. Lineup Lab finds it every week: who to start, who to pick up, and which trades actually help your team.
        <//>
        <${motion.div} initial=${{opacity:0,y:14}} animate=${{opacity:1,y:0}} transition=${{delay:1}} className="flex flex-wrap gap-3 mt-8">
          <a className="btn btn-mint no-underline" href=${APP_URL}>${Ico('Zap',{size:17})}Launch Lineup Lab Free</a>
          <button className="btn btn-ghost" onClick=${()=>document.querySelector('#sandbox').scrollIntoView({behavior:'smooth'})}>${Ico('Play',{size:15})}Watch Live Engine</button>
          <a className="btn btn-ghost no-underline" href="/play" style=${{borderColor:'rgba(124,242,166,.5)'}}>${Ico('Trophy',{size:15})}Play today's Daily Drive</a>
        <//>
        <${motion.div} initial=${{opacity:0}} animate=${{opacity:1}} transition=${{delay:1.2}} className="flex flex-wrap gap-x-6 gap-y-2 mt-8 mono text-[12px] muted">
          <span className="inline-flex items-center gap-1.5">${Ico('ShieldCheck',{size:14,color:'#7CF2A6'})}Google sign-in verified</span>
          <span className="inline-flex items-center gap-1.5">${Ico('Lock',{size:14,color:'#7CF2A6'})}ESPN cookies encrypted</span>
          <span className="inline-flex items-center gap-1.5">${Ico('Cpu',{size:14,color:'#7CF2A6'})}Free NFL data, no paid feeds</span>
        <//>
      </div>
      <${motion.div} ref=${stageRef} onMouseMove=${move} onMouseLeave=${leave} className="relative" style=${{perspective:1400,scale:scl}} initial=${{opacity:0,y:40}} animate=${{opacity:1,y:0}} transition=${{delay:.5,duration:.9,ease:[.16,1,.3,1]}}>
        <${motion.div} style=${{rotateX:rxs,rotateY:rys,transformStyle:'preserve-3d',rotate:0}} className="relative">
          <div className="absolute -inset-6 rounded-[36px] pointer-events-none" style=${{background:'radial-gradient(60% 60% at 50% 50%,rgba(28,94,73,.6),transparent 70%)',filter:'blur(30px)'}} aria-hidden="true"></div>
          <${motion.div} className="absolute inset-0 rounded-[22px] pointer-events-none z-20" style=${{background:spot,mixBlendMode:'screen'}} aria-hidden="true"/>
          <${HeroApp} model=${model} seed=${seed} busy=${busy} reopt=${reopt}/>
          <${motion.div} className="glass absolute z-30 rounded-2xl px-4 py-3 hidden sm:block -left-2 lg:-left-10" style=${{top:-26,translateZ:70}} animate=${{y:[0,-10,0],x:[0,4,0]}} transition=${{duration:6,repeat:Infinity,ease:'easeInOut'}}>
            <div className="eyebrow">Win probability delta</div><div className="mono text-[24px] font-bold mint leading-tight">+<${Ticker} value=${model.winOpt-model.winNow} decimals=${1} suffix="%"/></div><div className="text-[11px] dim">vs. your current lineup (sample)</div>
          <//>
          <${motion.div} className="glass absolute z-30 rounded-2xl px-4 py-3 hidden sm:block -right-2 lg:-right-8" style=${{bottom:-50,translateZ:90}} animate=${{y:[0,12,0],x:[0,-5,0]}} transition=${{duration:7,repeat:Infinity,ease:'easeInOut',delay:.6}}>
            <div className="eyebrow">Better starts found</div><div className="mono text-[24px] font-bold leading-tight"><${Ticker} value=${model.swaps} decimals=${0}/><span className="text-[13px] muted"> this week</span></div><div className="text-[11px] dim">sample lineup</div>
          <//>
        <//>
        <div className="flex gap-2 mt-4 sm:hidden">
          <span className="tag">+<${Ticker} value=${model.winOpt-model.winNow} decimals=${1} suffix="%"/> win chance vs. current lineup (sample)</span>
        </div>
      <//>
    </div>
  </section>`;
}

/* ---------- TICKER: two rows, opposite directions, speed follows scroll velocity ---------- */
const EDGES=['J. Chase +4.8 Proj Edge','Sleeper & ESPN Live Sync','10,000 Monte Carlo Sims / 0.4s','Optimal QB-WR Correlation Detected','G. Kittle +3.7 over your current TE','Waiver Radar: 3 pickups beat your bench','Playoff odds +6.4% on 1 trade','5 better starts found in a sample lineup'];
function Row({dir=1,items}){
  const base=useRef(0);const wrap=useRef(null);
  const {scrollY}=useScroll();const vel=useVelocity(scrollY);const sv=useSpring(vel,{damping:50,stiffness:400});
  const factor=useTransform(sv,[0,1000],[0,4],{clamp:false});
  const x=useMotionValue(0);
  useAnimationFrame((t,dt)=>{const w=wrap.current?wrap.current.scrollWidth/2:1;
    const move=dir*-0.045*dt*(1+Math.abs(factor.get()));
    base.current+=move;if(base.current<=-w)base.current+=w;if(base.current>0)base.current-=w;x.set(base.current)});
  const list=[...items,...items];
  return html`<div className="overflow-hidden" style=${{WebkitMaskImage:'linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent)',maskImage:'linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent)'}}>
    <${motion.div} ref=${wrap} style=${{x,display:'flex',width:'max-content'}}>
      ${list.map((t,i)=>html`<span key=${i} className="mono text-[13px] px-4 py-2 rounded-full whitespace-nowrap inline-flex items-center gap-2" style=${{marginRight:12,border:'1px solid var(--line)',background:'rgba(11,24,19,.7)',color:i%3===0?'var(--mint)':'#C9DBD0'}}>
        <span className="w-1.5 h-1.5 rounded-full" style=${{background:'var(--mint)',opacity:.8}}></span>${t}</span>`)}
    <//>
  </div>`;
}
function Ticker2(){
  return html`<section aria-label="Live edges ticker" className="py-6 grid gap-3" style=${{borderTop:'1px solid rgba(255,255,255,.05)',borderBottom:'1px solid rgba(255,255,255,.05)',background:'rgba(4,10,8,.5)'}}>
    <${Row} dir=${1} items=${EDGES}/><${Row} dir=${-1} items=${[...EDGES].reverse()}/>
  </section>`;
}

/* ---------- BENTO ---------- */
const reveal={initial:{opacity:0,y:36},whileInView:{opacity:1,y:0},viewport:{once:true,margin:'-60px'},transition:{duration:.8,ease:[.16,1,.3,1]}};

/* Card 1: start/sit quiz. You pick first, then the engine shows its call. */
const DILEMMAS=[['FLEX','kyren','hall'],['WR3','higgins','dkmet'],['QB','goff','nix'],['TE','kittle','laporta']];
function StartSit({onOpenAuth}){
  const [picks,setPicks]=useState({});
  const done=Object.keys(picks).length===DILEMMAS.length;
  const left=DILEMMAS.reduce((a,[sl,x,y],i)=>{const c=picks[i];if(!c)return a;const best=Math.max(SBID[x].proj,SBID[y].proj);return a+(best-SBID[c].proj)},0);
  const matched=DILEMMAS.filter(([sl,x,y],i)=>picks[i]&&SBID[picks[i]].proj===Math.max(SBID[x].proj,SBID[y].proj)).length;
  return html`<div className="relative z-10 flex flex-col h-full">
    <div className="eyebrow mb-2">Start / Sit</div>
    <h3 className="font-extrabold text-[22px] leading-tight tracking-tight">Make the call. Then see what the numbers say.</h3>
    <p className="muted text-[14px] mt-1.5">Four lineup decisions with each player's matchup and weather. Tap who you would start.</p>
    <div className="grid gap-2.5 mt-4">
      ${DILEMMAS.map(([sl,x,y],i)=>{const A=SBID[x],B=SBID[y];const c=picks[i];const win=A.proj>=B.proj?x:y;
        return html`<div key=${i} className="rounded-2xl p-2.5" style=${{background:'rgba(255,255,255,.03)',border:'1px solid '+(c?(c===win?'rgba(124,242,166,.35)':'rgba(245,194,107,.45)'):'rgba(255,255,255,.06)')}}>
          <div className="flex items-center justify-between mb-1.5 px-1"><span className="mono text-[10.5px] mint font-bold">${sl}</span>
            ${c&&html`<${motion.span} initial=${{opacity:0}} animate=${{opacity:1}} className="mono text-[11px]" style=${{color:c===win?'var(--mint)':'var(--warn)'}}>${c===win?'Matches Lineup Lab':'Lineup Lab picks '+SBID[win].name.split(' ').slice(-1)[0]+' · +'+fmt(Math.abs(A.proj-B.proj))+' pts'}<//>`}</div>
          <div className="grid grid-cols-2 gap-2">
            ${[A,B].map(P=>html`<button key=${P.id} disabled=${!!c} onClick=${()=>setPicks(o=>({...o,[i]:P.id}))} className="text-left rounded-xl px-3 py-2" style=${{background:c===P.id?'rgba(124,242,166,.14)':'rgba(255,255,255,.04)',border:'1px solid '+(c===P.id?'rgba(124,242,166,.5)':'rgba(255,255,255,.08)'),cursor:c?'default':'pointer'}}>
              <div className="text-[13.5px] font-semibold leading-tight truncate">${P.name}</div>
              <div className="mono text-[11px] muted mt-0.5" title=${mTier(P)+' · '+wxText(P.g)}>${mEm(P)} ${P.g.vs} ${P.g.e}${c?html` · <span className=${P.id===win?'mint font-bold':''}>${fmt(P.proj)} pts</span> · ${fmt(P.floor,0)}–${fmt(P.ceil,0)}`:''}</div>
            </button>`)}
          </div></div>`})}
    </div>
    <div className="mt-auto pt-4" aria-live="polite">
      ${done?html`<${motion.div} initial=${{opacity:0,y:10}} animate=${{opacity:1,y:0}} className="rounded-2xl p-4" style=${{background:'rgba(124,242,166,.08)',border:'1px solid rgba(124,242,166,.3)'}}>
        <div className="font-bold text-[15px]">${left>0.05?'Your picks left '+fmt(left)+' projected points on the bench.':'You matched Lineup Lab on all four. Nice.'}</div>
        <div className="text-[13px] muted mt-1">${matched} of 4 matched. Lineup Lab makes these calls for every slot, every week, on your own league.</div>
        <div className="flex gap-2 mt-3"><button className="btn btn-mint btn-sm" onClick=${()=>onOpenAuth('signup')}>Check my real lineup ${Ico('ArrowRight',{size:14})}</button><button className="btn btn-ghost btn-sm" onClick=${()=>setPicks({})}>Try again</button></div>
      <//>`:html`<p className="text-[11px] dim">${Object.keys(picks).length} of 4 answered. Sample projections for an illustrative slate.</p>`}
    </div>
  </div>`;
}

/* Card 2: bell curve */
function Bell(){
  const [opt,setOpt]=useState(true);
  const std={m:118,s:14},lab={m:127.5,s:17.5};
  const [par,setPar]=useState(lab);const ref=useRef(null);const inView=useInView(ref,{once:true,margin:'-80px'});
  useEffect(()=>{const t=opt?lab:std;const f={...par};const c=animate(0,1,{duration:.9,ease:[.16,1,.3,1],onUpdate:u=>setPar({m:f.m+(t.m-f.m)*u,s:f.s+(t.s-f.s)*u})});return()=>c.stop()},[opt]);
  const W=420,H=210,pad={l:10,r:10,t:16,b:30},x0=70,x1=190;
  const X=v=>pad.l+(v-x0)/(x1-x0)*(W-pad.l-pad.r);
  const pdf=(x,m,s)=>Math.exp(-0.5*Math.pow((x-m)/s,2))/(s*2.5066);
  const ymax=pdf(118,118,14)*1.12;const Y=d=>pad.t+(1-d/ymax)*(H-pad.t-pad.b);
  const pts=[];for(let x=x0;x<=x1;x+=1.5)pts.push([X(x),Y(pdf(x,par.m,par.s))]);
  const line='M'+pts.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' L');
  const area=line+` L${X(x1)} ${Y(0)} L${X(x0)} ${Y(0)} Z`;
  const T=150;const tail=pts.filter((p,i)=>x0+i*1.5>=T);
  const tailPath=tail.length?`M${X(T)} ${Y(0)} L`+tail.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' L')+` L${X(x1)} ${Y(0)} Z`:'';
  const pT=PROB_ABOVE(par.m,par.s,T)*100;
  const ghost=[];for(let x=x0;x<=x1;x+=1.5)ghost.push([X(x),Y(pdf(x,std.m,std.s))]);
  return html`<div ref=${ref} className="relative z-10 flex flex-col h-full">
    <div className="eyebrow mb-2">Outcome distribution</div>
    <h3 className="font-extrabold text-[22px] leading-tight tracking-tight">See your whole range of Sundays</h3>
    <div className="flex gap-2 mt-4" role="tablist">
      ${[[false,'Standard Lineup'],[true,'Lineup Lab Optimized']].map(([k,t])=>html`<button key=${t} role="tab" aria-selected=${opt===k} className="chip" onClick=${()=>setOpt(k)} style=${{color:opt===k?'#04140D':undefined}}>${opt===k&&html`<${motion.span} layoutId="bellTab" className="pill-bg" transition=${smooth}/>`}<span className="relative font-bold">${t}</span></button>`)}
    </div>
    <svg viewBox=${'0 0 '+W+' '+H} className="w-full mt-3" role="img" aria-label="Score distribution">
      <defs><linearGradient id="bg1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7CF2A6" stop-opacity=".35"/><stop offset="1" stop-color="#7CF2A6" stop-opacity="0"/></linearGradient>
        <filter id="glow"><feGaussianBlur stdDeviation="3.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
      ${[80,100,120,140,160,180].map(v=>html`<g key=${v}><line x1=${X(v)} x2=${X(v)} y1=${pad.t} y2=${H-pad.b} stroke="rgba(255,255,255,.06)"/><text x=${X(v)} y=${H-10} fill="#5E7A6C" font-size="10" text-anchor="middle" font-family="JetBrains Mono">${v}</text></g>`)}
      <path d=${'M'+ghost.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' L')} fill="none" stroke="rgba(255,255,255,.28)" stroke-width="1.5" stroke-dasharray="4 5" style=${{opacity:opt?1:0,transition:'opacity .4s'}}/>
      <path d=${area} fill="url(#bg1)"/>
      <path d=${tailPath} fill="rgba(124,242,166,.5)"/>
      <line x1=${X(T)} x2=${X(T)} y1=${pad.t} y2=${H-pad.b} stroke="#fff" stroke-width="1" stroke-dasharray="3 4" opacity=".6"/>
      <text x=${X(T)+5} y=${pad.t+10} fill="#fff" font-size="10" font-family="JetBrains Mono">150 pts</text>
      <${motion.path} d=${line} fill="none" stroke="#7CF2A6" stroke-width="2.6" stroke-linecap="round" filter="url(#glow)" initial=${{pathLength:0}} animate=${inView?{pathLength:1}:{pathLength:0}} transition=${{duration:1.6,ease:'easeInOut'}}/>
    </svg>
    <div className="grid grid-cols-3 gap-2 mt-auto pt-3">
      <div><div className="eyebrow">Mean</div><${Ticker} value=${par.m} className="text-[22px] font-bold"/></div>
      <div><div className="eyebrow">Spread (SD)</div><${Ticker} value=${par.s} className="text-[22px] font-bold"/></div>
      <div><div className="eyebrow">Odds ≥150</div><${Ticker} value=${pT} suffix="%" className="text-[22px] font-bold mint"/></div>
    </div>
  </div>`;
}

/* Card 3: waiver / trade radar with a spring progress ring */
function Ring({value}){
  const r=44,c=2*Math.PI*r;const sp=useSpring(value,{stiffness:70,damping:15});useEffect(()=>{sp.set(value)},[value]);
  const dash=useTransform(sp,v=>c*(1-v/100));const [txt,setTxt]=useState(value);
  useEffect(()=>sp.on('change',v=>setTxt(v)),[]);
  return html`<div className="relative" style=${{width:112,height:112}}>
    <svg viewBox="0 0 112 112" width="112" height="112" style=${{transform:'rotate(-90deg)'}}><circle cx="56" cy="56" r=${r} fill="none" stroke="rgba(255,255,255,.08)" stroke-width="9"/>
      <${motion.circle} cx="56" cy="56" r=${r} fill="none" stroke="#7CF2A6" stroke-width="9" stroke-linecap="round" strokeDasharray=${c} style=${{strokeDashoffset:dash,filter:'drop-shadow(0 0 8px rgba(124,242,166,.7))'}}/></svg>
    <div className="absolute inset-0 grid place-items-center"><div className="text-center leading-none"><div className="mono text-[24px] font-bold">${Math.round(txt)}%</div><div className="mono text-[9.5px] muted mt-1">PLAYOFFS</div></div></div>
  </div>`;
}
const MOVES=[
 {id:1,kind:'Waiver',title:'Pick up Bucky Irving',sub:'Drop your WR6. Covers two bye weeks.',gain:4.1,detail:'+2.3 pts/wk on your flex'},
 {id:2,kind:'Trade',title:'Send Breece Hall for Justin Jefferson',sub:'Fills your WR2 hole, costs RB depth you can spare.',gain:6.8,detail:'Rest-of-season value +9%'},
 {id:3,kind:'Waiver',title:'Pick up Dalton Kincaid',sub:'TE streamer with a soft matchup next two weeks.',gain:2.2,detail:'+3.4 pts over your TE'},
];
function Radar(){
  const [odds,setOdds]=useState(62);const [i,setI]=useState(0);const [done,setDone]=useState([]);const [sim,setSim]=useState(null);
  const cur=MOVES[i];
  const next=()=>{setI(x=>x+1);setSim(null)};
  const accept=()=>{setOdds(o=>clamp(o+cur.gain,0,99));setDone(d=>[...d,cur.id]);next()};
  const simulate=()=>setSim(cur.gain);
  const reset=()=>{setOdds(62);setI(0);setDone([]);setSim(null)};
  return html`<div className="relative z-10 flex flex-col h-full">
    <div className="eyebrow mb-2">AI trade & waiver radar</div>
    <h3 className="font-extrabold text-[22px] leading-tight tracking-tight">Every move scored against your playoff odds</h3>
    <div className="flex items-center gap-4 mt-4"><${Ring} value=${sim!=null?clamp(odds+sim,0,99):odds}/>
      <div className="min-w-0"><div className="mono text-[12px] muted">Moves accepted</div><div className="mono text-[26px] font-bold">${done.length}<span className="text-[14px] muted">/${MOVES.length}</span></div>
        ${sim!=null&&html`<div className="mono text-[12px] mint">simulated +${sim} pts of odds</div>`}</div></div>
    <div className="relative mt-4" style=${{minHeight:158}}>
      <${AnimatePresence} mode="popLayout">
      ${cur?html`<${motion.div} key=${cur.id} className="rounded-2xl p-4" style=${{background:'linear-gradient(180deg,#10261D,#0C1B15)',border:'1px solid rgba(124,242,166,.2)'}}
        initial=${{opacity:0,y:30,scale:.94}} animate=${{opacity:1,y:0,scale:1}} exit=${{opacity:0,x:-80,rotate:-4}} transition=${{type:'spring',stiffness:260,damping:24}}>
        <div className="flex items-center gap-2 mb-1.5"><span className="tag">${cur.kind}</span><span className="mono text-[11px] mint">+${cur.gain}% playoff odds</span></div>
        <div className="font-bold text-[16px] leading-snug">${cur.title}</div><div className="text-[13px] muted mt-1">${cur.sub}</div>
        <div className="mono text-[11.5px] dim mt-1">${cur.detail}</div>
        <div className="flex gap-2 mt-3.5"><button className="btn btn-mint btn-sm" onClick=${accept}>${Ico('Check',{size:14})}Accept Edge</button>
          <button className="btn btn-ghost btn-sm" onClick=${simulate}>Simulate Trade</button>
          <button className="btn btn-ghost btn-sm" onClick=${next} aria-label="Skip">Skip</button></div>
      <//>`:html`<${motion.div} key="end" className="rounded-2xl p-5 text-center" style=${{border:'1px dashed rgba(124,242,166,.3)'}} initial=${{opacity:0}} animate=${{opacity:1}}>
        <div className="font-bold">Radar clear</div><div className="text-[13px] muted mt-1">All sample moves reviewed.</div>
        <button className="btn btn-ghost btn-sm mt-3" onClick=${reset}>${Ico('RefreshCw',{size:13})}Run it again</button><//>`}
      <//>
    </div>
    <p className="text-[11px] dim mt-auto pt-3">Sample roster and sample odds. Playoff odds in the real app come from simulating your remaining schedule.</p>
  </div>`;
}

/* Card 4: ownership leverage scatter */
function Leverage(){
  const [hover,setHover]=useState(null);const [pin,setPin]=useState(null);
  const pool=SLATE.filter(p=>p.pos!=='DST');
  const W=440,H=300,pad={l:42,r:14,t:14,b:36};
  const X=o=>pad.l+(o/26)*(W-pad.l-pad.r),Y=c=>pad.t+(1-(c-18)/(38-18))*(H-pad.t-pad.b);
  const lev=p=>p.own<=10&&p.ceil>=28;
  const sel=pool.find(p=>p.id===(pin||hover));
  return html`<div className="relative z-10 flex flex-col h-full">
    <div className="eyebrow mb-2">Ownership leverage matrix</div>
    <h3 className="font-extrabold text-[22px] leading-tight tracking-tight">Find the high-ceiling players nobody owns</h3>
    <svg viewBox=${'0 0 '+W+' '+H} className="w-full mt-3" role="img" aria-label="Scatter of ownership versus ceiling">
      <rect x=${X(0)} y=${Y(38)} width=${X(10)-X(0)} height=${Y(28)-Y(38)} rx="10" fill="rgba(124,242,166,.08)" stroke="rgba(124,242,166,.35)" stroke-dasharray="4 5"/>
      <text x=${X(0)+8} y=${Y(38)+16} fill="#7CF2A6" font-size="10" font-family="JetBrains Mono">LEVERAGE ZONE</text>
      ${[0,5,10,15,20,25].map(v=>html`<g key=${'x'+v}><line x1=${X(v)} x2=${X(v)} y1=${pad.t} y2=${H-pad.b} stroke="rgba(255,255,255,.05)"/><text x=${X(v)} y=${H-18} fill="#5E7A6C" font-size="10" text-anchor="middle" font-family="JetBrains Mono">${v}%</text></g>`)}
      ${[20,25,30,35].map(v=>html`<g key=${'y'+v}><line y1=${Y(v)} y2=${Y(v)} x1=${pad.l} x2=${W-pad.r} stroke="rgba(255,255,255,.05)"/><text x=${pad.l-8} y=${Y(v)+3} fill="#5E7A6C" font-size="10" text-anchor="end" font-family="JetBrains Mono">${v}</text></g>`)}
      <text x=${(pad.l+W-pad.r)/2} y=${H-3} fill="#8FA89C" font-size="10.5" text-anchor="middle" font-family="JetBrains Mono">Projected ownership</text>
      <text transform=${`translate(11 ${(pad.t+H-pad.b)/2}) rotate(-90)`} fill="#8FA89C" font-size="10.5" text-anchor="middle" font-family="JetBrains Mono">Ceiling pts</text>
      ${pool.map((p,i)=>{const on=lev(p);const act=(pin||hover)===p.id;return html`<g key=${p.id} onMouseEnter=${()=>setHover(p.id)} onMouseLeave=${()=>setHover(null)} onClick=${()=>setPin(pin===p.id?null:p.id)} style=${{cursor:'pointer'}} tabIndex="0" role="button" aria-label=${p.name+', '+p.own+'% owned, ceiling '+p.ceil} onKeyDown=${e=>{if(e.key==='Enter')setPin(pin===p.id?null:p.id)}}>
        ${on&&html`<circle cx=${X(p.own)} cy=${Y(p.ceil)} r="7" fill="none" stroke="#7CF2A6" style=${{transformBox:'fill-box',transformOrigin:'center',animation:'pulse 2.2s infinite',animationDelay:(i%6)*.25+'s'}}/>`}
        <circle cx=${X(p.own)} cy=${Y(p.ceil)} r=${act?7:4.6} fill=${on?'#7CF2A6':'#1C5E49'} stroke=${act?'#fff':on?'#B8FFD0':'#2C7A60'} stroke-width=${act?2:1}/></g>`})}
    </svg>
    <div className="rounded-xl px-3.5 py-3 mt-2 mono text-[12.5px]" style=${{background:'rgba(255,255,255,.04)',minHeight:48}} aria-live="polite">
      ${sel?html`<span className="font-bold text-white">${sel.name}</span><span className="muted"> · ${sel.pos} · ${sel.own}% owned · ceiling ${sel.ceil} · </span><span className=${lev(sel)?'mint font-bold':'muted'}>${lev(sel)?'leverage play':'chalk'}</span>`:html`<span className="muted">Hover or tap a dot. Pulsing dots are low-owned with a high ceiling.</span>`}
    </div>
    <p className="text-[11px] dim mt-2">Sample ownership and ceilings for an illustrative slate.</p>
  </div>`;
}

function Bento({onOpenAuth}){
  const cell=(cls,child,delay=0)=>html`<${motion.div} ...${reveal} transition=${{...reveal.transition,delay}} className=${cls}>
    <${Tilt} className="card p-6 h-full" max=${5}>${child}<//><//>`;
  return html`<section id="product" className="gutter py-20 sm:py-28">
    <div className="wrap">
      <${motion.div} ...${reveal} className="max-w-[720px] mb-12">
        <div className="eyebrow mb-3">The product</div>
        <h2 className="font-extrabold tracking-[-0.03em] leading-[1.02] text-[clamp(34px,5vw,60px)]">Every decision, scored <span className="hl">before you make it</span></h2>
        <p className="text-[17px] mt-4" style=${{color:'#B6CBBF'}}>Start or sit. Pick up or pass. Trade or hold. Lineup Lab answers each one with numbers. Every card below runs live on a sample slate, so try them.</p>
      <//>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        ${cell('',html`<${StartSit} onOpenAuth=${onOpenAuth}/>`,0)}
        ${cell('',html`<${Bell}/>`,.08)}
        ${cell('',html`<${Radar}/>`,.04)}
        ${cell('',html`<${Leverage}/>`,.12)}
      </div>
    </div>
  </section>`;
}

/* how a starter compares with the best bench player who could take his slot */
function altFor(p,res){
  const bench=res.bench;
  const pool=p.slot==='FLEX'?bench.filter(b=>FLEX_POS.includes(b.pos)):bench.filter(b=>b.pos===p.pos);
  const alt=pool[0];if(!alt)return null;
  const d=p.proj-alt.proj,prob=normCdf(d/Math.sqrt(p.sd*p.sd+alt.sd*alt.sd));
  return {alt,d,prob,label:prob>=.70?'Easy start':prob>=.58?'Lean start':'Toss-up'};
}
/* ---------- SANDBOX ---------- */
function Switch({on,onChange,label}){
  return html`<button role="switch" aria-checked=${on} aria-label=${label} onClick=${()=>onChange(!on)} className="relative shrink-0" style=${{width:44,height:26,borderRadius:99,background:on?'var(--mint-2)':'rgba(255,255,255,.14)',transition:'background .2s'}}>
    <${motion.span} className="absolute rounded-full bg-white" style=${{top:3,width:20,height:20}} animate=${{left:on?21:3}} transition=${smooth}/></button>`;
}
function Sandbox({onOpenAuth}){
  const [pos,setPos]=useState('ALL');
  const [locked,setLocked]=useState(new Set());const [excl,setExcl]=useState(new Set());
  const [waiver,setWaiver]=useState(false);const [sel,setSel]=useState(null);
  const poolFor=w=>SB.filter(p=>w||!p.fa);
  const compute=(w,l,e)=>{const r=optimizeRoster(poolFor(w),l,e);if(r.error)return r;
    const base=w?optimizeRoster(poolFor(false),l,e):null;return {...r,waiverGain:base&&!base.error?r.pts-base.pts:0}};
  const init=useMemo(()=>compute(false,new Set(),new Set()),[]);
  const [res,setRes]=useState(init);const [running,setRunning]=useState(false);const [count,setCount]=useState(init.space||0);
  const list=poolFor(waiver).filter(p=>pos==='ALL'||p.pos===pos);
  const toggle=(set,setter,id,other,setOther)=>{const n=new Set(set);const was=n.has(id);was?n.delete(id):n.add(id);setter(n);if(!was&&other.has(id)){const o=new Set(other);o.delete(id);setOther(o)}setRes(null)};
  const run=()=>{if(running)return;setRunning(true);setRes(null);
    const r=compute(waiver,locked,excl);
    const target=r.error?0:r.space;const t0=performance.now();const dur=1400;
    const id=setInterval(()=>{const u=clamp((performance.now()-t0)/dur,0,1);setCount(Math.round(target*(1-Math.pow(1-u,3))));if(u>=1){clearInterval(id);setRes(r);setRunning(false)}},40)};
  const reset=()=>{setLocked(new Set());setExcl(new Set());setWaiver(false);setPos('ALL');const r=compute(false,new Set(),new Set());setRes(r);setCount(r.space)};
  return html`<section id="sandbox" className="gutter py-20 sm:py-28" style=${{background:'linear-gradient(180deg,transparent,rgba(14,50,38,.28),transparent)'}}>
    <div className="wrap">
      <${motion.div} ...${reveal} className="max-w-[760px] mb-10">
        <div className="eyebrow mb-3">Live lineup sandbox</div>
        <h2 className="font-extrabold tracking-[-0.03em] leading-[1.02] text-[clamp(34px,5vw,60px)]">Set your best lineup <span className="hl">in one click</span></h2>
        <p className="text-[17px] mt-4" style=${{color:'#B6CBBF'}}>On a sample roster, mark a player as Out, lock one in, or open the waiver wire. Lineup Lab picks the best 11 and shows the numbers behind each call: matchup, weather, range, and how often each starter beats the next man up. Tap any starter for the full breakdown.</p>
      <//>
      <${motion.div} ...${reveal} className="grid grid-cols-1 gap-5 lg:grid-cols-[1.1fr_1fr]">
        <div className="card p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-2 mb-4" role="tablist">
            ${['ALL','QB','RB','WR','TE','K','DST'].map(p=>html`<button key=${p} role="tab" aria-selected=${pos===p} className="chip" onClick=${()=>setPos(p)} style=${{color:pos===p?'#04140D':undefined}}>${pos===p&&html`<${motion.span} layoutId="posTab" className="pill-bg" transition=${smooth}/>`}<span className="relative font-bold">${p}</span></button>`)}
          </div>
          <div className="flex items-center justify-between rounded-xl px-3 py-2.5 mb-3" style=${{background:'rgba(255,255,255,.04)'}}>
            <div><div className="text-[13.5px] font-semibold">Include the waiver wire</div><div className="mono text-[11px] dim">5 low-rostered players you could add</div></div>
            <${Switch} on=${waiver} onChange=${v=>{setWaiver(v);setRes(null)}} label="Include the waiver wire"/>
          </div>
          <div style=${{maxHeight:430,overflowY:'auto'}} className="scroll-x">
            <div className="grid gap-1.5">
              <${AnimatePresence} initial=${false}>
              ${list.map(p=>{const lk=locked.has(p.id),ex=excl.has(p.id);return html`<${motion.div} layout key=${p.id} initial=${{opacity:0}} animate=${{opacity:ex?.45:1}} exit=${{opacity:0}} className="row gap-2.5 px-2.5 py-2 rounded-xl"
                style=${{gridTemplateColumns:'34px minmax(0,1fr) 44px 64px',background:lk?'rgba(124,242,166,.1)':'rgba(255,255,255,.03)',border:'1px solid '+(lk?'rgba(124,242,166,.4)':'transparent')}}>
                <span className="mono text-[10.5px] font-bold mint">${p.pos}</span>
                <div className="min-w-0"><div className="text-[13.5px] font-semibold truncate" style=${{textDecoration:ex?'line-through':'none'}}>${p.name} <span className="text-[12px]" title=${mTier(p)+' · '+wxText(p.g)}>${mEm(p)}${p.g.e}</span></div><div className="mono text-[10.5px] truncate" style=${{color:p.fa?'var(--mint)':'var(--dim)'}}>${ex?'Out this week':p.fa?'Free agent · '+p.rostered+'% rostered':'On your roster · '+p.g.vs}</div></div>
                <span className="mono text-[12.5px] font-bold text-right">${fmt(p.proj)}</span>
                <div className="flex gap-1 justify-end">
                  <button aria-pressed=${lk} aria-label=${'Always start '+p.name} title="Always start" onClick=${()=>toggle(locked,setLocked,p.id,excl,setExcl)} className="w-7 h-7 rounded-lg grid place-items-center" style=${{background:lk?'var(--mint)':'rgba(255,255,255,.06)',color:lk?'#04140D':'#9DB5A8'}}>${Ico('Lock',{size:13})}</button>
                  <button aria-pressed=${ex} aria-label=${'Mark '+p.name+' as out'} title="Mark as out" onClick=${()=>toggle(excl,setExcl,p.id,locked,setLocked)} className="w-7 h-7 rounded-lg grid place-items-center" style=${{background:ex?'var(--bad)':'rgba(255,255,255,.06)',color:ex?'#1a0505':'#9DB5A8'}}>${Ico('Ban',{size:13})}</button>
                </div><//>`})}
              <//>
            </div>
          </div>
          <div className="flex items-center justify-between mt-3 mono text-[11.5px] muted"><span>${locked.size} always start · ${excl.size} out</span><button className="mint underline" onClick=${reset}>Reset</button></div>
        </div>
        <div className="card p-5 sm:p-6 flex flex-col">
          <button className="btn btn-mint w-full" onClick=${run} disabled=${running} style=${{opacity:running?.8:1}}>${running?html`<span>Checking every legal lineup…</span>`:html`${Ico('Sparkles',{size:16})}Set My Best Lineup`}</button>
          <div className="mono text-[12px] muted mt-3 flex justify-between"><span>Lineups checked</span><${Ticker} value=${count} decimals=${0} className="mint font-bold"/></div>
          <div className="relative h-[3px] rounded-full mt-2 overflow-hidden" style=${{background:'rgba(255,255,255,.08)'}}>
            ${running&&html`<${motion.div} className="absolute inset-y-0 w-1/3 rounded-full" style=${{background:'linear-gradient(90deg,transparent,#7CF2A6,transparent)'}} animate=${{left:['-35%','100%']}} transition=${{duration:.9,repeat:Infinity,ease:'linear'}}/>`}</div>
          <div className="mt-5 flex-1" style=${{minHeight:380}} aria-live="polite">
            ${!res&&!running&&html`<div className="h-full grid place-items-center text-center rounded-2xl p-6" style=${{border:'1px dashed rgba(124,242,166,.25)',minHeight:300}}><div><div className="font-bold">Your best 11 land here</div><div className="text-[13px] muted mt-1">You changed something. Press the button to re-check every lineup.</div></div></div>`}
            ${res&&res.error&&html`<div className="rounded-2xl p-4 text-[14px]" style=${{border:'1px solid rgba(255,122,122,.4)',background:'rgba(255,122,122,.07)',color:'#FFB4B4'}} role="alert">${res.error}</div>`}
            ${res&&!res.error&&(()=>{
              const edges=Object.fromEntries(res.players.map(p=>[p.id,altFor(p,res)]));
              const close=res.players.filter(p=>edges[p.id]).sort((x,y)=>Math.abs(edges[x.id].prob-.5)-Math.abs(edges[y.id].prob-.5))[0];
              const cur=res.players.find(p=>p.id===sel)||close||res.players[0];const ce=edges[cur.id];
              return html`<div>
              ${close&&html`<div className="rounded-xl px-3 py-2 mb-2 text-[12.5px]" style=${{background:'rgba(245,194,107,.09)',border:'1px solid rgba(245,194,107,.35)'}}><span style=${{color:'var(--warn)'}} className="font-bold">Closest call:</span> <span className="muted">${close.name} over ${edges[close.id].alt.name}, ${Math.round(edges[close.id].prob*100)}% to outscore him</span></div>`}
              <div className="grid gap-1">
                ${res.players.map((p,i)=>{const e=edges[p.id];const on=p.id===cur.id;return html`<${motion.button} key=${p.id} onClick=${()=>setSel(p.id)} aria-pressed=${on} initial=${{opacity:0,x:24}} animate=${{opacity:1,x:0}} transition=${{delay:i*.04,type:'spring',stiffness:240,damping:22}} className="row gap-2 px-3 py-1.5 rounded-lg text-left" style=${{gridTemplateColumns:'44px minmax(0,1fr) auto',background:on?'rgba(124,242,166,.13)':p.fa?'rgba(124,242,166,.07)':'rgba(255,255,255,.04)',border:'1px solid '+(on?'rgba(124,242,166,.55)':p.fa?'rgba(124,242,166,.25)':'transparent'),cursor:'pointer'}}>
                  <span className="mono text-[10.5px] font-bold mint">${p.slot}</span>
                  <span className="min-w-0"><span className="block text-[13.5px] font-semibold truncate">${p.name}${locked.has(p.id)?html` <span className="mono text-[10px] mint">locked</span>`:''}${p.fa?html` <span className="tag" style=${{marginLeft:4,color:'var(--mint)',borderColor:'rgba(124,242,166,.4)'}}>Add</span>`:''}</span>
                    <span className="block mono text-[10.5px] dim truncate">${mEm(p)} ${p.g.vs} · ${p.g.e} ${p.g.dome?'dome':p.g.t+'°'}${e?' · '+Math.round(e.prob*100)+'% over '+e.alt.name.split(' ').slice(-1)[0]:''}</span></span>
                  <span className="text-right"><span className="block mono text-[13px] font-bold">${fmt(p.proj)}</span><span className="block mono text-[10px] dim">${fmt(p.floor,0)}–${fmt(p.ceil,0)}</span></span><//>`})}
              </div>
              <${AnimatePresence} mode="wait"><${motion.div} key=${cur.id} initial=${{opacity:0,y:8}} animate=${{opacity:1,y:0}} exit=${{opacity:0}} transition=${{duration:.2}} className="rounded-2xl p-4 mt-3" style=${{background:'linear-gradient(180deg,#10261D,#0C1B15)',border:'1px solid rgba(124,242,166,.22)'}}>
                <div className="flex items-baseline justify-between gap-3"><div className="font-bold text-[15px] truncate">Why ${cur.name} ${cur.slot==='K'||cur.slot==='DST'?'is your '+cur.slot:'starts'}</div>${ce&&html`<span className="tag shrink-0" style=${{color:ce.prob>=.58?'var(--mint)':'var(--warn)',borderColor:ce.prob>=.58?'rgba(124,242,166,.4)':'rgba(245,194,107,.5)'}}>${ce.label}</span>`}</div>
                <div className="mono text-[12px] mt-2.5 leading-relaxed">
                  <div><span className="dim">Base</span> ${fmt(cur.base)} <span className="dim">·</span> <span className=${cur.mu>=0?'mint':''} style=${{color:cur.mu<0?'var(--bad)':undefined}}>${mEm(cur)} matchup ${sgn(cur.mu)}</span> <span className="dim">·</span> <span style=${{color:cur.wx<0?'var(--bad)':undefined}}>${cur.g.e} weather ${sgn(cur.wx)}</span> <span className="dim">=</span> <span className="font-bold mint">${fmt(cur.proj)}</span></div>
                  <div className="muted mt-1">${mTier(cur)}: ranks ${cur.rank} of 32 for this position (32 = softest)</div>
                  <div className="muted">${cur.g.vs} · ${wxText(cur.g)}</div>
                  <div className="muted">Range ${fmt(cur.floor,0)} to ${fmt(cur.ceil,0)} points${cur.fa?' · rostered in '+cur.rostered+'% of leagues':''}</div>
                  ${ce?html`<div className="mt-1.5">${ce.d>=0?'+'+fmt(ce.d)+' pts over ':fmt(ce.d)+' pts vs. '}<span className="font-bold text-white">${ce.alt.name}</span>${ce.d<0?' (you locked him in)':''}. He outscores him in ${Math.round(ce.prob*100)} of 100 simulated games.</div>`:html`<div className="mt-1.5 dim">No other ${cur.slot==='FLEX'?'flex player':cur.pos} on your bench to compare.</div>`}
                </div>
              <//><//>
              <div className="grid grid-cols-2 gap-3 mt-4">
                <div><div className="eyebrow">Projected total</div><${Ticker} value=${res.pts} className="text-[26px] font-bold mint"/></div>
                <div><div className="eyebrow">On the bench</div><div className="mono text-[13px] muted mt-1 leading-snug">${res.bench.length?res.bench.slice(0,4).map(p=>p.name.split(' ').slice(-1)[0]).join(', ')+(res.bench.length>4?' +'+(res.bench.length-4):''):'Nobody'}</div></div>
              </div>
              ${waiver&&html`<div className="mono text-[12px] mint mt-3">${res.waiverGain>0.05?'The waiver wire adds +'+fmt(res.waiverGain)+' projected points.':'No free agent beats your roster here.'}</div>`}
              </div>`
            })()}
            ${res&&!res.error&&html`<div>
              <button className="btn btn-ghost w-full mt-4" onClick=${()=>onOpenAuth('signup')}>Do this for my real league ${Ico('ArrowRight',{size:15})}</button>
            </div>`}
          </div>
        </div>
      <//>
      <p className="text-[12px] dim mt-4">Sample roster. Matchups, weather and projections are illustrative, not this week's real data. Starting lineup: 1 QB, 2 RB, 3 WR, 1 TE, 2 FLEX (RB, WR or TE), 1 K and 1 DST.</p>
    </div>
  </section>`;
}

/* ---------- EDGES (what is real) ---------- */
function Edges(){
  const items=[
   ['Layers','Sleeper & ESPN sync','Connect a Sleeper username or an ESPN league and see your own roster, scoring and standings.'],
   ['Gauge','Start/Sit with a track record','Every pick is saved and graded after the games, so you can see how the calls actually did.'],
   ['Radar','Needs-aware trades','Trade suggestions look at what your roster is missing, not just raw point totals.'],
   ['Timer','Fast on big slates','Pre-loaded NFL data, so the boards and waiver lists open in a fraction of a second.']];
  return html`<section id="edges" className="gutter py-16 sm:py-24">
    <div className="wrap grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      ${items.map(([ic,t,d],i)=>html`<${motion.div} key=${t} ...${reveal} transition=${{...reveal.transition,delay:i*.07}}>
        <${Tilt} className="card p-5 h-full" max=${6}><div className="relative z-10">
          <div className="w-10 h-10 rounded-xl grid place-items-center mb-4" style=${{background:'linear-gradient(180deg,#1C5E49,#0E3226)',border:'1px solid rgba(124,242,166,.3)'}}>${Ico(ic,{size:18,color:'#7CF2A6'})}</div>
          <div className="font-bold text-[16px]">${t}</div><p className="muted text-[14px] mt-1.5">${d}</p></div><//>
      <//>`)}
    </div>
  </section>`;
}

/* ---------- PRICING ---------- */
const PLANS=[
  {id:'free',name:'Free',price:'$0',per:'forever',leagues:'Sync up to 2 leagues',blurb:'For anyone with one or two teams. Everything on this page, no card needed.',cta:'Start Free'},
  {id:'manager',name:'Manager',price:'$6',per:'/month',yearly:'or $60 a year, two months free',leagues:'Sync 3 to 4 leagues',blurb:'For people juggling a few teams who need every lineup set in minutes.',cta:'Join the waitlist',featured:true},
  {id:'commissioner',name:'Commissioner',price:'$12',per:'/month',yearly:'or $120 a year, two months free',leagues:'Sync 5 or more leagues',blurb:'For the player in a dozen leagues. No cap on how many you connect.',cta:'Join the waitlist'}];
function Waitlist({plan}){
  const [email,setEmail]=useState('');const [st,setSt]=useState('idle');const [msg,setMsg]=useState('');
  const submit=async e=>{e.preventDefault();
    if(!/^\S+@\S+\.\S+$/.test(email)){setSt('err');setMsg('Enter an email like you@school.edu.');return}
    setSt('busy');setMsg('');
    try{const r=await fetch('/api/waitlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email.trim(),plan})});
      if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.detail||'Something went wrong. Try again in a minute.')}
      setSt('done')}catch(x){setSt('err');setMsg(x.message)}};
  if(st==='done')return html`<div className="text-[14px] font-semibold mint" role="status">You are on the list. We will email you when this plan opens.</div>`;
  return html`<form onSubmit=${submit} noValidate className="grid gap-2.5">
    <label className="sr-only" htmlFor=${'wl-'+plan}>Email for the ${plan} plan waitlist</label>
    <input id=${'wl-'+plan} className="field" type="email" placeholder="you@email.com" value=${email} onChange=${e=>setEmail(e.target.value)} autoComplete="email"/>
    <button type="submit" className="btn btn-ghost w-full" disabled=${st==='busy'}>${st==='busy'?'Saving…':'Join the waitlist'}</button>
    ${st==='err'&&html`<div className="text-[13px]" style=${{color:'var(--bad)'}} role="alert">${msg}</div>`}
  </form>`;
}
function Pricing({onOpenAuth}){
  return html`<section id="pricing" className="gutter py-16 sm:py-24">
    <div className="wrap">
      <div className="max-w-[680px] mb-10"><div className="eyebrow mb-3">Plans for every league count</div>
        <h2 className="font-extrabold tracking-[-0.03em] leading-[1.04] text-[clamp(30px,4.6vw,52px)]">Same tools on every plan. <span className="hl">Pay only if you run a lot of teams.</span></h2>
        <p className="muted text-[16px] mt-4">Start free with two leagues. If you manage more, the paid plans raise how many leagues you can sync. The paid plans are not open yet: join the waitlist and we will email you first.</p></div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3 items-stretch">
        ${PLANS.map((p,i)=>html`<${motion.div} key=${p.id} ...${reveal} transition=${{...reveal.transition,delay:i*.08}} className="h-full">
          <div className="card p-6 sm:p-7 h-full flex flex-col" style=${p.featured?{borderColor:'rgba(124,242,166,.45)',boxShadow:'0 30px 90px -30px rgba(74,222,128,.35)'}:null}>
            <div className="flex items-center justify-between mb-5"><div className="font-extrabold text-[20px]">${p.name}</div>${p.id!=='free'?html`<span className="tag">Coming soon</span>`:null}</div>
            <div className="flex items-end gap-1.5"><span className="font-extrabold tracking-[-0.03em] text-[48px] leading-none">${p.price}</span><span className="muted text-[14px] pb-1.5">${p.per}</span></div>
            <div className="dim text-[12.5px] mt-1.5 min-h-[18px]">${p.yearly||''}</div>
            <div className="mt-5 flex items-center gap-2.5 font-bold text-[15px]">${Ico('Layers',{size:17,color:'#7CF2A6'})}${p.leagues}</div>
            <p className="muted text-[14px] mt-3 mb-6">${p.blurb}</p>
            <div className="mt-auto">${p.id==='free'?html`<${Magnetic} className="btn btn-mint w-full" onClick=${()=>onOpenAuth('signup')}>${p.cta} ${Ico('ArrowRight',{size:16})}<//>`:html`<${Waitlist} plan=${p.id}/>`}</div>
          </div><//>`)}
      </div>
      <p className="dim text-[12.5px] mt-5">Prices are in US dollars and may change before the paid plans open.</p>
    </div>
  </section>`;
}

/* ---------- FINAL CTA + FOOTER ---------- */
function Final({onOpenAuth}){
  return html`<section className="gutter pb-20"><${motion.div} ...${reveal} className="wrap relative rounded-[32px] overflow-hidden px-6 sm:px-14 py-16 sm:py-24 text-center" style=${{border:'1px solid rgba(124,242,166,.25)',background:'radial-gradient(70% 90% at 50% 120%,rgba(74,222,128,.42),rgba(28,94,73,.35) 40%,rgba(11,24,19,.95) 75%)'}}>
    <div className="absolute inset-0 pointer-events-none" style=${{background:'radial-gradient(40% 60% at 50% 0%,rgba(124,242,166,.14),transparent 70%)'}} aria-hidden="true"></div>
    <div className="relative">
      <div className="inline-flex mb-6"><${Logo} size=${64}/></div>
      <h2 className="font-extrabold tracking-[-0.03em] leading-[1.02] text-[clamp(32px,5.4vw,64px)] max-w-[800px] mx-auto">Sync your league in 30 seconds. <span className="hl">Start winning Sunday.</span></h2>
      <p className="text-[17px] mt-5 max-w-[520px] mx-auto" style=${{color:'#C3D8CC'}}>Connect Sleeper or ESPN, and Lineup Lab builds your first optimal lineup right away.</p>
      <div className="flex flex-wrap justify-center gap-3 mt-9">
        <${Magnetic} className="btn btn-mint" onClick=${()=>onOpenAuth('signup')}>Start Free ${Ico('ArrowRight',{size:16})}<//>
        <a className="btn btn-ghost no-underline" href=${APP_URL}>Open the live app</a>
      </div>
    </div>
  <//></section>`;
}
function Footer(){
  return html`<footer className="gutter pb-12"><div className="wrap pt-8 flex flex-wrap items-center justify-between gap-4" style=${{borderTop:'1px solid rgba(255,255,255,.07)'}}>
    <div className="flex items-center gap-2.5"><${Logo} size=${28}/><span className="font-extrabold">Lineup Lab</span></div>
    <div className="mono text-[12px] dim max-w-[560px]">Lineup Lab is an independent fantasy football tool. Not affiliated with the NFL, Sleeper, ESPN or Yahoo. Numbers on this page come from a sample slate.</div>
    <div className="flex gap-5 text-[13px]"><a className="muted no-underline hover:text-white" href="#product">Product</a><a className="muted no-underline hover:text-white" href="#sandbox">Try it</a><a className="muted no-underline hover:text-white" href="/play">Play The Daily Drive</a><a className="muted no-underline hover:text-white" href=${APP_URL}>Open app</a></div>
  </div></footer>`;
}

/* ---------- APP ---------- */
function App(){
  const user=null;
  const open=m=>{window.location.href='/?auth='+(m==='signup'?'signup':'login')};
  return html`<${MotionConfig} reducedMotion="user">
    <${Nav} user=${user} onOpenAuth=${open} onLogout=${()=>{}}/>
    <main>
      <${Hero}/><${Ticker2}/><${Bento} onOpenAuth=${open}/><${Sandbox} onOpenAuth=${open}/><${Edges}/><${Pricing} onOpenAuth=${open}/><${Final} onOpenAuth=${open}/>
    </main>
    <${Footer}/>
  <//>`;
}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
})();
