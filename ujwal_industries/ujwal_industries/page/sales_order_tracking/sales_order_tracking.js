// Sales Order Tracking Dashboard
// Professional end-to-end tracking: SO → PP → WO → JC → Delivery

frappe.pages['sales_order_tracking'].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Sales Order Tracking Dashboard',
		single_column: true
	});

	// Add refresh button
	page.add_inner_button('Refresh', () => {
		window.location.reload();
	});

	// Initialize React app
	new SalesOrderTrackingDashboard(wrapper, page);
};

class SalesOrderTrackingDashboard {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.init();
	}

	init() {
		// Add CSS for animations
		this.addStyles();

		// Load external dependencies
		this.loadDependencies().then(() => {
			this.renderApp();
			this.setupRealtimeListeners();
		});
	}

	addStyles() {
		// Add spinner animation CSS
		if (!document.getElementById('sales-tracking-styles')) {
			const style = document.createElement('style');
			style.id = 'sales-tracking-styles';
			style.textContent = `
				@keyframes spin {
					from { transform: rotate(0deg); }
					to { transform: rotate(360deg); }
				}
				.sot-filter-input:focus {
					border-color: #667eea !important;
					box-shadow: 0 0 0 2px rgba(102,126,234,0.15) !important;
				}
			`;
			document.head.appendChild(style);
		}
	}

	loadDependencies() {
		return new Promise((resolve) => {
			// Check if already loaded
			if (window.React && window.ReactDOM) {
				resolve();
				return;
			}

			let loaded = 0;
			const checkLoaded = () => {
				loaded++;
				if (loaded === 2) resolve();
			};

			// Load React
			if (!window.React) {
				const react = document.createElement('script');
				react.src = 'https://unpkg.com/react@18/umd/react.production.min.js';
				react.crossOrigin = 'anonymous';
				react.onload = checkLoaded;
				document.head.appendChild(react);
			} else {
				checkLoaded();
			}

			// Load ReactDOM
			if (!window.ReactDOM) {
				const reactDOM = document.createElement('script');
				reactDOM.src = 'https://unpkg.com/react-dom@18/umd/react-dom.production.min.js';
				reactDOM.crossOrigin = 'anonymous';
				reactDOM.onload = checkLoaded;
				document.head.appendChild(reactDOM);
			} else {
				checkLoaded();
			}
		});
	}

	renderApp() {
		const container = document.createElement('div');
		container.id = 'sales-tracking-root';
		container.style.padding = '0';
		container.style.margin = '0';
		this.wrapper.querySelector('.page-content').appendChild(container);

		const root = ReactDOM.createRoot(container);
		root.render(React.createElement(App));
	}

	setupRealtimeListeners() {
		// Real-time updates via Socket.IO
		frappe.realtime.on('sales_order_update', (data) => {
			console.log('Sales Order updated:', data);
			// Trigger React re-render via custom event
			window.dispatchEvent(new CustomEvent('salesOrderUpdate', { detail: data }));
		});

		frappe.realtime.on('work_order_update', (data) => {
			console.log('Work Order updated:', data);
			window.dispatchEvent(new CustomEvent('workOrderUpdate', { detail: data }));
		});

		frappe.realtime.on('job_card_update', (data) => {
			console.log('Job Card updated:', data);
			window.dispatchEvent(new CustomEvent('jobCardUpdate', { detail: data }));
		});
	}
}

// Helper: build args object for get_sales_orders API calls
function buildFilterArgs(filters, pageOffset, pageSize) {
	return {
		days: 'all',
		limit_page_length: pageSize,
		limit_page_offset: pageOffset,
		sales_order_filter: (filters && filters.sales_order) || null,
		from_date: (filters && filters.from_date) || null,
		to_date: (filters && filters.to_date) || null,
		customer: (filters && filters.customer) || null,
		item: (filters && filters.item) || null,
		status: (filters && filters.status) || null
	};
}

// React App Component
function App() {
	const { useState, useEffect, useRef, useCallback } = React;

	const [salesOrders, setSalesOrders] = useState([]);
	const [loading, setLoading] = useState(true);
	const [loadingMore, setLoadingMore] = useState(false);
	const [hasMore, setHasMore] = useState(false);
	const [offset, setOffset] = useState(0);
	const [selectedOrder, setSelectedOrder] = useState(null);

	const EMPTY_FILTERS = { sales_order: '', from_date: '', to_date: '', customer: '', item: '', status: '' };
	const [filterInputs, setFilterInputs] = useState(EMPTY_FILTERS);
	const [activeFilters, setActiveFilters] = useState({});

	const sentinelRef = useRef(null);
	const activeFiltersRef = useRef({});
	const PAGE_SIZE = 6;

	// Keep ref in sync so real-time handlers always see latest filters
	useEffect(() => { activeFiltersRef.current = activeFilters; }, [activeFilters]);

	// Fetch (or re-fetch) whenever activeFilters changes
	useEffect(() => {
		setSalesOrders([]);
		setOffset(0);
		setHasMore(false);
		setLoading(true);
		frappe.call({
			method: 'ujwal_industries.api.sales_order_tracking.get_sales_orders',
			args: buildFilterArgs(activeFilters, 0, PAGE_SIZE),
			callback: (r) => {
				if (r.message) {
					setSalesOrders(r.message.data);
					setHasMore(r.message.has_more);
					setOffset(PAGE_SIZE);
				}
				setLoading(false);
			}
		});
	}, [activeFilters]);

	// Listen for real-time updates
	useEffect(() => {
		const handleUpdate = () => {
			setSalesOrders([]);
			setOffset(0);
			setLoading(true);
			frappe.call({
				method: 'ujwal_industries.api.sales_order_tracking.get_sales_orders',
				args: buildFilterArgs(activeFiltersRef.current, 0, PAGE_SIZE),
				callback: (r) => {
					if (r.message) {
						setSalesOrders(r.message.data);
						setHasMore(r.message.has_more);
						setOffset(PAGE_SIZE);
					}
					setLoading(false);
				}
			});
		};

		window.addEventListener('salesOrderUpdate', handleUpdate);
		window.addEventListener('workOrderUpdate', handleUpdate);
		window.addEventListener('jobCardUpdate', handleUpdate);

		return () => {
			window.removeEventListener('salesOrderUpdate', handleUpdate);
			window.removeEventListener('workOrderUpdate', handleUpdate);
			window.removeEventListener('jobCardUpdate', handleUpdate);
		};
	}, []);

	// Fetch next page
	const fetchMore = useCallback(() => {
		if (loadingMore || !hasMore) return;
		setLoadingMore(true);
		frappe.call({
			method: 'ujwal_industries.api.sales_order_tracking.get_sales_orders',
			args: buildFilterArgs(activeFilters, offset, PAGE_SIZE),
			callback: (r) => {
				if (r.message) {
					setSalesOrders(prev => [...prev, ...r.message.data]);
					setHasMore(r.message.has_more);
					setOffset(prev => prev + PAGE_SIZE);
				}
				setLoadingMore(false);
			}
		});
	}, [loadingMore, hasMore, offset, activeFilters]);

	// Intersection Observer on sentinel
	useEffect(() => {
		if (!sentinelRef.current) return;
		const observer = new IntersectionObserver((entries) => {
			if (entries[0].isIntersecting && hasMore && !loadingMore) {
				fetchMore();
			}
		}, { threshold: 0 });
		observer.observe(sentinelRef.current);
		return () => observer.disconnect();
	}, [hasMore, loadingMore, fetchMore]);

	const handleApplyFilters = () => setActiveFilters({ ...filterInputs });
	const handleClearFilters = () => {
		setFilterInputs(EMPTY_FILTERS);
		setActiveFilters({});
	};

	return React.createElement('div', {
		style: {
			minHeight: '100vh',
			background: 'linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)',
			padding: '20px',
			margin: '-15px',
			width: 'calc(100% + 30px)'
		}
	}, [
		// Filter Panel
		React.createElement(FilterPanel, {
			key: 'filters',
			filterInputs,
			setFilterInputs,
			onApply: handleApplyFilters,
			onClear: handleClearFilters
		}),

		// Main Content
		React.createElement('div', {
			key: 'content',
			style: {
				width: '100%',
				margin: '0'
			}
		}, [
			loading
				? React.createElement(LoadingState, { key: 'loading' })
				: salesOrders.length === 0
				? React.createElement(EmptyState, { key: 'empty' })
				: React.createElement(SalesOrderGrid, {
					key: 'grid',
					salesOrders,
					selectedOrder,
					setSelectedOrder
				})
		]),

		// Sentinel + Loading More
		!loading && React.createElement('div', {
			key: 'infinite-scroll'
		}, [
			React.createElement('div', {
				key: 'sentinel',
				ref: sentinelRef,
				style: { height: '10px' }
			}),
			loadingMore && React.createElement('div', {
				key: 'loading-more',
				style: {
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					padding: '24px 0',
					gap: '12px'
				}
			}, [
				React.createElement('div', {
					key: 'spinner',
					style: {
						width: '28px',
						height: '28px',
						border: '3px solid #e5e7eb',
						borderTopColor: '#667eea',
						borderRadius: '50%',
						animation: 'spin 0.7s linear infinite'
					}
				}),
				React.createElement('span', {
					key: 'text',
					style: { fontSize: '14px', color: '#6b7280', fontWeight: '500' }
				}, 'Loading more orders...')
			]),
			!hasMore && salesOrders.length > 0 && React.createElement('div', {
				key: 'end',
				style: { textAlign: 'center', padding: '20px 0', fontSize: '13px', color: '#9ca3af' }
			}, `Showing all ${salesOrders.length} orders`)
		]),

		// Detail Modal
		selectedOrder && React.createElement(OrderDetailModal, {
			key: 'modal',
			order: selectedOrder,
			onClose: () => setSelectedOrder(null)
		})
	]);
}

// Filter Panel Component
function FilterPanel({ filterInputs, setFilterInputs, onApply, onClear }) {
	const inputStyle = {
		height: '34px',
		padding: '0 10px',
		border: '1px solid #e5e7eb',
		borderRadius: '6px',
		fontSize: '13px',
		color: '#374151',
		background: 'white',
		outline: 'none',
		width: '100%',
		boxSizing: 'border-box',
		transition: 'border-color 0.15s'
	};

	const labelStyle = {
		fontSize: '11px',
		fontWeight: '600',
		color: '#6b7280',
		textTransform: 'uppercase',
		letterSpacing: '0.5px',
		marginBottom: '5px',
		display: 'block'
	};

	const update = (key, value) => setFilterInputs(prev => ({ ...prev, [key]: value }));

	const handleKeyDown = (e) => { if (e.key === 'Enter') onApply(); };

	return React.createElement('div', {
		style: {
			background: 'white',
			borderRadius: '12px',
			padding: '18px 22px',
			marginBottom: '20px',
			boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
			border: '1px solid #e5e7eb'
		}
	}, [
		React.createElement('div', {
			key: 'header',
			style: { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }
		}, [
			React.createElement('span', { key: 'icon', style: { fontSize: '16px' } }, '🔍'),
			React.createElement('span', {
				key: 'title',
				style: { fontSize: '14px', fontWeight: '600', color: '#111827' }
			}, 'Filters')
		]),

		React.createElement('div', {
			key: 'grid',
			style: {
				display: 'grid',
				gridTemplateColumns: 'repeat(auto-fill, minmax(155px, 1fr))',
				gap: '12px',
				alignItems: 'end'
			}
		}, [
			// Sales Order No
			React.createElement('div', { key: 'so' }, [
				React.createElement('label', { key: 'lbl', style: labelStyle }, 'Sales Order No'),
				React.createElement('input', {
					key: 'inp',
					type: 'text',
					className: 'sot-filter-input',
					placeholder: 'SAL-ORD-...',
					value: filterInputs.sales_order,
					onChange: (e) => update('sales_order', e.target.value),
					onKeyDown: handleKeyDown,
					style: inputStyle
				})
			]),

			// Customer
			React.createElement('div', { key: 'customer' }, [
				React.createElement('label', { key: 'lbl', style: labelStyle }, 'Customer'),
				React.createElement('input', {
					key: 'inp',
					type: 'text',
					className: 'sot-filter-input',
					placeholder: 'Name or Code',
					value: filterInputs.customer,
					onChange: (e) => update('customer', e.target.value),
					onKeyDown: handleKeyDown,
					style: inputStyle
				})
			]),

			// From Date
			React.createElement('div', { key: 'from' }, [
				React.createElement('label', { key: 'lbl', style: labelStyle }, 'From Date'),
				React.createElement('input', {
					key: 'inp',
					type: 'date',
					className: 'sot-filter-input',
					value: filterInputs.from_date,
					onChange: (e) => update('from_date', e.target.value),
					style: inputStyle
				})
			]),

			// To Date
			React.createElement('div', { key: 'to' }, [
				React.createElement('label', { key: 'lbl', style: labelStyle }, 'To Date'),
				React.createElement('input', {
					key: 'inp',
					type: 'date',
					className: 'sot-filter-input',
					value: filterInputs.to_date,
					onChange: (e) => update('to_date', e.target.value),
					style: inputStyle
				})
			]),

			// Item
			React.createElement('div', { key: 'item' }, [
				React.createElement('label', { key: 'lbl', style: labelStyle }, 'Item'),
				React.createElement('input', {
					key: 'inp',
					type: 'text',
					className: 'sot-filter-input',
					placeholder: 'Code or Name',
					value: filterInputs.item,
					onChange: (e) => update('item', e.target.value),
					onKeyDown: handleKeyDown,
					style: inputStyle
				})
			]),

			// Status
			React.createElement('div', { key: 'status' }, [
				React.createElement('label', { key: 'lbl', style: labelStyle }, 'Status'),
				React.createElement('select', {
					key: 'sel',
					className: 'sot-filter-input',
					value: filterInputs.status,
					onChange: (e) => update('status', e.target.value),
					style: { ...inputStyle, cursor: 'pointer' }
				}, [
					React.createElement('option', { key: 'all', value: '' }, 'All Statuses'),
					React.createElement('option', { key: 'draft', value: 'Draft' }, 'Draft'),
					React.createElement('option', { key: 'tdb', value: 'To Deliver and Bill' }, 'To Deliver and Bill'),
					React.createElement('option', { key: 'tb', value: 'To Bill' }, 'To Bill'),
					React.createElement('option', { key: 'td', value: 'To Deliver' }, 'To Deliver'),
					React.createElement('option', { key: 'comp', value: 'Completed' }, 'Completed'),
					React.createElement('option', { key: 'hold', value: 'On Hold' }, 'On Hold'),
					React.createElement('option', { key: 'canc', value: 'Cancelled' }, 'Cancelled')
				])
			]),

			// Buttons
			React.createElement('div', {
				key: 'actions',
				style: { display: 'flex', gap: '8px' }
			}, [
				React.createElement('button', {
					key: 'apply',
					onClick: onApply,
					style: {
						flex: 1,
						height: '34px',
						background: 'linear-gradient(135deg, #667eea, #764ba2)',
						color: 'white',
						border: 'none',
						borderRadius: '6px',
						fontSize: '13px',
						fontWeight: '600',
						cursor: 'pointer',
						transition: 'opacity 0.15s'
					},
					onMouseEnter: (e) => e.currentTarget.style.opacity = '0.88',
					onMouseLeave: (e) => e.currentTarget.style.opacity = '1'
				}, 'Apply'),
				React.createElement('button', {
					key: 'clear',
					onClick: onClear,
					style: {
						flex: 1,
						height: '34px',
						background: 'white',
						color: '#6b7280',
						border: '1px solid #e5e7eb',
						borderRadius: '6px',
						fontSize: '13px',
						fontWeight: '600',
						cursor: 'pointer'
					}
				}, 'Clear')
			])
		])
	]);
}

// Sales Order Grid
function SalesOrderGrid({ salesOrders, selectedOrder, setSelectedOrder }) {
	return React.createElement('div', {
		style: {
			display: 'grid',
			gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))',
			gap: '20px'
		}
	}, salesOrders.map((order) =>
		React.createElement(SalesOrderCard, {
			key: order.name,
			order,
			onClick: () => setSelectedOrder(order)
		})
	));
}

// Sales Order Card Component
function SalesOrderCard({ order, onClick }) {
	const getStatusColor = (status) => {
		const colors = {
			'Draft': { bg: '#f3f4f6', text: '#374151' },
			'To Deliver and Bill': { bg: '#dbeafe', text: '#1e40af' },
			'To Bill': { bg: '#fef3c7', text: '#92400e' },
			'To Deliver': { bg: '#fed7aa', text: '#9a3412' },
			'Completed': { bg: '#d1fae5', text: '#065f46' },
			'Cancelled': { bg: '#fee2e2', text: '#991b1b' }
		};
		return colors[status] || colors['Draft'];
	};

	const getProgressColor = (progress) => {
		if (progress < 30) return '#ef4444';
		if (progress < 70) return '#eab308';
		return '#22c55e';
	};

	const statusColor = getStatusColor(order.status);

	// Job execution metrics
	const jcTotal = order.job_card_count || 0;
	const jcDone = order.job_card_completed || 0;
	const jcPct = jcTotal > 0 ? Math.round((jcDone / jcTotal) * 100) : 0;
	const jcColor = jcTotal === 0 ? '#9ca3af'
		: jcPct < 30 ? '#ef4444'
		: jcPct < 70 ? '#f59e0b'
		: '#10b981';

	return React.createElement('div', {
		style: {
			background: 'white',
			borderRadius: '12px',
			boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
			border: '1px solid #e5e7eb',
			overflow: 'hidden',
			cursor: 'pointer',
			transition: 'box-shadow 0.2s'
		},
		onMouseEnter: (e) => e.currentTarget.style.boxShadow = '0 10px 15px rgba(0,0,0,0.1)',
		onMouseLeave: (e) => e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.1)',
		onClick
	}, [
		// Header
		React.createElement('div', {
			key: 'header',
			style: {
				padding: '20px',
				borderBottom: '1px solid #f3f4f6'
			}
		}, [
			React.createElement('div', {
				key: 'top',
				style: {
					display: 'flex',
					justifyContent: 'space-between',
					alignItems: 'flex-start',
					marginBottom: '12px'
				}
			}, [
				React.createElement('div', { key: 'info' }, [
					React.createElement('h3', {
						key: 'name',
						style: {
							fontSize: '18px',
							fontWeight: '600',
							color: '#111827',
							marginBottom: '4px'
						}
					}, order.name),
					// Customer: show name prominently, code as secondary
					React.createElement('div', { key: 'customer' }, [
						React.createElement('p', {
							key: 'cname',
							style: { fontSize: '14px', color: '#374151', fontWeight: '500' }
						}, order.customer_name || order.customer),
						order.customer_name && React.createElement('p', {
							key: 'ccode',
							style: { fontSize: '12px', color: '#9ca3af', marginTop: '1px' }
						}, order.customer)
					])
				]),
				React.createElement('span', {
					key: 'status',
					style: {
						padding: '4px 12px',
						borderRadius: '12px',
						fontSize: '12px',
						fontWeight: '500',
						backgroundColor: statusColor.bg,
						color: statusColor.text
					}
				}, order.status)
			]),
			// Dates row
			React.createElement('div', {
				key: 'dates',
				style: { display: 'flex', gap: '16px', marginTop: '8px', flexWrap: 'wrap' }
			}, [
				order.transaction_date && React.createElement('span', {
					key: 'ord',
					style: { fontSize: '12px', color: '#6b7280' }
				}, `📅 Order: ${formatDate(order.transaction_date)}`),
				order.delivery_date && React.createElement('span', {
					key: 'del',
					style: { fontSize: '12px', color: '#dc2626', fontWeight: '600' }
				}, `🚚 Delivery: ${formatDate(order.delivery_date)}`)
			]),
			// Progress Bars
			React.createElement('div', { key: 'progress', style: { marginTop: '10px' } }, [

				// Bar 1: Stage Progress
				React.createElement('div', { key: 'stage-bar', style: { marginBottom: '8px' } }, [
					React.createElement('div', {
						key: 'row',
						style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '3px' }
					}, [
						React.createElement('span', {
							key: 'lbl',
							style: { fontSize: '11px', fontWeight: '600', color: '#374151' }
						}, '📊 Stage Progress'),
						React.createElement('span', {
							key: 'val',
							style: { fontSize: '11px', fontWeight: '700', color: getProgressColor(order.progress) }
						}, `${order.stages_done || 0} / ${order.total_stages || 5} stages`)
					]),
					React.createElement('div', {
						key: 'track',
						style: { width: '100%', height: '7px', backgroundColor: '#e5e7eb', borderRadius: '4px', overflow: 'hidden' }
					}, React.createElement('div', {
						style: {
							height: '100%',
							width: `${order.progress}%`,
							backgroundColor: getProgressColor(order.progress),
							borderRadius: '4px',
							transition: 'width 0.3s'
						}
					}))
				]),

				// Bar 2: Job Execution
				React.createElement('div', { key: 'jc-bar' }, [
					React.createElement('div', {
						key: 'row',
						style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '3px' }
					}, [
						React.createElement('span', {
							key: 'lbl',
							style: { fontSize: '11px', fontWeight: '600', color: '#374151' }
						}, '⚙️ Job Execution'),
						React.createElement('span', {
							key: 'val',
							style: { fontSize: '11px', fontWeight: '700', color: jcColor }
						}, jcTotal > 0
							? `${jcDone} / ${jcTotal} done (${jcPct}%)`
							: 'No job cards yet')
					]),
					React.createElement('div', {
						key: 'track',
						style: { width: '100%', height: '7px', backgroundColor: '#e5e7eb', borderRadius: '4px', overflow: 'hidden' }
					}, React.createElement('div', {
						style: {
							height: '100%',
							width: `${jcPct}%`,
							backgroundColor: jcColor,
							borderRadius: '4px',
							transition: 'width 0.3s'
						}
					}))
				])
			])
		]),

		// Items section
		order.items && order.items.length > 0 && React.createElement('div', {
			key: 'items',
			style: {
				padding: '10px 20px 12px',
				borderBottom: '1px solid #f3f4f6',
				background: '#fafafa'
			}
		}, [
			React.createElement('p', {
				key: 'lbl',
				style: { fontSize: '11px', fontWeight: '600', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }
			}, 'Items'),
			...order.items.slice(0, 3).map((item, idx) =>
				React.createElement('div', {
					key: item.item_code + idx,
					style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '3px' }
				}, [
					React.createElement('span', {
						key: 'desc',
						style: { fontSize: '12px', color: '#374151', fontWeight: '500', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '220px' }
					}, `${item.item_code}${item.item_name ? ' — ' + item.item_name : ''}`),
					React.createElement('span', {
						key: 'qty',
						style: { fontSize: '11px', color: '#6b7280', whiteSpace: 'nowrap', marginLeft: '8px', flexShrink: 0 }
					}, `${Number(item.qty || 0).toLocaleString()} ${item.stock_uom || ''}`)
				])
			),
			order.items.length > 3 && React.createElement('p', {
				key: 'more',
				style: { fontSize: '11px', color: '#9ca3af', marginTop: '4px', fontStyle: 'italic' }
			}, `+${order.items.length - 3} more item${order.items.length - 3 > 1 ? 's' : ''}`)
		]),

		// Stats
		React.createElement('div', {
			key: 'stats',
			style: {
				display: 'grid',
				gridTemplateColumns: '1fr 1fr',
				gap: '16px',
				padding: '20px',
				backgroundColor: '#f9fafb'
			}
		}, [
			React.createElement(StatItem, {
				key: 'pp',
				icon: '📋',
				label: 'Production Plans',
				value: order.production_plan_count || 0
			}),
			React.createElement(StatItem, {
				key: 'wo',
				icon: '⚙️',
				label: 'Work Orders',
				value: order.work_order_count || 0
			}),
			React.createElement(StatItem, {
				key: 'jc',
				icon: '📊',
				label: 'Job Cards',
				value: order.job_card_count || 0
			}),
			React.createElement(StatItem, {
				key: 'dn',
				icon: '📦',
				label: 'Deliveries',
				value: order.delivery_note_count || 0
			})
		])
	]);
}

// Stat Item Component
function StatItem({ icon, label, value }) {
	return React.createElement('div', {
		style: { textAlign: 'center' }
	}, [
		React.createElement('div', {
			key: 'icon',
			style: { fontSize: '24px', marginBottom: '4px' }
		}, icon),
		React.createElement('div', {
			key: 'value',
			style: { fontSize: '18px', fontWeight: 'bold', color: '#111827' }
		}, value),
		React.createElement('div', {
			key: 'label',
			style: { fontSize: '12px', color: '#6b7280' }
		}, label)
	]);
}

// Loading State
function LoadingState() {
	return React.createElement('div', {
		style: {
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			minHeight: '300px'
		}
	}, React.createElement('div', {
		style: { textAlign: 'center' }
	}, [
		React.createElement('div', {
			key: 'spinner',
			style: {
				width: '48px',
				height: '48px',
				border: '3px solid #e5e7eb',
				borderTopColor: '#3b82f6',
				borderRadius: '50%',
				margin: '0 auto',
				animation: 'spin 1s linear infinite'
			}
		}),
		React.createElement('p', {
			key: 'text',
			style: {
				marginTop: '16px',
				color: '#6b7280',
				fontSize: '14px'
			}
		}, 'Loading sales orders...')
	]));
}

// Empty State
function EmptyState() {
	return React.createElement('div', {
		style: {
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			minHeight: '300px'
		}
	}, React.createElement('div', {
		style: { textAlign: 'center' }
	}, [
		React.createElement('div', {
			key: 'icon',
			style: { fontSize: '60px', marginBottom: '16px' }
		}, '📦'),
		React.createElement('h3', {
			key: 'title',
			style: {
				fontSize: '20px',
				fontWeight: '600',
				color: '#111827',
				marginBottom: '8px'
			}
		}, 'No Sales Orders Found'),
		React.createElement('p', {
			key: 'desc',
			style: { color: '#6b7280', fontSize: '14px' }
		}, 'No sales orders match the current filters.')
	]));
}

// Order Detail Modal
function OrderDetailModal({ order, onClose }) {
	const { useState, useEffect } = React;
	const [details, setDetails] = useState(null);
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		frappe.call({
			method: 'ujwal_industries.api.sales_order_tracking.get_sales_order_detail',
			args: { sales_order: order.name },
			callback: (r) => {
				if (r.message) {
					setDetails(r.message);
				}
				setLoading(false);
			}
		});
	}, [order.name]);

	return React.createElement('div', {
		style: {
			position: 'fixed',
			top: 0,
			left: 0,
			right: 0,
			bottom: 0,
			backgroundColor: 'rgba(0,0,0,0.5)',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			zIndex: 1000,
			padding: '16px'
		},
		onClick: onClose
	}, React.createElement('div', {
		style: {
			background: 'white',
			borderRadius: '12px',
			maxWidth: '1000px',
			width: '100%',
			maxHeight: '90vh',
			overflowY: 'auto'
		},
		onClick: (e) => e.stopPropagation()
	}, [
		// Header
		React.createElement('div', {
			key: 'header',
			style: {
				padding: '24px',
				borderBottom: '1px solid #e5e7eb',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
				color: 'white',
				borderRadius: '12px 12px 0 0'
			}
		}, [
			React.createElement('div', { key: 'info' }, [
				React.createElement('h2', {
					key: 'title',
					style: {
						fontSize: '24px',
						fontWeight: 'bold',
						marginBottom: '4px'
					}
				}, order.name),
				React.createElement('p', {
					key: 'customer',
					style: { fontSize: '14px', opacity: 0.9 }
				}, order.customer_name
					? `${order.customer_name}  (${order.customer})`
					: order.customer)
			]),
			React.createElement('button', {
				key: 'close',
				style: {
					fontSize: '24px',
					color: 'white',
					background: 'rgba(255,255,255,0.2)',
					border: 'none',
					cursor: 'pointer',
					padding: '8px 12px',
					borderRadius: '6px'
				},
				onClick: onClose
			}, '✕')
		]),

		// Content
		React.createElement('div', {
			key: 'content',
			style: { padding: '24px' }
		}, loading
			? React.createElement('div', {
				style: { textAlign: 'center', padding: '40px', color: '#6b7280' }
			}, 'Loading details...')
			: details
			? React.createElement(TrackingTimeline, { details })
			: React.createElement('p', {
				style: { color: '#6b7280', textAlign: 'center', padding: '40px' }
			}, 'No tracking details available')
		)
	]));
}

// Date formatter helper
function formatDate(d) {
	if (!d || d === 'None' || d === 'null' || d === '') return '—';
	const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
	// Split on space or T to handle both "2026-01-23" and "2026-01-23 00:00:00"
	const datePart = String(d).split(' ')[0].split('T')[0];
	const parts = datePart.split('-');
	if (parts.length < 3) return '—';
	const year = parseInt(parts[0], 10);
	const month = parseInt(parts[1], 10) - 1;
	const day = parseInt(parts[2], 10);
	if (isNaN(year) || isNaN(month) || isNaN(day)) return '—';
	return `${day} ${months[month]} ${year}`;
}

// Journey Stepper Component
function JourneyStepper({ details, completedJC, totalJC }) {
	const stagesData = [
		{ label: 'Order', sub: 'Created', icon: '📝', done: true },
		{ label: 'Production', sub: details.production_plans.length > 0 ? details.production_plans.length + ' plan' + (details.production_plans.length !== 1 ? 's' : '') : 'Pending', icon: '📋', done: details.production_plans.length > 0 },
		{ label: 'Work Orders', sub: details.work_orders.length > 0 ? details.work_orders.length + ' created' : 'Pending', icon: '⚙️', done: details.work_orders.length > 0 },
		{ label: 'Job Cards', sub: totalJC > 0 ? completedJC + '/' + totalJC + ' done' : 'Pending', icon: '📊', done: completedJC > 0 },
		{ label: 'Delivery', sub: details.delivery_notes.length > 0 ? details.delivery_notes.length + ' note' + (details.delivery_notes.length !== 1 ? 's' : '') : 'Pending', icon: '📦', done: details.delivery_notes.length > 0 }
	];

	// Find how far the green line should stretch (consecutive done stages)
	let consecutiveDone = 0;
	for (let i = 0; i < stagesData.length; i++) {
		if (stagesData[i].done) consecutiveDone = i + 1;
		else break;
	}
	const lastGreenIdx = consecutiveDone - 1;
	const greenPercent = lastGreenIdx > 0 ? (lastGreenIdx / (stagesData.length - 1)) * 100 : 0;

	let activeIndex = stagesData.findIndex(s => !s.done);
	if (activeIndex === -1) activeIndex = stagesData.length;

	const circleSize = 36;

	return React.createElement('div', {
		style: {
			background: 'white',
			borderRadius: '10px',
			padding: '20px 28px 16px',
			marginBottom: '24px',
			border: '1px solid #e5e7eb',
			boxShadow: '0 2px 8px rgba(0,0,0,0.06)'
		}
	}, [
		React.createElement('p', {
			key: 'title',
			style: { fontSize: '11px', fontWeight: '600', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '1px', textAlign: 'center', marginBottom: '18px' }
		}, 'Order Journey'),

		React.createElement('div', {
			key: 'stepper-wrapper',
			style: { position: 'relative', minWidth: '320px' }
		}, [
			// Grey background line
			React.createElement('div', {
				key: 'line-bg',
				style: {
					position: 'absolute',
					top: (circleSize / 2) + 'px',
					left: (circleSize / 2) + 'px',
					right: (circleSize / 2) + 'px',
					height: '3px',
					transform: 'translateY(-50%)',
					background: '#e5e7eb',
					borderRadius: '2px',
					zIndex: 0
				}
			}),
			// Green progress line
			greenPercent > 0 && React.createElement('div', {
				key: 'line-fg',
				style: {
					position: 'absolute',
					top: (circleSize / 2) + 'px',
					left: (circleSize / 2) + 'px',
					width: `calc((100% - ${circleSize}px) * ${greenPercent / 100})`,
					height: '3px',
					transform: 'translateY(-50%)',
					background: 'linear-gradient(90deg, #10b981, #34d399)',
					borderRadius: '2px',
					zIndex: 0,
					transition: 'width 0.6s ease'
				}
			}),
			// Stage circles + labels
			React.createElement('div', {
				key: 'stages',
				style: { display: 'flex', justifyContent: 'space-between', position: 'relative', zIndex: 1 }
			}, stagesData.map((stage, i) => {
				const isDone = stage.done;
				const isActive = i === activeIndex;
				return React.createElement('div', {
					key: 'stage-' + i,
					style: { display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0, width: '70px' }
				}, [
					React.createElement('div', {
						key: 'circle',
						style: {
							width: circleSize + 'px',
							height: circleSize + 'px',
							borderRadius: '50%',
							background: isDone ? 'linear-gradient(135deg, #10b981, #34d399)' : isActive ? 'linear-gradient(135deg, #667eea, #764ba2)' : 'white',
							border: isDone || isActive ? 'none' : '2px dashed #d1d5db',
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							fontSize: isDone ? '18px' : '15px',
							color: 'white',
							boxShadow: isActive ? '0 0 12px rgba(102,126,234,0.45)' : isDone ? '0 0 8px rgba(16,185,129,0.3)' : '0 2px 4px rgba(0,0,0,0.08)'
						}
					}, isDone ? '✓' : stage.icon),
					React.createElement('p', {
						key: 'label',
						style: { fontSize: '11px', fontWeight: '600', color: isDone ? '#065f46' : isActive ? '#4f46e5' : '#6b7280', marginTop: '8px', textAlign: 'center', lineHeight: '1.3' }
					}, stage.label),
					React.createElement('p', {
						key: 'sub',
						style: { fontSize: '10px', color: isDone ? '#6b7280' : '#9ca3af', marginTop: '2px', textAlign: 'center' }
					}, stage.sub)
				]);
			}))
		])
	]);
}

// Tracking Timeline Component
function TrackingTimeline({ details }) {
	const completedJC = (details.job_cards || []).filter(jc => jc.status === 'Completed').length;
	const totalJC = (details.job_cards || []).length;
	const overallPct = totalJC > 0 ? Math.round((completedJC / totalJC) * 100) : 0;

	return React.createElement('div', {}, [
		// SO Info Bar - dates + amount
		React.createElement('div', {
			key: 'so-bar',
			style: {
				display: 'grid',
				gridTemplateColumns: '1fr 1fr 1fr',
				gap: '12px',
				marginBottom: '24px'
			}
		}, [
			React.createElement('div', {
				key: 'order-date',
				style: {
					background: 'linear-gradient(135deg, #667eea, #764ba2)',
					borderRadius: '10px',
					padding: '14px 16px',
					color: 'white',
					boxShadow: '0 4px 12px rgba(102,126,234,0.3)'
				}
			}, [
				React.createElement('p', {
					key: 'label',
					style: { fontSize: '11px', opacity: 0.8, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }
				}, '📅 Order Date'),
				React.createElement('p', {
					key: 'val',
					style: { fontSize: '16px', fontWeight: '700' }
				}, formatDate(details.sales_order.transaction_date))
			]),
			React.createElement('div', {
				key: 'delivery-date',
				style: {
					background: 'linear-gradient(135deg, #f093fb, #f5576c)',
					borderRadius: '10px',
					padding: '14px 16px',
					color: 'white',
					boxShadow: '0 4px 12px rgba(240,147,251,0.3)'
				}
			}, [
				React.createElement('p', {
					key: 'label',
					style: { fontSize: '11px', opacity: 0.8, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }
				}, '🚚 Delivery Date'),
				React.createElement('p', {
					key: 'val',
					style: { fontSize: '16px', fontWeight: '700' }
				}, formatDate(details.sales_order.delivery_date))
			]),
			React.createElement('div', {
				key: 'amount',
				style: {
					background: 'linear-gradient(135deg, #4facfe, #00f2fe)',
					borderRadius: '10px',
					padding: '14px 16px',
					color: 'white',
					boxShadow: '0 4px 12px rgba(79,172,254,0.3)'
				}
			}, [
				React.createElement('p', {
					key: 'label',
					style: { fontSize: '11px', opacity: 0.8, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }
				}, '💰 Grand Total'),
				React.createElement('p', {
					key: 'val',
					style: { fontSize: '16px', fontWeight: '700' }
				}, `₹ ${Number(details.sales_order.grand_total || 0).toLocaleString()}`)
			])
		]),

		// Journey Stepper
		React.createElement(JourneyStepper, {
			key: 'journey',
			details,
			completedJC,
			totalJC
		}),

		// Overall Progress Bar
		React.createElement('div', {
			key: 'overall-progress',
			style: {
				background: 'white',
				borderRadius: '10px',
				padding: '16px 20px',
				marginBottom: '24px',
				border: '1px solid #e5e7eb',
				boxShadow: '0 2px 8px rgba(0,0,0,0.06)'
			}
		}, [
			React.createElement('div', {
				key: 'top',
				style: { display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }
			}, [
				React.createElement('span', {
					key: 'label',
					style: { fontSize: '14px', fontWeight: '600', color: '#374151' }
				}, 'Overall Completion'),
				React.createElement('span', {
					key: 'pct',
					style: { fontSize: '14px', fontWeight: '700', color: overallPct === 100 ? '#10b981' : '#667eea' }
				}, `${overallPct}%`)
			]),
			React.createElement('div', {
				key: 'bar-bg',
				style: {
					height: '10px',
					background: '#f3f4f6',
					borderRadius: '5px',
					overflow: 'hidden'
				}
			}, React.createElement('div', {
				style: {
					height: '100%',
					width: `${overallPct}%`,
					background: overallPct === 100 ? 'linear-gradient(90deg, #10b981, #34d399)' : 'linear-gradient(90deg, #667eea, #764ba2)',
					borderRadius: '5px',
					transition: 'width 0.6s ease'
				}
			})),
			React.createElement('p', {
				key: 'sub',
				style: { fontSize: '12px', color: '#9ca3af', marginTop: '6px' }
			}, `${completedJC} of ${totalJC} Job Cards completed`)
		]),

		// Production Plans with nested Work Orders
		...details.production_plans.map((pp) =>
			React.createElement(ProductionPlanSection, {
				key: pp.name,
				productionPlan: pp,
				workOrders: details.work_orders.filter(wo => wo.production_plan === pp.name),
				jobCards: details.job_cards,
				stockEntries: details.stock_entries || []
			})
		),

		// Work Orders without Production Plan
		details.work_orders.filter(wo => !wo.production_plan).length > 0 &&
		React.createElement('div', {
			key: 'direct-wo-section',
			style: {
				marginBottom: '20px',
				borderRadius: '10px',
				overflow: 'hidden',
				boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
				border: '1px solid #e5e7eb'
			}
		}, [
			React.createElement('div', {
				key: 'header',
				style: {
					background: '#f9fafb',
					padding: '14px 18px',
					borderBottom: '1px solid #e5e7eb',
					display: 'flex',
					alignItems: 'center',
					gap: '10px'
				}
			}, [
				React.createElement('span', { key: 'icon', style: { fontSize: '20px' } }, '⚙️'),
				React.createElement('h3', {
					key: 'title',
					style: { fontSize: '15px', fontWeight: '600', color: '#111827' }
				}, 'Direct Work Orders')
			]),
			React.createElement('div', {
				key: 'work-orders',
				style: { padding: '14px' }
			}, details.work_orders.filter(wo => !wo.production_plan).map(wo =>
				React.createElement(WorkOrderSection, {
					key: wo.name,
					workOrder: wo,
					jobCards: details.job_cards.filter(jc => jc.work_order === wo.name),
					stockEntries: (details.stock_entries || []).filter(se => se.work_order === wo.name)
				})
			))
		]),

		// Delivery Notes
		details.delivery_notes.length > 0 && React.createElement('div', {
			key: 'delivery-section',
			style: {
				borderRadius: '10px',
				overflow: 'hidden',
				boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
				border: '1px solid #10b981',
				marginBottom: '20px'
			}
		}, [
			React.createElement('div', {
				key: 'header',
				style: {
					background: 'linear-gradient(135deg, #d1fae5, #a7f3d0)',
					padding: '14px 18px',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between'
				}
			}, [
				React.createElement('div', {
					key: 'left',
					style: { display: 'flex', alignItems: 'center', gap: '10px' }
				}, [
					React.createElement('span', { key: 'icon', style: { fontSize: '20px' } }, '📦'),
					React.createElement('h3', {
						key: 'title',
						style: { fontSize: '15px', fontWeight: '600', color: '#065f46' }
					}, `Delivery Notes`)
				]),
				React.createElement('span', {
					key: 'count',
					style: {
						background: '#10b981',
						color: 'white',
						borderRadius: '12px',
						padding: '3px 10px',
						fontSize: '12px',
						fontWeight: '600'
					}
				}, details.delivery_notes.length)
			]),
			React.createElement('div', {
				key: 'body',
				style: { padding: '14px', background: 'white' }
			}, details.delivery_notes.map(dn =>
				React.createElement('div', {
					key: dn.name,
					style: {
						background: '#f0fdf4',
						padding: '12px 14px',
						borderRadius: '8px',
						marginBottom: '8px',
						display: 'flex',
						justifyContent: 'space-between',
						alignItems: 'center',
						border: '1px solid #bbf7d0'
					}
				}, [
					React.createElement('div', { key: 'info' }, [
						React.createElement('p', {
							key: 'name',
							style: { fontWeight: '600', color: '#065f46', fontSize: '14px' }
						}, dn.name),
						React.createElement('p', {
							key: 'date',
							style: { fontSize: '12px', color: '#6b7280', marginTop: '3px' }
						}, `📅 ${formatDate(dn.posting_date)}`)
					]),
					React.createElement('span', {
						key: 'status',
						style: {
							padding: '4px 12px',
							borderRadius: '12px',
							fontSize: '12px',
							fontWeight: '600',
							backgroundColor: '#d1fae5',
							color: '#065f46'
						}
					}, dn.status)
				])
			))
		]),
	]);
}

// Production Plan Section Component
function ProductionPlanSection({ productionPlan, workOrders, jobCards, stockEntries }) {
	const getPPStatusStyle = (status) => {
		if (status === 'Submitted') return { bg: '#dbeafe', text: '#1e40af' };
		if (status === 'In Process') return { bg: '#ede9fe', text: '#5b21b6' };
		if (status === 'Material Requested') return { bg: '#fef3c7', text: '#92400e' };
		if (status === 'Draft') return { bg: '#f3f4f6', text: '#374151' };
		return { bg: '#dbeafe', text: '#1e40af' };
	};
	const ppStyle = getPPStatusStyle(productionPlan.status);

	return React.createElement('div', {
		style: {
			marginBottom: '20px',
			borderRadius: '10px',
			overflow: 'hidden',
			boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
			border: '1px solid #e0e7ff'
		}
	}, [
		// PP Header
		React.createElement('div', {
			key: 'header',
			style: {
				background: 'linear-gradient(135deg, #eef2ff, #e0e7ff)',
				padding: '14px 18px',
				display: 'flex',
				justifyContent: 'space-between',
				alignItems: 'center'
			}
		}, [
			React.createElement('div', {
				key: 'left',
				style: { display: 'flex', alignItems: 'center', gap: '12px' }
			}, [
				React.createElement('div', {
					key: 'icon',
					style: {
						width: '36px',
						height: '36px',
						borderRadius: '8px',
						background: 'white',
						boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						fontSize: '18px'
					}
				}, '📋'),
				React.createElement('div', { key: 'info' }, [
					React.createElement('h3', {
						key: 'name',
						style: { fontSize: '15px', fontWeight: '700', color: '#1e1b4b' }
					}, productionPlan.name),
					React.createElement('p', {
						key: 'date',
						style: { fontSize: '12px', color: '#6366f1', marginTop: '2px' }
					}, `📅 Created: ${formatDate(productionPlan.posting_date)}`)
				])
			]),
			React.createElement('span', {
				key: 'status',
				style: {
					padding: '5px 14px',
					borderRadius: '12px',
					fontSize: '12px',
					fontWeight: '600',
					backgroundColor: ppStyle.bg,
					color: ppStyle.text
				}
			}, productionPlan.status)
		]),

		// Work Orders
		React.createElement('div', {
			key: 'work-orders',
			style: { padding: '14px', background: 'white' }
		}, workOrders.length > 0
			? workOrders.map(wo =>
				React.createElement(WorkOrderSection, {
					key: wo.name,
					workOrder: wo,
					jobCards: jobCards.filter(jc => jc.work_order === wo.name),
					stockEntries: stockEntries.filter(se => se.work_order === wo.name)
				})
			)
			: React.createElement('p', {
				style: { textAlign: 'center', color: '#9ca3af', padding: '18px', fontStyle: 'italic', fontSize: '13px' }
			}, 'No Work Orders created yet')
		)
	]);
}

// Work Order Section Component
function WorkOrderSection({ workOrder, jobCards, stockEntries }) {
	const producedPct = workOrder.qty > 0 ? Math.round((Number(workOrder.produced_qty || 0) / Number(workOrder.qty)) * 100) : 0;

	const getWOStatusStyle = (status) => {
		if (status === 'Completed') return { bg: '#d1fae5', text: '#065f46', dot: '#10b981' };
		if (status === 'In Process') return { bg: '#dbeafe', text: '#1e40af', dot: '#3b82f6' };
		if (status === 'Not Started') return { bg: '#f3f4f6', text: '#6b7280', dot: '#9ca3af' };
		if (status === 'Draft') return { bg: '#f3f4f6', text: '#374151', dot: '#9ca3af' };
		return { bg: '#fef3c7', text: '#92400e', dot: '#f59e0b' };
	};
	const woStyle = getWOStatusStyle(workOrder.status);

	const getJCStatusStyle = (status) => {
		if (status === 'Completed') return { bg: '#d1fae5', text: '#065f46', dot: '#10b981' };
		if (status === 'Working') return { bg: '#dbeafe', text: '#1e40af', dot: '#3b82f6' };
		if (status === 'On Hold') return { bg: '#fee2e2', text: '#991b1b', dot: '#ef4444' };
		if (status === 'Open') return { bg: '#ede9fe', text: '#5b21b6', dot: '#8b5cf6' };
		return { bg: '#fef3c7', text: '#92400e', dot: '#f59e0b' };
	};

	// Build item display: code + name if available
	const itemDisplay = workOrder.production_item_name
		? `${workOrder.production_item} — ${workOrder.production_item_name}`
		: workOrder.production_item;

	return React.createElement('div', {
		style: {
			background: 'white',
			border: '1px solid #fcd34d',
			borderRadius: '10px',
			marginBottom: '14px',
			overflow: 'hidden',
			boxShadow: '0 2px 6px rgba(245,158,11,0.12)'
		}
	}, [
		// WO Header
		React.createElement('div', {
			key: 'header',
			style: {
				background: 'linear-gradient(135deg, #fffbeb, #fef3c7)',
				padding: '14px 16px',
				display: 'flex',
				justifyContent: 'space-between',
				alignItems: 'flex-start'
			}
		}, [
			React.createElement('div', {
				key: 'left',
				style: { display: 'flex', alignItems: 'flex-start', gap: '12px' }
			}, [
				React.createElement('div', {
					key: 'icon',
					style: {
						width: '34px',
						height: '34px',
						borderRadius: '8px',
						background: 'white',
						boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						fontSize: '18px',
						flexShrink: 0
					}
				}, '⚙️'),
				React.createElement('div', { key: 'info' }, [
					React.createElement('h4', {
						key: 'name',
						style: { fontSize: '15px', fontWeight: '700', color: '#92400e' }
					}, workOrder.name),
					React.createElement('p', {
						key: 'item',
						style: { fontSize: '12px', color: '#78716c', marginTop: '3px' }
					}, `Item: ${itemDisplay}`),
					React.createElement('div', {
						key: 'dates',
						style: { display: 'flex', gap: '16px', marginTop: '6px' }
					}, [
						workOrder.planned_start_date && React.createElement('span', {
							key: 'planned',
							style: { fontSize: '11px', color: '#78716c' }
						}, `📅 Planned: ${formatDate(workOrder.planned_start_date)}`),
						workOrder.actual_start_date && React.createElement('span', {
							key: 'actual',
							style: { fontSize: '11px', color: '#065f46', fontWeight: '600' }
						}, `✅ Started: ${formatDate(workOrder.actual_start_date)}`)
					])
				])
			]),
			React.createElement('span', {
				key: 'status',
				style: {
					padding: '4px 12px',
					borderRadius: '12px',
					fontSize: '12px',
					fontWeight: '600',
					backgroundColor: woStyle.bg,
					color: woStyle.text,
					whiteSpace: 'nowrap'
				}
			}, workOrder.status)
		]),

		// Completion % Bar
		React.createElement('div', {
			key: 'progress',
			style: {
				padding: '10px 16px',
				background: '#fefce8',
				borderBottom: '1px solid #fef08a'
			}
		}, [
			React.createElement('div', {
				key: 'top',
				style: { display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }
			}, [
				React.createElement('span', {
					key: 'label',
					style: { fontSize: '12px', fontWeight: '600', color: '#78716c' }
				}, `Production: ${Number(workOrder.produced_qty || 0).toLocaleString()} / ${Number(workOrder.qty).toLocaleString()}`),
				React.createElement('span', {
					key: 'pct',
					style: { fontSize: '12px', fontWeight: '700', color: producedPct === 100 ? '#10b981' : '#f59e0b' }
				}, `${producedPct}%`)
			]),
			React.createElement('div', {
				key: 'bar-bg',
				style: {
					height: '6px',
					background: '#fef08a',
					borderRadius: '3px',
					overflow: 'hidden'
				}
			}, React.createElement('div', {
				style: {
					height: '100%',
					width: `${producedPct}%`,
					background: producedPct === 100 ? 'linear-gradient(90deg, #10b981, #34d399)' : 'linear-gradient(90deg, #f59e0b, #fbbf24)',
					borderRadius: '3px',
					transition: 'width 0.5s ease'
				}
			}))
		]),

		// Job Cards
		React.createElement('div', {
			key: 'job-cards',
			style: { padding: '14px 16px', borderBottom: stockEntries.length > 0 ? '1px solid #f3f4f6' : 'none' }
		}, [
			React.createElement('div', {
				key: 'title-row',
				style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }
			}, [
				React.createElement('h5', {
					key: 'title',
					style: { fontSize: '13px', fontWeight: '600', color: '#374151' }
				}, '📊 Job Cards'),
				React.createElement('span', {
					key: 'count',
					style: {
						background: '#ede9fe',
						color: '#5b21b6',
						borderRadius: '10px',
						padding: '2px 8px',
						fontSize: '11px',
						fontWeight: '600'
					}
				}, jobCards.length)
			]),
			jobCards.length > 0
				? React.createElement('div', {
					key: 'cards',
					style: { display: 'flex', flexDirection: 'column', gap: '6px' }
				}, jobCards.map(jc => {
					const jcStyle = getJCStatusStyle(jc.status);
					return React.createElement('div', {
						key: jc.name,
						style: {
							padding: '9px 12px',
							background: '#fafafa',
							borderRadius: '7px',
							display: 'flex',
							justifyContent: 'space-between',
							alignItems: 'center',
							border: '1px solid #f0f0f0'
						}
					}, [
						React.createElement('div', {
							key: 'info',
							style: { display: 'flex', alignItems: 'center', gap: '10px' }
						}, [
							React.createElement('div', {
								key: 'dot',
								style: {
									width: '10px',
									height: '10px',
									borderRadius: '50%',
									backgroundColor: jcStyle.dot,
									flexShrink: 0,
									boxShadow: `0 0 4px ${jcStyle.dot}66`
								}
							}),
							React.createElement('span', {
								key: 'name',
								style: { fontSize: '13px', fontWeight: '500', color: '#111827' }
							}, jc.name),
							React.createElement('span', {
								key: 'op',
								style: { fontSize: '12px', color: '#9ca3af' }
							}, `- ${jc.operation}`)
						]),
						React.createElement('div', {
							key: 'right',
							style: { display: 'flex', alignItems: 'center', gap: '12px' }
						}, [
							jc.actual_start_date && React.createElement('span', {
								key: 'date',
								style: { fontSize: '11px', color: '#9ca3af' }
							}, formatDate(jc.actual_start_date)),
							React.createElement('span', {
								key: 'status',
								style: {
									padding: '3px 10px',
									borderRadius: '10px',
									fontSize: '11px',
									fontWeight: '600',
									backgroundColor: jcStyle.bg,
									color: jcStyle.text
								}
							}, jc.status)
						])
					]);
				}))
				: React.createElement('p', {
					key: 'empty',
					style: { fontSize: '12px', color: '#9ca3af', fontStyle: 'italic' }
				}, 'No Job Cards yet')
		]),

		// Stock Entries
		stockEntries.length > 0 && React.createElement('div', {
			key: 'stock-entries',
			style: { padding: '14px 16px', background: '#fefce8' }
		}, [
			React.createElement('div', {
				key: 'title-row',
				style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }
			}, [
				React.createElement('h5', {
					key: 'title',
					style: { fontSize: '13px', fontWeight: '600', color: '#374151' }
				}, '📦 Stock Entries'),
				React.createElement('span', {
					key: 'count',
					style: {
						background: '#d1fae5',
						color: '#065f46',
						borderRadius: '10px',
						padding: '2px 8px',
						fontSize: '11px',
						fontWeight: '600'
					}
				}, stockEntries.length)
			]),
			React.createElement('div', {
				key: 'entries',
				style: { display: 'flex', flexDirection: 'column', gap: '6px' }
			}, stockEntries.map(se =>
				React.createElement('div', {
					key: se.name,
					style: {
						padding: '9px 12px',
						background: 'white',
						borderRadius: '7px',
						display: 'flex',
						justifyContent: 'space-between',
						alignItems: 'center',
						border: '1px solid #f0f0f0'
					}
				}, [
					React.createElement('div', {
						key: 'info',
						style: { display: 'flex', alignItems: 'center', gap: '10px' }
					}, [
						React.createElement('div', {
							key: 'dot',
							style: {
								width: '10px',
								height: '10px',
								borderRadius: '50%',
								backgroundColor: se.status === 'Submitted' ? '#10b981' : '#f59e0b',
								flexShrink: 0,
								boxShadow: se.status === 'Submitted' ? '0 0 4px #10b98166' : '0 0 4px #f59e0b66'
							}
						}),
						React.createElement('span', {
							key: 'name',
							style: { fontSize: '13px', fontWeight: '500', color: '#111827' }
						}, se.name),
						React.createElement('span', {
							key: 'type',
							style: { fontSize: '12px', color: '#9ca3af' }
						}, `- ${se.stock_entry_type}`)
					]),
					React.createElement('div', {
						key: 'right',
						style: { display: 'flex', alignItems: 'center', gap: '12px' }
					}, [
						React.createElement('span', {
							key: 'date',
							style: { fontSize: '11px', color: '#9ca3af' }
						}, formatDate(se.posting_date)),
						React.createElement('span', {
							key: 'status',
							style: {
								padding: '3px 10px',
								borderRadius: '10px',
								fontSize: '11px',
								fontWeight: '600',
								backgroundColor: se.status === 'Submitted' ? '#d1fae5' : '#fef3c7',
								color: se.status === 'Submitted' ? '#065f46' : '#92400e'
							}
						}, se.status)
					])
				])
			))
		])
	]);
}
