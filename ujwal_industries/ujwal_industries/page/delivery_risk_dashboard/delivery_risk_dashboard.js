// Delivery Risk Dashboard — bold colors, big fonts, drill-down panels

frappe.pages['delivery_risk_dashboard'].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: 'Sales Order Tracker', single_column: true });
	page.add_inner_button('Refresh', () => window.location.reload());
	new DeliveryRiskDashboard(wrapper, page);
};

class DeliveryRiskDashboard {
	constructor(wrapper, page) { this.wrapper = wrapper; this.page = page; this.init(); }
	init() { this.addStyles(); this.loadDependencies().then(() => this.renderApp()); }
	addStyles() {
		if (document.getElementById('drd-styles')) return;
		const s = document.createElement('style');
		s.id = 'drd-styles';
		s.textContent = `
			@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
			@keyframes pop  { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
			.drd-filter-input:focus { border-color:#f59e0b!important; box-shadow:0 0 0 2px rgba(245,158,11,.2)!important; }
			.drd-card { transition:transform .15s,box-shadow .15s; }
			.drd-card:hover { transform:translateY(-2px); box-shadow:0 10px 28px rgba(0,0,0,.22)!important; }
			.drd-wo-row { transition:background .12s,border-color .12s; }
			.drd-wo-row:hover { background:#fef9ec!important; }
		`;
		document.head.appendChild(s);
	}
	loadDependencies() {
		return new Promise(resolve => {
			if (window.React && window.ReactDOM) { resolve(); return; }
			let n = 0; const done = () => { if (++n===2) resolve(); };
			['react@18/umd/react.production.min.js','react-dom@18/umd/react-dom.production.min.js'].forEach(lib => {
				const s = document.createElement('script');
				s.src = `https://unpkg.com/${lib}`; s.crossOrigin = 'anonymous'; s.onload = done;
				document.head.appendChild(s);
			});
		});
	}
	renderApp() {
		const c = document.createElement('div');
		c.id = 'drd-root';
		this.wrapper.querySelector('.page-content').appendChild(c);
		ReactDOM.createRoot(c).render(React.createElement(DRDApp));
	}
}

// ─── Production Status ────────────────────────────────────────────────────────
const P = {
	'OVERDUE':       { label:'OVERDUE',       color:'#b91c1c', bg:'#fee2e2', border:'#f87171', cardBg:'#fff5f5', icon:'🚨' },
	'DELIVERY RISK': { label:'DELIVERY RISK', color:'#92400e', bg:'#fef3c7', border:'#fbbf24', cardBg:'#fffbeb', icon:'⚠️' },
	'ON HOLD':       { label:'ON HOLD',       color:'#6d28d9', bg:'#ede9fe', border:'#a78bfa', cardBg:'#faf5ff', icon:'⏸️' },
	'ON TRACK':      { label:'ON TRACK',      color:'#065f46', bg:'#d1fae5', border:'#34d399', cardBg:'#f0fdf4', icon:'✅' },
	'COMPLETED':     { label:'COMPLETED',     color:'#0e7490', bg:'#cffafe', border:'#22d3ee', cardBg:'#ecfeff', icon:'🏁' },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmtDate(d) {
	if (!d || d==='None'||d==='null'||d==='') return '—';
	const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
	const pt = String(d).split(' ')[0].split('T')[0].split('-');
	if (pt.length<3) return '—';
	const [y,m,day] = [parseInt(pt[0]),parseInt(pt[1])-1,parseInt(pt[2])];
	return isNaN(y)?'—':`${day} ${mo[m]} ${y}`;
}
function fmtRs(v) { return '₹'+Number(v||0).toLocaleString('en-IN',{maximumFractionDigits:0}); }
function pf(v) { return parseFloat(v)||0; }
function woColor(s) {
	if (s==='Completed')   return {bg:'#d1fae5',text:'#065f46',dot:'#10b981'};
	if (s==='In Process')  return {bg:'#dbeafe',text:'#1e40af',dot:'#3b82f6'};
	if (s==='Not Started') return {bg:'#f3f4f6',text:'#6b7280',dot:'#9ca3af'};
	if (s==='Stopped')     return {bg:'#fee2e2',text:'#991b1b',dot:'#dc2626'};
	return {bg:'#fef3c7',text:'#92400e',dot:'#f59e0b'};
}
function jcColor(s) {
	if (s==='Completed') return {bg:'#d1fae5',text:'#065f46',dot:'#10b981'};
	if (s==='Working')   return {bg:'#dbeafe',text:'#1e40af',dot:'#3b82f6'};
	if (s==='On Hold')   return {bg:'#fee2e2',text:'#991b1b',dot:'#ef4444'};
	if (s==='Open')      return {bg:'#ede9fe',text:'#5b21b6',dot:'#8b5cf6'};
	return {bg:'#f3f4f6',text:'#374151',dot:'#9ca3af'};
}
function bar(pct, h, radius) {
	const c = pct>=80?'#10b981':pct>=40?'#f59e0b':'#ef4444';
	return React.createElement('div', {style:{height:h||8,background:'#e5e7eb',borderRadius:radius||4,overflow:'hidden'}},
		React.createElement('div', {style:{height:'100%',width:`${pct}%`,background:c,borderRadius:radius||4,transition:'width .4s'}}));
}

// ─── App ──────────────────────────────────────────────────────────────────────
function DRDApp() {
	const {useState,useEffect,useRef,useCallback} = React;
	// screen: 'overview' | 'list'
	const [screen,setScreen]           = useState('overview');
	const [orders,setOrders]           = useState([]);
	const [loading,setLoading]         = useState(true);
	const [loadingMore,setLoadingMore] = useState(false);
	const [hasMore,setHasMore]         = useState(false);
	const [offset,setOffset]           = useState(0);
	const [selectedSO,setSelectedSO]   = useState(null);
	const [openWOs,setOpenWOs]         = useState([]);

	const EMPTY = {so:'',customer:'',from_date:'',to_date:'',priority:'',planning:''};
	const [filterInputs,setFilterInputs] = useState(EMPTY);
	const [activeFilters,setActiveFilters] = useState({});

	const sentinelRef = useRef(null);
	const PAGE = 12;

	const applyFilters = (data, f) => {
		let d = data;
		if (f.so)        { const q=f.so.toLowerCase();       d=d.filter(o=>o.name.toLowerCase().includes(q)); }
		if (f.customer)  { const q=f.customer.toLowerCase(); d=d.filter(o=>(o.customer||'').toLowerCase().includes(q)||(o.customer_name||'').toLowerCase().includes(q)); }
		if (f.from_date) { d=d.filter(o=>o.expected_date>=f.from_date); }
		if (f.to_date)   { d=d.filter(o=>o.expected_date<=f.to_date); }
		if (f.priority)  { d=d.filter(o=>o.priority===f.priority); }
		if (f.planning==='planned')     { d=d.filter(o=>o.has_pp); }
		if (f.planning==='not_planned') { d=d.filter(o=>!o.has_pp); }
		return d;
	};

	useEffect(() => {
		if (screen !== 'list') return;
		setOrders([]); setOffset(0); setHasMore(false); setLoading(true);
		// Fetch completed SOs from backend only when navigating to Completed filter
		const needsCompleted = activeFilters.priority === 'COMPLETED';
		frappe.call({
			method:'ujwal_industries.api.sales_order_tracker.get_so_list',
			args:{include_completed: needsCompleted ? 1 : 0},
			callback:(r)=>{
				if (r.message) {
					const filtered = applyFilters(r.message, activeFilters);
					setOrders(filtered.slice(0,PAGE));
					setHasMore(filtered.length>PAGE);
					setOffset(PAGE);
					window._drdAll = filtered;
				}
				setLoading(false);
			}
		});
	}, [activeFilters, screen]);

	const fetchMore = useCallback(()=>{
		if (loadingMore||!hasMore||!window._drdAll) return;
		setLoadingMore(true);
		const next = window._drdAll.slice(offset, offset+PAGE);
		setOrders(p=>[...p,...next]);
		setHasMore(window._drdAll.length>offset+PAGE);
		setOffset(p=>p+PAGE);
		setLoadingMore(false);
	},[loadingMore,hasMore,offset]);

	useEffect(()=>{
		if (!sentinelRef.current) return;
		const obs = new IntersectionObserver(e=>{ if(e[0].isIntersecting&&hasMore&&!loadingMore) fetchMore(); },{threshold:0});
		obs.observe(sentinelRef.current);
		return ()=>obs.disconnect();
	},[hasMore,loadingMore,fetchMore]);

	const addWO    = useCallback(n=>setOpenWOs(p=>p.includes(n)?p:[n,...p]),[]);
	const removeWO = useCallback(n=>setOpenWOs(p=>p.filter(x=>x!==n)),[]);
	const pickSO   = o=>{ setSelectedSO(o); setOpenWOs([]); };
	const back     = ()=>{ setSelectedSO(null); setOpenWOs([]); };
	const openSet  = new Set(openWOs);

	// Navigate from overview to list with a pre-set filter
	const goToList = useCallback((priorityFilter, planningFilter)=>{
		const filters = {};
		if (priorityFilter) filters.priority  = priorityFilter;
		if (planningFilter) filters.planning   = planningFilter;
		setFilterInputs({...EMPTY, ...filters});
		setActiveFilters(filters);
		setSelectedSO(null); setOpenWOs([]);
		setScreen('list');
	},[]);

	const wrapStyle = {minHeight:'100vh',background:'#F2F4F6',padding:'20px',margin:'-15px',width:'calc(100% + 30px)'};

	if (screen === 'overview') {
		return React.createElement('div',{style:wrapStyle},
			React.createElement(OverviewScreen,{onNavigate:goToList})
		);
	}

	return React.createElement('div',{style:wrapStyle},[
		// Back to overview button
		React.createElement('div',{key:'nav',style:{marginBottom:'12px',display:'flex',alignItems:'center',gap:'10px'}}, [
			React.createElement('button',{key:'back',onClick:()=>setScreen('overview'),style:{background:'white',border:'1px solid #e2e8f0',color:'#374151',borderRadius:'8px',padding:'6px 14px',fontSize:'13px',fontWeight:'700',cursor:'pointer',boxShadow:'0 1px 3px rgba(0,0,0,.06)'}},'← Dashboard'),
			activeFilters.priority && React.createElement('span',{key:'badge',style:{fontSize:'12px',fontWeight:'800',padding:'3px 10px',borderRadius:'20px',background:(P[activeFilters.priority]||{}).bg||'#e5e7eb',color:(P[activeFilters.priority]||{}).color||'#374151'}},
				`${(P[activeFilters.priority]||{}).icon||''} ${activeFilters.priority}`
			),
			activeFilters.planning && React.createElement('span',{key:'plan-badge',style:{fontSize:'12px',fontWeight:'800',padding:'3px 10px',borderRadius:'20px',background:'#D3EADA',color:'#2d6b4a'}},
				activeFilters.planning==='planned' ? '📅 PLANNED' : '📝 NOT PLANNED'
			)
		]),
		React.createElement(Filters,{key:'f',filterInputs,setFilterInputs,onApply:()=>setActiveFilters({...filterInputs}),onClear:()=>{setFilterInputs(EMPTY);setActiveFilters({});}}),

		selectedSO
		? React.createElement('div',{key:'split',style:{display:'flex',gap:'16px',alignItems:'flex-start',flexWrap:'wrap'}}, [
			React.createElement('div',{key:'L',style:{flex:'0 0 380px',minWidth:'300px',position:'sticky',top:'20px',maxHeight:'calc(100vh - 120px)',overflowY:'auto',borderRadius:'12px',scrollbarWidth:'thin'}},
				React.createElement(SOPanel,{soData:selectedSO,onBack:back,onToggle:addWO,openSet})),
			React.createElement('div',{key:'R',style:{flex:'1 1 400px',minWidth:'300px',display:'flex',flexDirection:'column',gap:'12px'}},
				openWOs.length===0
				? React.createElement(WOHint,{key:'hint'})
				: openWOs.map(n=>React.createElement(WOPanel,{key:n,woName:n,onClose:()=>removeWO(n)}))
			)
		])
		: React.createElement('div',{key:'list'},[
			loading ? React.createElement(Spinner,{key:'sp'}) :
			orders.length===0 ? React.createElement(Empty,{key:'em'}) :
			React.createElement('div',{key:'cards',style:{display:'flex',flexDirection:'column',gap:'10px'}},
				orders.map(o=>React.createElement(SOCard,{key:o.name,order:o,onClick:()=>pickSO(o)}))
			),
			!loading && React.createElement('div',{key:'pg'},[
				React.createElement('div',{key:'s',ref:sentinelRef,style:{height:'8px'}}),
				loadingMore && React.createElement('div',{key:'lm',style:{textAlign:'center',padding:'16px',color:'#94a3b8',fontSize:'14px'}}, 'Loading more...'),
				!hasMore&&orders.length>0 && React.createElement('div',{key:'end',style:{textAlign:'center',padding:'14px',fontSize:'13px',color:'#94a3b8'}},`All ${orders.length} orders shown`)
			])
		])
	]);
}

// ─── Overview Screen ──────────────────────────────────────────────────────────
function OverviewScreen({onNavigate}) {
	const {useState,useEffect,useCallback} = React;
	const [data,setData]       = useState(null);
	const [loading,setLoading] = useState(true);
	const [df,setDf]           = useState({range:'all',from_date:'',to_date:''});

	const presets = useCallback(range=>{
		const t=new Date();
		// Use local date parts to avoid UTC-shift bug (toISOString converts to UTC)
		const fmt=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
		if(range==='week'){const s=new Date(t);s.setDate(t.getDate()-t.getDay());const e=new Date(s);e.setDate(s.getDate()+6);return{from_date:fmt(s),to_date:fmt(e)};}
		if(range==='month'){return{from_date:fmt(new Date(t.getFullYear(),t.getMonth(),1)),to_date:fmt(new Date(t.getFullYear(),t.getMonth()+1,0))};}
		if(range==='quarter'){const q=Math.floor(t.getMonth()/3);return{from_date:fmt(new Date(t.getFullYear(),q*3,1)),to_date:fmt(new Date(t.getFullYear(),q*3+3,0))};}
		if(range==='year'){return{from_date:`${t.getFullYear()}-01-01`,to_date:`${t.getFullYear()}-12-31`};}
		return{from_date:'',to_date:''};
	},[]);

	useEffect(()=>{
		setLoading(true); setData(null);
		frappe.call({
			method:'ujwal_industries.api.sales_order_tracker.get_so_overview',
			args:{from_date:df.from_date||null,to_date:df.to_date||null},
			callback:r=>{ if(r.message) setData(r.message); setLoading(false); }
		});
	},[df]);

	if (loading) return React.createElement('div',{style:{textAlign:'center',paddingTop:'80px'}},React.createElement(Spinner));
	if (!data)   return React.createElement(Empty);

	const prod = data.production||{};
	const plan = data.planning||{};

	// Grand total = active + completed — both pies must sum to this
	const grandTotal = (data.total_active||0) + (data.completed||0);

	const prodPieData = [
		{label:'Overdue',       value:prod['OVERDUE']||0,       color:'#f87171', key:'OVERDUE'},
		{label:'Delivery Risk', value:prod['DELIVERY RISK']||0, color:'#fbbf24', key:'DELIVERY RISK'},
		{label:'On Hold',       value:prod['ON HOLD']||0,       color:'#a78bfa', key:'ON HOLD'},
		{label:'On Track',      value:prod['ON TRACK']||0,      color:'#34d399', key:'ON TRACK'},
		{label:'Completed',     value:data.completed||0,        color:'#22d3ee', key:'COMPLETED'},
	].filter(d=>d.value>0);

	// not_planned = active - planned; adding completed keeps planning total = grandTotal
	const planNotPlanned = Math.max(0,(data.total_active||0)-(plan.planned||0));
	const planPieData = [
		{label:'Planned',     value:plan.planned||0,   color:'#60a5fa', key:'planned'},
		{label:'Not Planned', value:planNotPlanned,     color:'#94a3b8', key:'not_planned'},
		{label:'Completed',   value:data.completed||0, color:'#22d3ee', key:'completed'},
	].filter(d=>d.value>0);

	const mkCard = (key,icon,label,val,sub,bg,onClick)=>React.createElement('div',{
		key,
		style:{background:bg||'white',borderRadius:'12px',padding:'14px 16px',textAlign:'center',cursor:onClick?'pointer':'default',border:'1px solid rgba(0,0,0,.08)',boxShadow:'0 1px 4px rgba(0,0,0,.06)',transition:'transform .15s,box-shadow .15s',flex:'1 1 100px',minWidth:'90px'},
		onClick,
		onMouseEnter:e=>onClick&&(e.currentTarget.style.transform='translateY(-3px)',e.currentTarget.style.boxShadow='0 8px 20px rgba(0,0,0,.12)'),
		onMouseLeave:e=>onClick&&(e.currentTarget.style.transform='translateY(0)',e.currentTarget.style.boxShadow='0 1px 4px rgba(0,0,0,.06)')
	},[
		React.createElement('div',{key:'ic',style:{fontSize:'22px',marginBottom:'4px'}},icon),
		React.createElement('div',{key:'v',style:{fontSize:'26px',fontWeight:'900',color:'#1e293b',lineHeight:1.1}},val),
		React.createElement('div',{key:'l',style:{fontSize:'11px',fontWeight:'700',color:'#64748b',marginTop:'3px'}},label),
		sub&&React.createElement('div',{key:'s',style:{fontSize:'10px',color:'#94a3b8',marginTop:'1px'}},sub)
	]);

	const sectionHdr = (icon,title,sub,iconBg)=>React.createElement('div',{
		key:'hdr',
		style:{display:'flex',alignItems:'center',gap:'10px',marginBottom:'16px',paddingBottom:'12px',borderBottom:'1px solid #e2e8f0'}
	},[
		React.createElement('span',{key:'ic',style:{fontSize:'18px',background:iconBg,borderRadius:'8px',padding:'7px 9px',lineHeight:1}},icon),
		React.createElement('div',{key:'txt'},[
			React.createElement('h3',{key:'t',style:{color:'#1e293b',fontSize:'15px',fontWeight:'800',margin:0}},title),
			React.createElement('p',{key:'s',style:{color:'#94a3b8',fontSize:'11px',margin:'2px 0 0'}},sub)
		])
	]);

	const RANGES=[{r:'all',l:'All'},{r:'week',l:'This Week'},{r:'month',l:'This Month'},{r:'quarter',l:'This Quarter'},{r:'year',l:'This Year'}];
	const inpStyle={height:'30px',padding:'0 8px',borderRadius:'6px',border:'1px solid #e2e8f0',background:'white',color:'#374151',fontSize:'12px',outline:'none',colorScheme:'light'};

	return React.createElement('div',{},[
		React.createElement('div',{key:'title',style:{marginBottom:'14px'}},[
			React.createElement('h2',{key:'h',style:{color:'#1e293b',fontSize:'22px',fontWeight:'800',margin:0}},'📊 Sales Order Dashboard'),
			React.createElement('p',{key:'s',style:{color:'#64748b',fontSize:'13px',margin:'4px 0 0'}},'Click any tile or chart segment to drill into the list')
		]),

		// ── Date Filter Bar ──
		React.createElement('div',{key:'filterbar',style:{background:'white',borderRadius:'12px',padding:'12px 18px',marginBottom:'18px',border:'1px solid #e2e8f0',boxShadow:'0 1px 4px rgba(0,0,0,.05)',display:'flex',alignItems:'center',gap:'8px',flexWrap:'wrap'}},[
			React.createElement('span',{key:'lbl',style:{fontSize:'11px',fontWeight:'700',color:'#94a3b8',letterSpacing:'.5px',marginRight:'4px'}},'DELIVERY DATE'),
			...RANGES.map(({r,l})=>{
				const active=df.range===r;
				return React.createElement('button',{key:r,onClick:()=>setDf({range:r,...presets(r)}),style:{padding:'5px 13px',borderRadius:'20px',fontSize:'12px',fontWeight:'700',cursor:'pointer',border:active?'1px solid #c9a84c':'1px solid #e2e8f0',background:active?'#F2D894':'transparent',color:active?'#713f12':'#64748b',transition:'all .15s'}},l);
			}),
			React.createElement('div',{key:'range',style:{display:'flex',gap:'6px',alignItems:'center',marginLeft:'auto'}},[
				React.createElement('input',{key:'fd',type:'date',value:df.from_date,onChange:e=>setDf({range:'custom',from_date:e.target.value,to_date:df.to_date}),style:inpStyle}),
				React.createElement('span',{key:'arr',style:{color:'#94a3b8',fontSize:'12px'}},'→'),
				React.createElement('input',{key:'td',type:'date',value:df.to_date,onChange:e=>setDf({range:'custom',from_date:df.from_date,to_date:e.target.value}),style:inpStyle}),
			])
		]),

		// ── Production Section ──
		React.createElement('div',{key:'prod-sec',style:{background:'#FFF5F3',borderRadius:'16px',border:'1px solid #F9C0AF',boxShadow:'0 1px 6px rgba(0,0,0,.05)',padding:'20px 24px',marginBottom:'18px'}},[
			sectionHdr('🏭','Production Status','Active SOs by delivery risk level','rgba(249,192,175,.4)'),
			React.createElement('div',{key:'cards',style:{display:'flex',gap:'10px',flexWrap:'wrap',marginBottom:'18px'}},[
				mkCard('ta','📋','Total',grandTotal,'Active + Completed','white',()=>onNavigate(null)),
				mkCard('ov','🚨','Overdue',prod['OVERDUE']||0,'Need attention','#FFDDD8',()=>onNavigate('OVERDUE')),
				mkCard('dr','⚠️','Delivery Risk',prod['DELIVERY RISK']||0,'Predicted late','#F2D894',()=>onNavigate('DELIVERY RISK')),
				mkCard('oh','⏸️','On Hold',prod['ON HOLD']||0,'JC blocked','#D2C7E5',()=>onNavigate('ON HOLD')),
				mkCard('ot','✅','On Track',prod['ON TRACK']||0,'All good','#D3EADA',()=>onNavigate('ON TRACK')),
				mkCard('co','🏁','Completed',data.completed||0,'This period','#F9ECE3',()=>onNavigate('COMPLETED')),
			]),
			React.createElement(PieCard,{key:'pie',title:'',subtitle:'',data:prodPieData,total:grandTotal,onSlice:onNavigate,embedded:true,light:true})
		]),

		// ── Planning Section ──
		React.createElement('div',{key:'plan-sec',style:{background:'#F0EDF8',borderRadius:'16px',border:'1px solid #D2C7E5',boxShadow:'0 1px 6px rgba(0,0,0,.05)',padding:'20px 24px',marginBottom:'18px'}},[
			sectionHdr('📋','Planning Status','Active SOs by production plan status','rgba(210,199,229,.5)'),
			React.createElement('div',{key:'cards',style:{display:'flex',gap:'10px',flexWrap:'wrap',marginBottom:'18px'}},[
				mkCard('pl','📅','Planned',plan.planned||0,'Production planned','#D3EADA',()=>onNavigate(null,'planned')),
				mkCard('np','📝','Not Planned',planNotPlanned,'Needs planning','#F9ECE3',()=>onNavigate(null,'not_planned')),
				mkCard('co','🏁','Completed',data.completed||0,'This period','#FFDDD8',()=>onNavigate('COMPLETED')),
			]),
			React.createElement(PieCard,{key:'pie',title:'',subtitle:'',data:planPieData,total:grandTotal,onSlice:null,embedded:true,light:true})
		]),

		// ── Top Overdue ──
		data.top_overdue&&data.top_overdue.length>0&&React.createElement('div',{key:'top',style:{background:'white',borderRadius:'14px',padding:'20px 24px',border:'1px solid #e2e8f0',boxShadow:'0 1px 4px rgba(0,0,0,.05)'}},[
			React.createElement('div',{key:'hd',style:{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'14px'}},[
				React.createElement('h3',{key:'t',style:{color:'#1e293b',fontSize:'15px',fontWeight:'800',margin:0}},'🚨 Top Overdue Orders'),
				React.createElement('button',{key:'b',onClick:()=>onNavigate('OVERDUE'),style:{background:'#FFDDD8',border:'1px solid #F9C0AF',color:'#7f1d1d',borderRadius:'7px',padding:'4px 12px',fontSize:'12px',fontWeight:'700',cursor:'pointer'}},'View All →')
			]),
			...data.top_overdue.map((so,i)=>React.createElement('div',{key:so.name,style:{display:'flex',alignItems:'center',gap:'12px',padding:'10px 12px',background:i%2===0?'#FFF5F3':'transparent',borderRadius:'8px',cursor:'pointer'},onClick:()=>onNavigate('OVERDUE')},[
				React.createElement('span',{key:'r',style:{fontSize:'18px',fontWeight:'900',color:'#dc2626',minWidth:'24px',textAlign:'center'}},i+1),
				React.createElement('div',{key:'i',style:{flex:1,minWidth:0}},[
					React.createElement('p',{key:'n',style:{fontSize:'13px',fontWeight:'800',color:'#1e293b',margin:0,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},so.name),
					React.createElement('p',{key:'c',style:{fontSize:'11px',color:'#64748b',margin:'1px 0 0',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},so.customer)
				]),
				React.createElement('div',{key:'d',style:{textAlign:'right',flexShrink:0}},[
					React.createElement('span',{key:'ov',style:{fontSize:'13px',fontWeight:'900',color:'#dc2626',background:'#FFDDD8',borderRadius:'6px',padding:'2px 10px'}},`+${so.overdue_days}d`),
					React.createElement('p',{key:'dt',style:{fontSize:'10px',color:'#94a3b8',margin:'2px 0 0',textAlign:'right'}},fmtDate(so.delivery_date))
				])
			]))
		])
	]);
}

// ─── SVG Pie Chart Card ───────────────────────────────────────────────────────
function PieCard({title,subtitle,data,total,onSlice,embedded,light}) {
	const size = 160, cx=size/2, cy=size/2, r=size/2-12;
	let angle = -Math.PI/2;
	const tot = data.reduce((s,d)=>s+d.value,0)||1;
	const slices = data.map(d=>{
		const a = (d.value/tot)*2*Math.PI;
		const sa = angle; angle += a;
		const ea = angle;
		const x1=cx+r*Math.cos(sa), y1=cy+r*Math.sin(sa);
		const x2=cx+r*Math.cos(ea), y2=cy+r*Math.sin(ea);
		return {...d, path:`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${a>Math.PI?1:0} 1 ${x2},${y2} Z`};
	});

	const [hovered,setHovered] = React.useState(null);

	const mkBody = ()=>React.createElement('div',{style:{display:'flex',gap:'20px',alignItems:'center',flexWrap:'wrap'}},[
		React.createElement('div',{key:'pie',style:{position:'relative',flexShrink:0}},[
			React.createElement('svg',{key:'svg',width:size,height:size,style:{display:'block'}},[
				...slices.map((s,i)=>React.createElement('path',{
					key:i, d:s.path, fill:s.color,
					style:{cursor:onSlice?'pointer':'default',opacity:hovered===null||hovered===i?1:.5,transition:'opacity .2s'},
					onMouseEnter:()=>setHovered(i),
					onMouseLeave:()=>setHovered(null),
					onClick:()=>onSlice&&onSlice(s.key)
				})),
				// Donut hole — dark circle ensures center text is always readable
				React.createElement('circle',{key:'hole',cx:cx,cy:cy,r:Math.round(r*0.52),fill:light?'white':'rgba(12,18,36,.96)'})
			]),
			React.createElement('div',{key:'ct',style:{position:'absolute',top:'50%',left:'50%',transform:'translate(-50%,-50%)',textAlign:'center',pointerEvents:'none'}},[
				React.createElement('div',{key:'v',style:{fontSize:'20px',fontWeight:'900',color:light?'#1e293b':'white',lineHeight:1}},
					hovered!==null ? data[hovered].value : tot
				),
				React.createElement('div',{key:'l',style:{fontSize:'9px',color:hovered!==null?data[hovered].color:light?'#94a3b8':'rgba(255,255,255,.5)',fontWeight:'700'}},
					hovered!==null ? data[hovered]?.label : 'TOTAL'
				)
			])
		]),
		React.createElement('div',{key:'leg',style:{display:'flex',flexDirection:'column',gap:'2px'}},
			data.map((d,i)=>React.createElement('div',{
				key:d.label,
				style:{display:'flex',alignItems:'center',gap:'10px',padding:'5px 10px',borderRadius:'8px',background:hovered===i?(light?'rgba(0,0,0,.04)':'rgba(255,255,255,.07)'):'transparent',cursor:onSlice?'pointer':'default',opacity:hovered===null||hovered===i?1:.4,transition:'opacity .2s,background .15s'},
				onMouseEnter:()=>setHovered(i),
				onMouseLeave:()=>setHovered(null),
				onClick:()=>onSlice&&onSlice(d.key)
			},[
				React.createElement('div',{key:'dot',style:{width:'9px',height:'9px',borderRadius:'50%',background:d.color,flexShrink:0,boxShadow:`0 0 5px ${d.color}`}}),
				React.createElement('span',{key:'l',style:{fontSize:'12px',color:light?'#374151':'rgba(255,255,255,.75)',minWidth:'90px'}},d.label),
				React.createElement('span',{key:'v',style:{fontSize:'14px',fontWeight:'900',color:d.color,minWidth:'24px',textAlign:'right'}},d.value)
			]))
		)
	]);

	if (embedded) return mkBody();

	return React.createElement('div',{style:{background:'rgba(255,255,255,.07)',borderRadius:'14px',padding:'20px 24px',border:'1px solid rgba(255,255,255,.12)'}},[
		React.createElement('h3',{key:'t',style:{color:'white',fontSize:'14px',fontWeight:'800',margin:'0 0 2px'}},title),
		React.createElement('p',{key:'s',style:{fontSize:'11px',color:'rgba(255,255,255,.4)',margin:'0 0 16px'}},subtitle),
		mkBody()
	]);
}

// ─── Filters ──────────────────────────────────────────────────────────────────
function Filters({filterInputs,setFilterInputs,onApply,onClear}) {
	const upd=(k,v)=>setFilterInputs(p=>({...p,[k]:v}));
	const inp={height:'36px',padding:'0 10px',border:'1px solid #e2e8f0',borderRadius:'7px',fontSize:'14px',color:'#374151',background:'white',outline:'none',width:'100%',boxSizing:'border-box'};
	const lbl={fontSize:'11px',fontWeight:'700',color:'#94a3b8',textTransform:'uppercase',letterSpacing:'.5px',marginBottom:'5px',display:'block'};
	return React.createElement('div',{style:{background:'white',borderRadius:'12px',padding:'16px 20px',marginBottom:'16px',border:'1px solid #e2e8f0',boxShadow:'0 1px 4px rgba(0,0,0,.05)'}}, [
		React.createElement('div',{key:'hd',style:{display:'flex',alignItems:'center',gap:'8px',marginBottom:'12px'}}, [
			React.createElement('span',{key:'ic',style:{fontSize:'15px'}},'🔍'),
			React.createElement('span',{key:'tx',style:{fontSize:'14px',fontWeight:'700',color:'#1e293b'}},'Filters')
		]),
		React.createElement('div',{key:'g',style:{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(145px,1fr))',gap:'10px',alignItems:'end'}}, [
			fc('so','Sales Order','SAL-ORD-...',filterInputs.so,v=>upd('so',v),'text',onApply,inp,lbl),
			fc('cu','Customer','Name or Code',filterInputs.customer,v=>upd('customer',v),'text',onApply,inp,lbl),
			fc('fd','From Date','',filterInputs.from_date,v=>upd('from_date',v),'date',null,inp,lbl),
			fc('td','To Date','',filterInputs.to_date,v=>upd('to_date',v),'date',null,inp,lbl),
			React.createElement('div',{key:'pr'},[
				React.createElement('label',{key:'l',style:lbl},'Production Status'),
				React.createElement('select',{key:'s',className:'drd-filter-input',value:filterInputs.priority,onChange:e=>upd('priority',e.target.value),style:{...inp,cursor:'pointer'}},[
					['','All'],['OVERDUE','🚨 OVERDUE'],['DELIVERY RISK','⚠️ DELIVERY RISK'],['ON HOLD','⏸️ ON HOLD'],['ON TRACK','✅ ON TRACK'],['COMPLETED','🏁 COMPLETED']
				].map(([v,t])=>React.createElement('option',{key:v,value:v},t)))
			]),
			React.createElement('div',{key:'pl'},[
				React.createElement('label',{key:'l',style:lbl},'Planning Status'),
				React.createElement('select',{key:'s',className:'drd-filter-input',value:filterInputs.planning,onChange:e=>upd('planning',e.target.value),style:{...inp,cursor:'pointer'}},[
					['','All'],['planned','📅 Planned'],['not_planned','📝 Not Planned']
				].map(([v,t])=>React.createElement('option',{key:v,value:v},t)))
			]),
			React.createElement('div',{key:'bt',style:{display:'flex',gap:'8px'}}, [
				React.createElement('button',{key:'ap',onClick:onApply,style:{flex:1,height:'36px',background:'#F2D894',color:'#713f12',border:'1px solid #c9a84c',borderRadius:'7px',fontSize:'14px',fontWeight:'700',cursor:'pointer'}},'Apply'),
				React.createElement('button',{key:'cl',onClick:onClear,style:{flex:1,height:'36px',background:'white',color:'#374151',border:'1px solid #e2e8f0',borderRadius:'7px',fontSize:'14px',fontWeight:'600',cursor:'pointer'}},'Clear')
			])
		])
	]);
}
function fc(key,label,ph,val,onChange,type,onEnter,inp,lbl) {
	return React.createElement('div',{key},[
		React.createElement('label',{key:'l',style:lbl},label),
		React.createElement('input',{key:'i',type,className:'drd-filter-input',placeholder:ph,value:val,onChange:e=>onChange(e.target.value),onKeyDown:e=>{if(e.key==='Enter'&&onEnter)onEnter();},style:inp})
	]);
}

// ─── SO Card (list view) ──────────────────────────────────────────────────────
function SOCard({order,onClick}) {
	const pm  = P[order.priority]||P['ON TRACK'];
	const pct = order.progress_pct||0;
	const isOverdue = order.actual_overdue_days > 0;
	const isLate    = !isOverdue && order.delay_days > 0;
	const isEarly   = order.delay_days < 0;

	// Date row background
	const dateBg = isOverdue ? 'rgba(220,38,38,.08)' : isLate ? 'rgba(245,158,11,.07)' : 'rgba(5,150,105,.06)';
	const dateBorder = isOverdue ? '#fca5a5' : isLate ? '#fcd34d' : '#a7f3d0';

	return React.createElement('div',{
		className:'drd-card',
		style:{background:pm.cardBg,borderRadius:'10px',borderLeft:`6px solid ${pm.border}`,boxShadow:'0 2px 10px rgba(0,0,0,.18)',cursor:'pointer',overflow:'hidden'},
		onClick
	},[
		React.createElement('div',{key:'body',style:{padding:'14px 16px 10px',display:'flex',gap:'14px',alignItems:'flex-start'}},[
			// Priority column
			React.createElement('div',{key:'pri',style:{flexShrink:0,display:'flex',flexDirection:'column',alignItems:'center',gap:'3px'}}, [
				React.createElement('span',{key:'ic',style:{fontSize:'20px'}}, pm.icon),
				React.createElement('span',{key:'lb',style:{fontSize:'10px',fontWeight:'800',color:pm.color,letterSpacing:'.3px'}}, pm.label),
			]),
			// Main info
			React.createElement('div',{key:'info',style:{flex:1,minWidth:0}}, [
				React.createElement('div',{key:'r1',style:{display:'flex',alignItems:'baseline',gap:'8px',flexWrap:'wrap',marginBottom:'2px'}}, [
					React.createElement('span',{key:'n',style:{fontSize:'17px',fontWeight:'800',color:'#111827'}}, order.name),
					React.createElement('span',{key:'c',style:{fontSize:'13px',color:'#6b7280',fontWeight:'500'}}, order.customer_name||order.customer)
				]),
				order.items_display && React.createElement('p',{key:'it',style:{fontSize:'12px',color:'#4b5563',margin:0,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}, order.items_display)
			]),
			// Value
			React.createElement('div',{key:'right',style:{flexShrink:0,textAlign:'right'}},
				React.createElement('div',{key:'v',style:{fontSize:'12px',color:'#9ca3af'}}, fmtRs(order.value))
			)
		]),
		// 5-stage journey (same style as Sales Order Tracking dashboard)
		React.createElement('div',{key:'journey',style:{padding:'8px 16px 6px'}}, [
			React.createElement('div',{key:'stepper',style:{position:'relative'}}, (()=>{
				const stagesData = [
					{label:'Sales Order', sub:'Created',                          icon:'📝', done:true},
					{label:'Prod Plan',   sub:(order.stages_done||1)>1?'Done':'Pending',   icon:'📋', done:(order.stages_done||1)>1},
					{label:'Work Order',  sub:(order.stages_done||1)>2?'Done':'Pending',   icon:'⚙️', done:(order.stages_done||1)>2},
					{label:'Job Card',    sub:(order.stages_done||1)>3?'Done':'Pending',   icon:'📊', done:(order.stages_done||1)>3},
					{label:'Delivery',    sub:(order.stages_done||1)>4?'Done':'Pending',   icon:'📦', done:(order.stages_done||1)>4},
				];
				const cs = 28;
				let lastGreen = -1;
				stagesData.forEach((s,i)=>{ if(s.done) lastGreen=i; });
				const greenPct = lastGreen>0?(lastGreen/(stagesData.length-1))*100:0;
				const activeIdx = stagesData.findIndex(s=>!s.done);
				return [
					React.createElement('div',{key:'bg',style:{position:'absolute',top:(cs/2)+'px',left:(cs/2)+'px',right:(cs/2)+'px',height:'2px',transform:'translateY(-50%)',background:'#e5e7eb',borderRadius:'2px',zIndex:0}}),
					greenPct>0&&React.createElement('div',{key:'fg',style:{position:'absolute',top:(cs/2)+'px',left:(cs/2)+'px',width:`calc((100% - ${cs}px) * ${greenPct/100})`,height:'2px',transform:'translateY(-50%)',background:'linear-gradient(90deg,#10b981,#34d399)',borderRadius:'2px',zIndex:0,transition:'width .5s'}}),
					React.createElement('div',{key:'st',style:{display:'flex',justifyContent:'space-between',position:'relative',zIndex:1}},
						stagesData.map((stage,i)=>{
							const isDone=stage.done, isActive=i===activeIdx;
							return React.createElement('div',{key:'s'+i,style:{display:'flex',flexDirection:'column',alignItems:'center',width:'60px',flexShrink:0}}, [
								React.createElement('div',{key:'c',style:{width:cs+'px',height:cs+'px',borderRadius:'50%',background:isDone?'linear-gradient(135deg,#10b981,#34d399)':isActive?'linear-gradient(135deg,#667eea,#764ba2)':'white',border:isDone||isActive?'none':'2px dashed #d1d5db',display:'flex',alignItems:'center',justifyContent:'center',fontSize:isDone?'13px':'11px',color:'white',boxShadow:isActive?'0 0 10px rgba(102,126,234,.4)':isDone?'0 0 6px rgba(16,185,129,.25)':'0 1px 3px rgba(0,0,0,.08)'}},
									isDone?'✓':stage.icon
								),
								React.createElement('p',{key:'lb',style:{fontSize:'10px',fontWeight:'600',color:isDone?'#065f46':isActive?'#4f46e5':'#9ca3af',marginTop:'5px',textAlign:'center',lineHeight:'1.2'}},stage.label),
								React.createElement('p',{key:'sb',style:{fontSize:'9px',color:isDone?'#6b7280':'#9ca3af',marginTop:'1px',textAlign:'center'}},stage.sub)
							]);
						})
					)
				];
			})())
		]),
		// FG Job Execution
		React.createElement('div',{key:'jc-exec',style:{padding:'0 16px 8px'}}, [
			React.createElement('div',{key:'hd',style:{display:'flex',justifyContent:'space-between',marginBottom:'3px'}}, [
				React.createElement('span',{key:'l',style:{fontSize:'11px',fontWeight:'700',color:'#6b7280'}}, '⚙️ Job Execution'),
				React.createElement('span',{key:'v',style:{fontSize:'11px',fontWeight:'800',color:'#374151'}},
					(order.fg_total_qty||0)>0
					? `${pf(order.fg_produced_qty).toLocaleString()} / ${pf(order.fg_total_qty).toLocaleString()} (${order.fg_progress_pct||0}%)`
					: 'No job cards yet'
				)
			]),
			bar(order.fg_progress_pct||0, 6, 3)
		]),
		// Qty progress
		React.createElement('div',{key:'prog',style:{padding:'0 16px 8px'}}, [
			React.createElement('div',{key:'lbl',style:{display:'flex',justifyContent:'space-between',marginBottom:'4px'}}, [
				React.createElement('span',{key:'q',style:{fontSize:'12px',color:'#6b7280',fontWeight:'600'}}, `${pf(order.produced_qty).toLocaleString()} / ${pf(order.total_qty).toLocaleString()}`),
				React.createElement('span',{key:'p',style:{fontSize:'13px',fontWeight:'800',color:pct>=80?'#059669':pct>=40?'#b45309':'#dc2626'}}, `${pct}%`)
			]),
			bar(pct, 9, 5)
		]),
		// Date comparison row
		React.createElement('div',{key:'dates',style:{padding:'7px 16px',background:dateBg,borderTop:`1px solid ${dateBorder}`,borderBottom:`1px solid ${dateBorder}`,display:'flex',alignItems:'center',gap:'10px',flexWrap:'wrap'}}, [
			React.createElement('span',{key:'bpp',style:{fontSize:'12px',fontWeight:'600',color:'#374151'}}, `📅 BPP: ${fmtDate(order.expected_date)}`),
			order.predicted_date && React.createElement('span',{key:'est',style:{fontSize:'12px',fontWeight:'800',color:isOverdue||isLate?'#dc2626':'#059669'}}, `🎯 Est: ${fmtDate(order.predicted_date)}`),
			isOverdue && React.createElement('span',{key:'ovbadge',style:{fontSize:'11px',fontWeight:'800',color:'white',background:'#dc2626',borderRadius:'4px',padding:'1px 7px',marginLeft:'auto'}}, `🚨 ${order.actual_overdue_days}d OVERDUE`),
			isLate && React.createElement('span',{key:'latebadge',style:{fontSize:'11px',fontWeight:'800',color:'#92400e',background:'#fef3c7',borderRadius:'4px',padding:'1px 7px',marginLeft:'auto'}}, `⚠️ +${order.delay_days}d late`),
			!isOverdue && !isLate && order.predicted_date && React.createElement('span',{key:'okbadge',style:{fontSize:'11px',fontWeight:'700',color:'#065f46',background:'#d1fae5',borderRadius:'4px',padding:'1px 7px',marginLeft:'auto'}}, isEarly?`✅ ${Math.abs(order.delay_days)}d early`:'✅ On Track')
		]),
		// Footer strip
		React.createElement('div',{key:'foot',style:{background:'rgba(0,0,0,.04)',padding:'7px 16px',display:'flex',gap:'14px',flexWrap:'wrap',alignItems:'center'}}, [
			React.createElement('span',{key:'wo',style:{fontSize:'12px',color:'#6b7280'}}, `⚙️ ${order.wo_count} WO`),
			React.createElement('span',{key:'go',style:{fontSize:'12px',color:'#6366f1',marginLeft:'auto',fontWeight:'700'}}, 'Open →')
		])
	]);
}

// ─── SO Left Panel ────────────────────────────────────────────────────────────
function SOPanel({soData,onBack,onToggle,openSet}) {
	const {useState,useEffect} = React;
	const [det,setDet] = useState(null);
	const [loading,setLoading] = useState(true);
	const pm = P[soData.priority]||P['ON TRACK'];

	useEffect(()=>{
		setDet(null); setLoading(true);
		frappe.call({
			method:'ujwal_industries.api.sales_order_tracker.get_so_detail',
			args:{sales_order:soData.name},
			callback:r=>{ if(r.message) setDet(r.message); setLoading(false); }
		});
	},[soData.name]);

	return React.createElement('div',{style:{background:'white',borderRadius:'12px',overflow:'hidden',boxShadow:'0 4px 24px rgba(0,0,0,.22)'}},[
		// Header
		React.createElement('div',{key:'hdr',style:{background:`linear-gradient(135deg,${pm.border},${pm.color})`,padding:'14px 16px',color:'white'}}, [
			React.createElement('div',{key:'r1',style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'4px'}}, [
				React.createElement('div',{key:'l',style:{display:'flex',alignItems:'center',gap:'8px',minWidth:0}}, [
					React.createElement('span',{key:'ic',style:{fontSize:'18px'}}, pm.icon),
					React.createElement('span',{key:'n',style:{fontSize:'16px',fontWeight:'800',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}, soData.name)
				]),
				React.createElement('button',{key:'bk',style:{background:'rgba(255,255,255,.25)',border:'none',color:'white',borderRadius:'6px',padding:'4px 10px',fontSize:'12px',fontWeight:'700',cursor:'pointer',flexShrink:0},onClick:onBack}, '← Back')
			]),
			React.createElement('p',{key:'c',style:{fontSize:'13px',opacity:.9,margin:'2px 0'}}, soData.customer_name?`${soData.customer_name} (${soData.customer})`:soData.customer),
			React.createElement('div',{key:'dates',style:{display:'flex',gap:'10px',marginTop:'6px',flexWrap:'wrap'}}, [
				React.createElement('span',{key:'e',style:{fontSize:'12px',opacity:.85}}, `📅 BPP: ${fmtDate(soData.expected_date)}`),
				soData.predicted_date && React.createElement('span',{key:'p',style:{fontSize:'12px',fontWeight:'800'}}, `🎯 ${fmtDate(soData.predicted_date)}`),
				soData.delay_days>0 && React.createElement('span',{key:'d',style:{fontSize:'12px',fontWeight:'800',background:'rgba(255,255,255,.3)',borderRadius:'4px',padding:'0 7px'}}, `+${soData.delay_days}d late`)
			])
		]),
		// Body
		React.createElement('div',{key:'body',style:{padding:'12px'}},
			loading
			? React.createElement('div',{style:{textAlign:'center',padding:'28px',color:'#9ca3af'}}, [
				React.createElement('div',{key:'sp',style:{width:'30px',height:'30px',margin:'0 auto 10px',border:'3px solid #e5e7eb',borderTopColor:'#f59e0b',borderRadius:'50%',animation:'spin .8s linear infinite'}}),
				'Loading...'
			  ])
			: det ? React.createElement(SOPanelBody,{det,onToggle,openSet}) : null
		)
	]);
}

function SOPanelBody({det,onToggle,openSet}) {
	const so   = det.sales_order;
	const wos  = det.work_orders||[];
	const items= det.so_items||[];
	const dns  = det.delivery_notes||[];
	const fg   = wos.filter(w=>w.is_fg);
	const sfg  = wos.filter(w=>!w.is_fg);

	// count on-hold JCs across all WOs
	const holdJCs = wos.flatMap(w=>(w.job_cards||[]).filter(j=>j.status==='On Hold'));

	return React.createElement('div',{},[
		// Quick stats
		React.createElement('div',{key:'stats',style:{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8px',marginBottom:'12px'}},[
			ms('💰','Value',fmtRs(so.grand_total)),
			ms('📅','Delivery',fmtDate(so.delivery_date)),
			ms('📦','Delivered',`${pf(so.per_delivered).toFixed(0)}%`),
			ms('⚙️','Work Orders',wos.length),
		]),

		// ON HOLD alert banner
		holdJCs.length>0 && React.createElement('div',{key:'hold',style:{background:'#fee2e2',border:'1px solid #fca5a5',borderRadius:'8px',padding:'10px 12px',marginBottom:'12px'}}, [
			React.createElement('p',{key:'hd',style:{fontSize:'13px',fontWeight:'800',color:'#991b1b',marginBottom:'4px'}}, `🔴 ${holdJCs.length} Job Card${holdJCs.length>1?'s':''} On Hold`),
			...holdJCs.map(j=>React.createElement('div',{key:j.name,style:{fontSize:'12px',color:'#7f1d1d',marginTop:'3px'}}, [
				React.createElement('span',{key:'n',style:{fontWeight:'600'}}, `${j.name}: `),
				j.pause_reason||j.remarks||'No reason recorded'
			]))
		]),

		// Items
		items.length>0 && React.createElement('div',{key:'items',style:{marginBottom:'12px'}}, [
			React.createElement('p',{key:'hd',style:{fontSize:'11px',fontWeight:'700',color:'#9ca3af',textTransform:'uppercase',letterSpacing:'.5px',marginBottom:'5px'}}, '📦 Order Items'),
			...items.map((it,i)=>React.createElement('div',{key:it.item_code+i,style:{display:'flex',justifyContent:'space-between',fontSize:'12px',padding:'3px 0',borderBottom:'1px solid #f3f4f6'}}, [
				React.createElement('span',{key:'n',style:{color:'#374151',fontWeight:'500',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',maxWidth:'190px'}}, it.item_name?`${it.item_code} — ${it.item_name}`:it.item_code),
				React.createElement('span',{key:'q',style:{color:'#6b7280',flexShrink:0,marginLeft:'6px'}}, `${pf(it.qty).toLocaleString()} ${it.stock_uom||''}`)
			]))
		]),

		// FG WOs
		fg.length>0 && React.createElement(CollapsibleSection,{key:'fg',title:`🏭 FG Work Orders`,count:fg.length,defaultOpen:true},
			fg.map(w=>React.createElement(WORow,{key:w.name,wo:w,onToggle:()=>onToggle(w.name),open:openSet.has(w.name)}))
		),

		// SFG WOs
		sfg.length>0 && React.createElement(CollapsibleSection,{key:'sfg',title:`🔩 SFG Work Orders`,count:sfg.length,defaultOpen:true},
			sfg.map(w=>React.createElement(WORow,{key:w.name,wo:w,onToggle:()=>onToggle(w.name),open:openSet.has(w.name)}))
		),

		wos.length===0 && React.createElement('div',{key:'nowo',style:{textAlign:'center',padding:'20px',background:'#fafafa',borderRadius:'8px',border:'1px dashed #e5e7eb',marginBottom:'10px'}}, [
			React.createElement('div',{key:'ic',style:{fontSize:'28px'}},'⚙️'),
			React.createElement('p',{key:'tx',style:{fontSize:'12px',color:'#9ca3af',marginTop:'4px'}},'No Work Orders yet')
		]),

		// DNs
		dns.length>0 && React.createElement(CollapsibleSection,{key:'dns',title:`🚚 Delivery Notes`,count:dns.length,defaultOpen:false},
			dns.map(dn=>React.createElement('div',{key:dn.name,style:{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'6px 10px',background:'#f0fdf4',borderRadius:'6px',marginBottom:'4px',border:'1px solid #bbf7d0'}}, [
				React.createElement('div',{key:'l'},[
					React.createElement('p',{key:'n',style:{fontSize:'12px',fontWeight:'700',color:'#065f46',margin:0}},dn.name),
					React.createElement('p',{key:'d',style:{fontSize:'11px',color:'#6b7280',margin:0}},fmtDate(dn.posting_date))
				]),
				React.createElement('span',{key:'s',style:{padding:'2px 8px',borderRadius:'6px',fontSize:'10px',fontWeight:'700',background:'#d1fae5',color:'#065f46'}},dn.status)
			]))
		)
	]);
}

function sec(title, children) {
	return React.createElement('div',{key:title,style:{marginBottom:'10px'}}, [
		React.createElement('p',{key:'hd',style:{fontSize:'11px',fontWeight:'700',color:'#6b7280',textTransform:'uppercase',letterSpacing:'.5px',marginBottom:'5px'}}, title),
		...children
	]);
}

function CollapsibleSection({title, count, defaultOpen=true, children}) {
	const {useState} = React;
	const [open, setOpen] = useState(defaultOpen);
	return React.createElement('div',{style:{marginBottom:'10px',border:'1px solid #e5e7eb',borderRadius:'8px',overflow:'hidden'}}, [
		React.createElement('div',{
			key:'hd',
			style:{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'7px 10px',background:'#f8fafc',cursor:'pointer',userSelect:'none'},
			onClick:()=>setOpen(o=>!o)
		}, [
			React.createElement('div',{key:'l',style:{display:'flex',alignItems:'center',gap:'6px'}}, [
				React.createElement('span',{key:'ic',style:{fontSize:'12px',color:'#6b7280',transition:'transform .2s',display:'inline-block',transform:open?'rotate(0deg)':'rotate(-90deg)'}}, '▼'),
				React.createElement('span',{key:'t',style:{fontSize:'11px',fontWeight:'800',color:'#374151',textTransform:'uppercase',letterSpacing:'.5px'}}, title),
			]),
			count!=null && React.createElement('span',{key:'ct',style:{fontSize:'10px',fontWeight:'700',padding:'1px 7px',borderRadius:'10px',background:'#e5e7eb',color:'#6b7280'}}, count)
		]),
		open && React.createElement('div',{key:'body',style:{padding:'8px 8px 4px'}}, children)
	]);
}
function ms(icon,label,value) {
	return React.createElement('div',{key:label,style:{background:'#f8fafc',borderRadius:'8px',border:'1px solid #e5e7eb',padding:'8px 10px',textAlign:'center'}}, [
		React.createElement('div',{key:'ic',style:{fontSize:'16px',marginBottom:'1px'}},icon),
		React.createElement('div',{key:'v',style:{fontSize:'14px',fontWeight:'800',color:'#111827'}},value),
		React.createElement('div',{key:'l',style:{fontSize:'10px',color:'#9ca3af'}},label)
	]);
}

// WO row inside left panel
function WORow({wo,onToggle,open}) {
	const wc      = woColor(wo.status);
	const pct     = wo.progress_pct||0;
	const hasDelay = wo.delay_days>0;
	const hasHold  = (wo.job_cards||[]).some(j=>j.status==='On Hold');
	const rmShort  = wo.rm_issue_count>0;
	const isDraft  = wo.docstatus===0;

	return React.createElement('div',{
		className:'drd-wo-row',
		style:{background:open?'#fffbeb':'white',border:`1px solid ${open?'#f59e0b':hasDelay?'#fca5a5':'#e5e7eb'}`,borderRadius:'8px',marginBottom:'6px',padding:'10px 12px',cursor:'pointer',boxShadow:open?'0 0 0 2px rgba(245,158,11,.3)':'none'},
		onClick:onToggle
	},[
		// Row 1
		React.createElement('div',{key:'r1',style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'4px'}}, [
			React.createElement('div',{key:'l',style:{display:'flex',alignItems:'center',gap:'6px',minWidth:0}}, [
				open && React.createElement('span',{key:'pin',style:{fontSize:'12px',flexShrink:0}},'📌'),
				React.createElement('span',{key:'n',style:{fontSize:'13px',fontWeight:'800',color:'#111827',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},wo.name),
				React.createElement('span',{key:'t',style:{fontSize:'9px',fontWeight:'800',padding:'1px 5px',borderRadius:'3px',background:wo.is_fg?'#dbeafe':'#ede9fe',color:wo.is_fg?'#1e40af':'#5b21b6',flexShrink:0}},wo.wo_type),
				isDraft&&React.createElement('span',{key:'dr',style:{fontSize:'9px',fontWeight:'800',padding:'1px 5px',borderRadius:'3px',background:'#f3f4f6',color:'#6b7280',flexShrink:0}},'DRAFT')
			]),
			React.createElement('div',{key:'r',style:{display:'flex',alignItems:'center',gap:'5px',flexShrink:0}}, [
				hasDelay && React.createElement('span',{key:'d',style:{fontSize:'11px',fontWeight:'800',color:'#dc2626',background:'#fee2e2',borderRadius:'4px',padding:'0 5px'}},`+${wo.delay_days}d`),
				!isDraft && React.createElement('span',{key:'s',style:{padding:'2px 8px',borderRadius:'6px',fontSize:'10px',fontWeight:'700',background:wc.bg,color:wc.text}},wo.status)
			])
		]),
		// Item
		React.createElement('p',{key:'item',style:{fontSize:'11px',color:'#6b7280',margin:'0 0 5px',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},wo.item_name||wo.production_item),
		// Progress bar
		React.createElement('div',{key:'bar',style:{marginBottom:'5px'}}, [
			React.createElement('div',{key:'lbl',style:{display:'flex',justifyContent:'space-between',marginBottom:'2px'}}, [
				React.createElement('span',{key:'q',style:{fontSize:'10px',color:'#9ca3af'}},`${pf(wo.produced_qty).toLocaleString()} / ${pf(wo.qty).toLocaleString()}`),
				React.createElement('span',{key:'p',style:{fontSize:'11px',fontWeight:'800',color:pct>=80?'#059669':pct>=40?'#b45309':'#dc2626'}},`${pct}%`)
			]),
			bar(pct, 5, 3)
		]),
		// Badges row
		React.createElement('div',{key:'tags',style:{display:'flex',gap:'6px',flexWrap:'wrap'}}, [
			wo.jc_total>0 && React.createElement('span',{key:'jc',style:{fontSize:'10px',color:'#6b7280'}},`📊 ${wo.jc_done}/${wo.jc_total} JC`),
			hasHold && React.createElement('span',{key:'hold',style:{fontSize:'10px',fontWeight:'700',color:'#991b1b',background:'#fee2e2',borderRadius:'4px',padding:'0 5px'}},'🔴 ON HOLD'),
			rmShort && React.createElement('span',{key:'rm',style:{fontSize:'10px',fontWeight:'700',color:'#92400e',background:'#fef3c7',borderRadius:'4px',padding:'0 5px'}},`⚠️ ${wo.rm_issue_count} RM`),
			React.createElement('span',{key:'go',style:{fontSize:'10px',color:'#6366f1',marginLeft:'auto',fontWeight:'700'}}, open?'Opened ↗':'Details →')
		])
	]);
}

// ─── WO Right Panel ───────────────────────────────────────────────────────────
function WOPanel({woName,onClose}) {
	const {useState,useEffect} = React;
	const [det,setDet]         = useState(null);
	const [loading,setLoading] = useState(true);
	const [col,setCol]         = useState(false);

	useEffect(()=>{
		frappe.call({
			method:'ujwal_industries.api.sales_order_tracker.get_wo_detail',
			args:{work_order:woName},
			callback:r=>{ if(r.message) setDet(r.message); setLoading(false); }
		});
	},[woName]);

	const wo  = det&&det.work_order;
	const wc  = wo?woColor(wo.status):{};
	const pct = wo?wo.progress_pct||0:0;

	return React.createElement('div',{style:{background:'white',borderRadius:'12px',overflow:'hidden',boxShadow:'0 4px 20px rgba(0,0,0,.18)',animation:'pop .2s ease'}}, [
		// Header (clickable = collapse)
		React.createElement('div',{key:'hdr',style:{background:'linear-gradient(135deg,#d97706,#92400e)',padding:'12px 16px',display:'flex',alignItems:'center',justifyContent:'space-between',cursor:'pointer'},onClick:()=>setCol(c=>!c)}, [
			React.createElement('div',{key:'l',style:{display:'flex',alignItems:'center',gap:'10px',minWidth:0}}, [
				React.createElement('span',{key:'ic',style:{fontSize:'20px',flexShrink:0}},'⚙️'),
				React.createElement('div',{key:'inf',style:{minWidth:0}}, [
					React.createElement('p',{key:'n',style:{fontSize:'14px',fontWeight:'800',color:'white',margin:0,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},woName),
					wo&&React.createElement('p',{key:'it',style:{fontSize:'11px',color:'rgba(255,255,255,.75)',margin:0,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},wo.item_name||wo.production_item)
				])
			]),
			React.createElement('div',{key:'r',style:{display:'flex',alignItems:'center',gap:'8px',flexShrink:0}}, [
				wo&&React.createElement('span',{key:'s',style:{padding:'2px 10px',borderRadius:'8px',fontSize:'11px',fontWeight:'700',background:'rgba(255,255,255,.2)',color:'white'}},wo.status),
				wo&&wo.delay_days>0&&React.createElement('span',{key:'d',style:{fontSize:'12px',fontWeight:'800',color:'white',background:'rgba(220,38,38,.6)',borderRadius:'4px',padding:'1px 8px'}},`+${wo.delay_days}d`),
				React.createElement('span',{key:'col',style:{fontSize:'16px',color:'white',padding:'0 2px'}},col?'▼':'▲'),
				React.createElement('button',{key:'x',style:{background:'rgba(255,255,255,.2)',border:'none',color:'white',borderRadius:'6px',padding:'4px 9px',fontSize:'15px',cursor:'pointer',lineHeight:1},onClick:e=>{e.stopPropagation();onClose();}},'✕')
			])
		]),

		// Progress bar (always visible)
		!col&&wo && React.createElement('div',{key:'pb',style:{padding:'8px 16px',background:'#fffbeb',borderBottom:'1px solid #fef08a'}}, [
			React.createElement('div',{key:'lbl',style:{display:'flex',justifyContent:'space-between',marginBottom:'4px'}}, [
				React.createElement('span',{key:'q',style:{fontSize:'13px',fontWeight:'600',color:'#78716c'}},`${pf(wo.produced_qty).toLocaleString()} / ${pf(wo.qty).toLocaleString()}`),
				React.createElement('span',{key:'p',style:{fontSize:'14px',fontWeight:'800',color:pct>=80?'#059669':pct>=40?'#b45309':'#dc2626'}},`${pct}%`)
			]),
			bar(pct, 10, 5)
		]),

		// Body
		!col && React.createElement('div',{key:'body',style:{padding:'14px'}},
			loading
			? React.createElement('div',{style:{textAlign:'center',padding:'24px',color:'#9ca3af'}}, [
				React.createElement('div',{key:'sp',style:{width:'28px',height:'28px',margin:'0 auto 8px',border:'3px solid #e5e7eb',borderTopColor:'#f59e0b',borderRadius:'50%',animation:'spin .8s linear infinite'}}),
				'Loading...'
			  ])
			: det ? React.createElement(WOPanelBody,{det}) : null
		)
	]);
}

function WOPanelBody({det}) {
	const wo  = det.work_order;
	const jcs = det.job_cards||[];
	const rms = det.rm_items||[];
	const ses = det.stock_entries||[];

	return React.createElement('div',{},[
		// Dates
		React.createElement('div',{key:'dates',style:{display:'flex',gap:'10px',flexWrap:'wrap',marginBottom:'14px'}}, [
			wo.planned_start_date&&React.createElement('span',{key:'ps',style:{fontSize:'12px',color:'#6b7280'}},`📅 Plan: ${fmtDate(wo.planned_start_date)} → ${fmtDate(wo.planned_end_date)}`),
			wo.actual_start_date&&React.createElement('span',{key:'as',style:{fontSize:'12px',color:'#059669',fontWeight:'700'}},`✅ Started: ${fmtDate(wo.actual_start_date)}`),
			wo.predicted_date&&React.createElement('span',{key:'pr',style:{fontSize:'12px',fontWeight:'800',color:wo.delay_days>0?'#dc2626':'#059669'}},`🎯 ${fmtDate(wo.predicted_date)}${wo.delay_days>0?` (+${wo.delay_days}d)`:''}`)
		]),

		// ── JOB CARDS ──
		React.createElement(CollapsibleSection,{key:'jc-sect',title:'📊 Job Cards',count:jcs.length,defaultOpen:true},
			jcs.length===0
			? React.createElement('p',{style:{fontSize:'13px',color:'#9ca3af',fontStyle:'italic',padding:'8px 0'}},'No Job Cards')
			: React.createElement('div',{key:'rows',style:{display:'flex',flexDirection:'column',gap:'6px',marginBottom:'4px'}},
				jcs.map(jc=>{
					const jc_ = jcColor(jc.status);
					const jqty = pf(jc.for_quantity);
					const jdone = pf(jc.total_completed_qty);
					const jpct = jqty>0?Math.round((jdone/jqty)*100):0;
					const isDraft = jc.docstatus===0;
					const isHold  = jc.status==='On Hold';

					return React.createElement('div',{key:jc.name,style:{borderRadius:'8px',overflow:'hidden',border:`1px solid ${isHold?'#fca5a5':isDraft?'#e5e7eb':'#f0f0f0'}`}},[
						// Main row
						React.createElement('div',{key:'row',style:{padding:'8px 12px',background:isHold?'#fff5f5':isDraft?'#fafafa':'#fafafa',display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}, [
							React.createElement('div',{key:'l',style:{display:'flex',alignItems:'flex-start',gap:'8px',minWidth:0}}, [
								React.createElement('div',{key:'dot',style:{width:'9px',height:'9px',borderRadius:'50%',background:jc_.dot,flexShrink:0,marginTop:'3px'}}),
								React.createElement('div',{key:'inf'}, [
									React.createElement('div',{key:'r1',style:{display:'flex',alignItems:'center',gap:'6px',flexWrap:'wrap'}}, [
										React.createElement('span',{key:'n',style:{fontSize:'13px',fontWeight:'700',color:'#111827'}},jc.name),
										isDraft&&React.createElement('span',{key:'dr',style:{fontSize:'9px',fontWeight:'800',background:'#f3f4f6',color:'#6b7280',borderRadius:'4px',padding:'0 5px'}},'DRAFT'),
									]),
									React.createElement('div',{key:'r2',style:{fontSize:'11px',color:'#6b7280',marginTop:'2px'}},
										[jc.operation, jc.workstation&&`@ ${jc.workstation}`].filter(Boolean).join(' ')
									)
								])
							]),
							React.createElement('div',{key:'r',style:{display:'flex',flexDirection:'column',alignItems:'flex-end',gap:'3px',flexShrink:0,marginLeft:'8px'}}, [
								React.createElement('span',{key:'s',style:{padding:'2px 8px',borderRadius:'6px',fontSize:'11px',fontWeight:'700',background:jc_.bg,color:jc_.text}},jc.status),
								jc.days_overdue>0&&React.createElement('span',{key:'ov',style:{fontSize:'10px',fontWeight:'700',color:'#dc2626'}},`${jc.days_overdue}d overdue`)
							])
						]),
						// Qty + progress (if qty known)
						jqty>0 && React.createElement('div',{key:'qty',style:{padding:'5px 12px',background:isHold?'#fee2e2':isDraft?'#f9fafb':'#f8f8f8',borderTop:`1px solid ${isHold?'#fca5a5':'#f0f0f0'}`}}, [
							React.createElement('div',{key:'l',style:{display:'flex',justifyContent:'space-between',marginBottom:'3px'}}, [
								React.createElement('span',{key:'q',style:{fontSize:'11px',color:'#6b7280'}},`Done: ${jdone.toLocaleString()} / ${jqty.toLocaleString()}`),
								React.createElement('span',{key:'p',style:{fontSize:'11px',fontWeight:'800',color:jpct>=80?'#059669':jpct>=40?'#b45309':'#dc2626'}},`${jpct}%`)
							]),
							bar(jpct, 5, 3)
						]),
						// Pause reason (only On Hold + has remarks)
						isHold && React.createElement('div',{key:'reason',style:{padding:'7px 12px',background:'#fef2f2',borderTop:'2px solid #fca5a5',display:'flex',alignItems:'flex-start',gap:'6px'}}, [
							React.createElement('span',{key:'ic',style:{fontSize:'14px',flexShrink:0}},'🔴'),
							React.createElement('div',{key:'txt'}, [
								React.createElement('p',{key:'hd',style:{fontSize:'11px',fontWeight:'800',color:'#991b1b',margin:'0 0 1px'}},'Hold Reason:'),
								React.createElement('p',{key:'reason',style:{fontSize:'12px',color:'#7f1d1d',margin:0,fontStyle:jc.remarks?'normal':'italic'}},
									jc.pause_reason||jc.remarks||'No reason recorded'
								)
							])
						])
					]);
				})
			)
		),

		// ── RM TABLE ──
		rms.length>0 && React.createElement(CollapsibleSection,{key:'rm-sect',title:'🧱 Raw Materials',count:rms.length,defaultOpen:true},
			React.createElement('div',{key:'tbl',style:{overflowX:'auto',marginBottom:'4px'}},
				React.createElement('table',{style:{width:'100%',borderCollapse:'collapse',fontSize:'12px'}},[
					React.createElement('thead',{key:'th'},
						React.createElement('tr',{style:{background:'#f8fafc',borderBottom:'1px solid #e5e7eb'}}, [
							['Item','38%'],['Req','16%'],['Trans','16%'],['Avail','15%'],['','15%']
						].map(([h,w])=>React.createElement('th',{key:h,style:{padding:'6px 8px',textAlign:'left',fontWeight:'700',color:'#6b7280',fontSize:'11px',width:w}},h)))
					),
					React.createElement('tbody',{key:'tb'}, rms.map(rm=>{
						const ok = pf(rm.transferred_qty)>=pf(rm.required_qty);
						const pt = !ok&&pf(rm.transferred_qty)>0;
						return React.createElement('tr',{key:rm.item_code,style:{background:ok?'#f0fdf4':pt?'#fffbeb':'#fff5f5',borderBottom:'1px solid #f3f4f6'}},[
							React.createElement('td',{key:'i',style:{padding:'6px 8px',fontWeight:'600',color:'#111827',maxWidth:'130px',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}},rm.item_name?`${rm.item_code} — ${rm.item_name}`:rm.item_code),
							React.createElement('td',{key:'r',style:{padding:'6px 8px',color:'#374151'}},pf(rm.required_qty).toLocaleString()),
							React.createElement('td',{key:'t',style:{padding:'6px 8px',color:ok?'#059669':'#dc2626',fontWeight:'700'}},pf(rm.transferred_qty).toLocaleString()),
							React.createElement('td',{key:'a',style:{padding:'6px 8px',color:'#374151'}},pf(rm.available_qty_at_wip_warehouse).toLocaleString()),
							React.createElement('td',{key:'s',style:{padding:'6px 8px'}},
								React.createElement('span',{style:{padding:'2px 7px',borderRadius:'6px',fontSize:'10px',fontWeight:'800',background:ok?'#d1fae5':pt?'#fef3c7':'#fee2e2',color:ok?'#065f46':pt?'#92400e':'#991b1b'}},ok?'OK':pt?'Part.':'SHORT')
							)
						]);
					}))
				])
			)
		),

		// ── STOCK ENTRIES ──
		ses.length>0 && React.createElement(CollapsibleSection,{key:'se-sect',title:`📦 Stock Entries`,count:ses.length,defaultOpen:false},
			React.createElement('div',{key:'rows',style:{display:'flex',flexDirection:'column',gap:'4px',marginBottom:'4px'}},
				ses.map(se=>React.createElement('div',{key:se.name,style:{padding:'7px 10px',background:'#fafafa',borderRadius:'6px',display:'flex',justifyContent:'space-between',alignItems:'center',border:'1px solid #f0f0f0'}},[
					React.createElement('div',{key:'l',style:{display:'flex',alignItems:'center',gap:'8px'}}, [
						React.createElement('div',{key:'dot',style:{width:'8px',height:'8px',borderRadius:'50%',background:se.status==='Submitted'?'#10b981':'#f59e0b',flexShrink:0}}),
						React.createElement('span',{key:'n',style:{fontSize:'12px',fontWeight:'600',color:'#111827'}},se.name),
						React.createElement('span',{key:'tp',style:{fontSize:'11px',color:'#9ca3af'}},`— ${se.stock_entry_type}`)
					]),
					React.createElement('div',{key:'r',style:{display:'flex',gap:'8px',alignItems:'center',flexShrink:0}}, [
						React.createElement('span',{key:'d',style:{fontSize:'11px',color:'#9ca3af'}},fmtDate(se.posting_date)),
						React.createElement('span',{key:'s',style:{padding:'2px 8px',borderRadius:'6px',fontSize:'10px',fontWeight:'700',background:se.status==='Submitted'?'#d1fae5':'#fef3c7',color:se.status==='Submitted'?'#065f46':'#92400e'}},se.status)
					])
				]))
			)
		)
	]);
}

// ─── Hint / Loading / Empty ───────────────────────────────────────────────────
function WOHint() {
	return React.createElement('div',{style:{display:'flex',alignItems:'center',justifyContent:'center',minHeight:'220px',background:'white',borderRadius:'12px',border:'2px dashed #e2e8f0',boxShadow:'0 1px 4px rgba(0,0,0,.05)'}},
		React.createElement('div',{style:{textAlign:'center'}},[
			React.createElement('div',{key:'ic',style:{fontSize:'44px',opacity:.35,marginBottom:'10px'}},'⚙️'),
			React.createElement('p',{key:'t',style:{color:'#94a3b8',fontSize:'14px',fontWeight:'600'}},'Click a Work Order on the left'),
			React.createElement('p',{key:'s',style:{color:'#cbd5e1',fontSize:'12px',marginTop:'3px'}},'Open multiple WOs side by side')
		])
	);
}
function Spinner() {
	return React.createElement('div',{style:{display:'flex',alignItems:'center',justifyContent:'center',minHeight:'300px'}},
		React.createElement('div',{style:{textAlign:'center'}},[
			React.createElement('div',{key:'sp',style:{width:'48px',height:'48px',border:'3px solid #e2e8f0',borderTopColor:'#c9a84c',borderRadius:'50%',margin:'0 auto',animation:'spin .8s linear infinite'}}),
			React.createElement('p',{key:'tx',style:{marginTop:'14px',color:'#94a3b8',fontSize:'14px'}},'Calculating delivery risks...')
		])
	);
}
function Empty() {
	return React.createElement('div',{style:{display:'flex',alignItems:'center',justifyContent:'center',minHeight:'300px'}},
		React.createElement('div',{style:{textAlign:'center'}},[
			React.createElement('div',{key:'ic',style:{fontSize:'56px',marginBottom:'12px'}},'✅'),
			React.createElement('h3',{key:'h',style:{fontSize:'20px',fontWeight:'700',color:'#1e293b',marginBottom:'6px'}},'All Clear!'),
			React.createElement('p',{key:'p',style:{color:'#64748b',fontSize:'14px'}},'No active orders with delivery risk found.')
		])
	);
}
