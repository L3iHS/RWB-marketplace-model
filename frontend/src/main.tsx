import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Dashboard, Filters, History, Order, Questions, Report, DemoStatus } from './types';
import './styles.css';

type Section = 'overview' | 'sales' | 'delivery' | 'quality' | 'questions' | 'history' | 'demo';
const sections: { id: Section; label: string; icon: string; title: string; description: string }[] = [
  { id: 'overview', label: 'Обзор', icon: '▦', title: 'Продажи и исполнение', description: 'От общей картины к конкретному заказу' },
  { id: 'sales', label: 'Продажи', icon: '▥', title: 'Структура продаж', description: 'Категории, продавцы и состав заказов' },
  { id: 'delivery', label: 'Доставка', icon: '▱', title: 'Исполнение заказов', description: 'Статусы, сроки и задержки по штатам покупателя' },
  { id: 'quality', label: 'Качество', icon: '◇', title: 'Качество данных', description: 'Проверки всего набора и сущности, требующие внимания' },
  { id: 'questions', label: 'Ответы 6–10', icon: '≡', title: 'Ответы на вопросы 6–10', description: 'Блок Б: проверенные расчёты, исходный SQL и выгрузки' },
  { id: 'history', label: 'История', icon: '◷', title: 'История изменений', description: 'Категории товаров и адрес покупателя на момент заказа' },
  { id: 'demo', label: 'Демонстрация', icon: '▷', title: 'Демонстрация новых данных', description: 'Пять дней изменений: каждый следующий день загружается по кнопке' },
];
const shortSectionLabels: Record<Section, string> = { overview: 'Обзор', sales: 'Продажи', delivery: 'Дост.', quality: 'Кач.', questions: '6–10', history: 'История', demo: 'Демо' };
const emptyFilters: Filters = { date_from: null, date_to: null, state: null };
const integer = new Intl.NumberFormat('ru-RU');
const amount = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const shortAmount = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 });
const statuses: Record<string, string> = { delivered: 'Доставлен', shipped: 'В доставке', approved: 'Подтверждён', canceled: 'Отменён', processing: 'Обрабатывается', created: 'Создан', invoiced: 'Выставлен счёт', unavailable: 'Недоступен' };
const issues: Record<string, string> = { multiple_reviews: 'Несколько отзывов на заказ', order_without_items: 'Заказ без товаров', carrier_before_approval: 'Передача в доставку раньше подтверждения', delivered_without_delivery_date: 'Доставлен без даты вручения', delivery_before_carrier: 'Вручение раньше передачи в доставку', delivery_date_without_delivered_status: 'Дата вручения при другом статусе', missing_category: 'Категория товара не заполнена', missing_category_translation: 'Нет перевода категории', order_without_payment: 'Нет платёжной записи', payment_amount_mismatch: 'Оплата расходится с суммой заказа', undefined_payment_type: 'Не определён способ оплаты', zero_installments: 'Нулевой срок рассрочки' };
const columnNames: Record<string, string> = { product_id: 'Товар', date: 'Дата', price: 'Цена, BRL', units_sold: 'Продано единиц', state: 'Штат', orders: 'Заказы', avg_delivery_days: 'Средний срок, дн.', late_pct: 'Доля опозданий, %', status: 'Статус', orders_pct: 'Доля заказов, %', orders_without_items: 'Без позиций', payments: 'Платежи', amount: 'Сумма, BRL', avg_installments: 'Средняя рассрочка', payment_type: 'Способ оплаты', score: 'Оценка' };
const questionCell = (value: string | number | null, column: string): React.ReactNode => {
  if (value === null) return '—';
  if (column === 'status') return <Status value={String(value)}/>;
  if (column === 'date') return dateLabel(String(value));
  if (typeof value === 'number') return integer.format(value);
  if (/^-?\d+\.\d+$/.test(value)) return money(value);
  return value;
};
const money = (value: string | null) => value === null ? '—' : amount.format(Number(value));
const decimal = (value: string | number | null, digits = 1) => value === null ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(Number(value));
const dateLabel = (value: string | null) => value ? new Date(value.slice(0, 10) + 'T12:00:00').toLocaleDateString('ru-RU') : 'вся история';
const monthLabel = (value: string) => new Date(value.slice(0, 10) + 'T12:00:00').toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' });
const versionName = (value: string) => value === 'original' ? 'Исходная версия' : value.slice(0, 8);
const queryString = (filters: Filters) => { const query = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); }); return query; };

function Icon({ name }: { name: 'download' | 'refresh' | 'chevron' }) {
  return <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">{name === 'download' ? <><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 16v4h16v-4"/></> : name === 'refresh' ? <><path d="M20 11a8 8 0 1 0-2 6"/><path d="M20 4v7h-7"/></> : <path d="m9 5 7 7-7 7"/>}</svg>;
}

function Chart({ data, onExport, exporting }: { data: Dashboard['monthly']; onExport: () => void; exporting: boolean }) {
  const [metric, setMetric] = useState<'revenue' | 'orders'>('revenue');
  const [hover, setHover] = useState<number | null>(null);
  const w = 1000, h = 238, left = 64, bottom = 35, top = 15, right = 12;
  const plotW = w - left - right, plotH = h - top - bottom;
  const values = data.map(row => metric === 'revenue' ? Number(row.revenue_brl) : row.delivered_orders);
  const max = Math.max(1, ...values) * 1.12;
  const x = (index: number) => left + plotW * (data.length === 1 ? .5 : index / (data.length - 1));
  const y = (value: number) => top + plotH * (1 - value / max);
  const points = values.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const selected = hover === null ? null : data[hover];
  return <section className="panel chart-panel"><div className="panel-heading"><div><h2>Динамика по месяцам</h2><p>Доставленные заказы по дате оформления</p></div><div className="segmented" aria-label="Показатель графика"><button className={metric === 'revenue' ? 'selected' : ''} onClick={() => setMetric('revenue')}>Оборот, BRL</button><button className={metric === 'orders' ? 'selected' : ''} onClick={() => setMetric('orders')}>Заказы</button></div></div>
    {data.length ? <div className="chart-wrap"><svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={metric === 'revenue' ? 'Товарный оборот по месяцам в бразильских реалах' : 'Число доставленных заказов по месяцам'} onMouseLeave={() => setHover(null)}>
      {[0, .25, .5, .75, 1].map(t => <g key={t}><line x1={left} y1={top + plotH * t} x2={w - right} y2={top + plotH * t} stroke="#e7eaf2" strokeDasharray={t === 1 ? undefined : '3 5'}/><text x={left - 12} y={top + plotH * t + 4} textAnchor="end" className="chart-label">{shortAmount.format(max * (1 - t))}</text></g>)}
      <polygon points={`${left},${y(0)} ${points} ${x(data.length - 1)},${y(0)}`} fill="#eeedff"/>
      <polyline points={points} fill="none" stroke="#5558d9" strokeWidth="2.8" strokeLinejoin="round"/>
      {data.map((row, i) => <g key={row.month}><rect x={x(i) - plotW / Math.max(data.length - 1, 1) / 2} y={top} width={plotW / Math.max(data.length - 1, 1)} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)}><title>{monthLabel(row.month)}: {metric === 'revenue' ? money(row.revenue_brl) + ' BRL' : integer.format(row.delivered_orders) + ' заказов'}</title></rect>{(i % Math.max(1, Math.ceil(data.length / 9)) === 0 || i === data.length - 1) && <text x={x(i)} y={h - 9} textAnchor="middle" className="chart-label">{monthLabel(row.month)}</text>}</g>)}
      {hover !== null && <><line x1={x(hover)} x2={x(hover)} y1={top} y2={y(0)} stroke="#9698dd" strokeDasharray="4 4"/><circle cx={x(hover)} cy={y(values[hover])} r="5" fill="#5558d9" stroke="white" strokeWidth="3"/></>}
    </svg><div className="chart-caption">{selected ? <><strong>{monthLabel(selected.month)}</strong><span>{money(selected.revenue_brl)} BRL</span><span>{integer.format(selected.delivered_orders)} заказов</span></> : <><span className="legend-dot"/>Товарный оборот без стоимости доставки<span className="chart-hint">Наведите на месяц, чтобы увидеть значения</span></>}<button className="text-button" onClick={onExport} disabled={exporting}><Icon name="download"/>CSV</button></div></div> : <Empty text="В выбранном периоде нет месяцев для отображения."/>}
  </section>;
}

function Empty({ text }: { text: string }) { return <div className="empty"><span aria-hidden="true">∅</span><p>{text}</p></div>; }
function Status({ value }: { value: string }) { return <span className={`status status-${value}`}>{statuses[value] || value}</span>; }
function Panel({ title, subtitle, children, action }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode }) { return <section className="panel"><div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>; }


function PagedTable<T>({ rows, head, renderRow, empty, pageSize = 10, className = '' }: { rows: T[]; head: React.ReactNode; renderRow: (row: T, index: number) => React.ReactNode; empty: string; pageSize?: number; className?: string }) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, pages - 1);
  const start = currentPage * pageSize;
  return <><div className={`table-scroll ${className}`}><table><thead>{head}</thead><tbody>{rows.slice(start, start + pageSize).map((row, index) => renderRow(row, start + index))}</tbody></table>{!rows.length && <Empty text={empty}/>}</div>{rows.length > pageSize && <div className="table-pagination" aria-label="Страницы таблицы"><span>{integer.format(start + 1)}–{integer.format(Math.min(start + pageSize, rows.length))} из {integer.format(rows.length)}</span><div><button className="pagination-button" aria-label="Предыдущая страница" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>‹</button><span>Страница {currentPage + 1} / {pages}</span><button className="pagination-button" aria-label="Следующая страница" disabled={currentPage === pages - 1} onClick={() => setPage(currentPage + 1)}>›</button></div></div>}</>;
}

function OrdersPanel({ data, preview = false, onOpen, action, onAll }: { data: Dashboard; preview?: boolean; onOpen: (order: Order) => void; action?: React.ReactNode; onAll?: () => void }) {
  const rows = preview ? data.orders.slice(0, 5) : data.orders;
  return <Panel title="Последние заказы" subtitle={preview ? `${integer.format(rows.length)} последних из ${integer.format(data.orders_total)} · все статусы` : `${integer.format(data.orders.length)} последних из ${integer.format(data.orders_total)} · все статусы`} action={action}>
    <PagedTable rows={rows} className="orders-table" head={<tr><th>Заказ</th><th>Оформлен</th><th>Статус</th><th>Штат</th><th className="numeric">Сумма, BRL</th>{!preview && <><th className="numeric">Единицы</th><th className="numeric">Доставка, дн.</th></>}<th><span className="sr-only">Детали</span></th></tr>} renderRow={order => <tr key={order.order_id}><td><button className="order-id" title={order.order_id} onClick={() => onOpen(order)}>{order.order_id.slice(0, 8)}…</button></td><td>{dateLabel(order.purchased_at)}</td><td><Status value={order.status_code}/></td><td>{order.state || '—'}</td><td className="numeric">{money(order.order_amount)}</td>{!preview && <><td className="numeric">{order.units}</td><td className={`numeric ${order.is_late ? 'late-value' : ''}`}>{order.delivery_days === null ? '—' : order.delivery_days}{order.is_late && <span className="late-dot" title="Доставлен позже обещанного"/>}</td></>}<td><button className="row-open" aria-label={`Открыть заказ ${order.order_id}`} onClick={() => onOpen(order)}><Icon name="chevron"/></button></td></tr>} empty="В этом срезе нет заказов."/>
    {preview && <button className="panel-footer-link" onClick={onAll}>Все заказы и детали продаж <Icon name="chevron"/></button>}
  </Panel>;
}

function OverviewPanels({ data, onOpen, onSales, onDelivery, exportButton, downloadMonthly, exporting }: { data: Dashboard; onOpen: (order: Order) => void; onSales: (orders?: boolean) => void; onDelivery: () => void; exportButton: (report: Report, label?: string) => React.ReactNode; downloadMonthly: () => void; exporting: boolean }) {
  return <div className="overview-grid"><Chart data={data.monthly} onExport={downloadMonthly} exporting={exporting}/><Panel title="Категории по обороту" subtitle="Пять крупнейших · стоимость товаров, BRL" action={<button className="text-button" onClick={() => onSales()}>Все <Icon name="chevron"/></button>}><div className="category-bars">{data.categories.length ? data.categories.slice(0, 5).map(row => <div key={row.category_key} className="category-bar-row"><div><span title={row.name}>{row.name === 'unknown' ? 'Без категории' : row.name}</span><strong>{money(row.revenue_brl)}</strong></div><div className="bar-track"><span style={{ width: `${Math.max(.3, Number(row.revenue_pct || 0))}%` }}/></div></div>) : <Empty text="В этом срезе нет продаж по категориям."/>}</div></Panel><OrdersPanel data={data} preview onOpen={onOpen} action={exportButton('orders')} onAll={() => onSales(true)}/><Panel title="Статусы заказов" action={exportButton('statuses')}><div className="status-list">{data.statuses.length ? data.statuses.map(row => <div key={row.status_code} className="visual-status-row" title={`${integer.format(row.orders)} заказов · ${decimal(row.orders_pct,2)}%`}><span className="status-share-track" style={{ width: `${Number(row.orders_pct || 0)}%` }}/><Status value={row.status_code}/><div className="status-count"><strong>{integer.format(row.orders)}</strong><span>{decimal(row.orders_pct)}%</span></div></div>) : <Empty text="В этом срезе нет заказов."/>}</div><button className="panel-footer-link" onClick={onDelivery}>Доставка по штатам <Icon name="chevron"/></button></Panel></div>;
}


type BarDatum = { label: string; value: string | number | null; hint?: string };
function HorizontalBars({ rows, unit = '', label, limit = 10 }: { rows: BarDatum[]; unit?: string; label: string; limit?: number }) {
  const shown = rows.slice(0, limit);
  const max = Math.max(1, ...shown.map(row => Number(row.value || 0)));
  return <div className="horizontal-chart" role="img" aria-label={label}><div className="bar-axis-label">{label}{unit ? `, ${unit}` : ''}</div>{shown.length ? shown.map((row, index) => <div className="horizontal-bar" key={`${row.label}-${index}`} title={`${row.label}: ${decimal(row.value, 2)} ${unit}${row.hint ? ` · ${row.hint}` : ''}`}><span className="horizontal-bar-label">{row.label}</span><div className="horizontal-bar-track"><span style={{ width: `${row.value === null ? 0 : Number(row.value) / max * 100}%` }}/></div><strong>{decimal(row.value, 2)}{unit === '%' && row.value !== null ? '%' : ''}</strong></div>) : <Empty text="Нет данных для графика."/>}{rows.length > limit && <p className="chart-footnote">Показаны {limit} строк. Полные данные — в таблице и CSV.</p>}</div>;
}

function ChartOrTable({ chart, children }: { chart: React.ReactNode; children: React.ReactNode }) {
  const [view, setView] = useState<'chart' | 'table'>('chart');
  return <><div className="data-view-switch segmented" aria-label="Представление данных"><button className={view === 'chart' ? 'selected' : ''} aria-pressed={view === 'chart'} onClick={() => setView('chart')}>График</button><button className={view === 'table' ? 'selected' : ''} aria-pressed={view === 'table'} onClick={() => setView('table')}>Таблица</button></div>{view === 'chart' ? chart : children}</>;
}

function PriceScatter({ question }: { question: Questions['questions'][number] }) {
  const dateIndex = question.columns.indexOf('date'), priceIndex = question.columns.indexOf('price'), unitsIndex = question.columns.indexOf('units_sold');
  const points = question.rows.filter(row => row[dateIndex] !== null && row[priceIndex] !== null).map(row => ({ date: String(row[dateIndex]), time: Date.parse(String(row[dateIndex]).slice(0, 10) + 'T12:00:00'), price: Number(row[priceIndex]), units: row[unitsIndex] }));
  if (!points.length) return <Empty text="Нет наблюдений цены на текущей версии данных."/>;
  const minTime = Math.min(...points.map(point => point.time)), maxTime = Math.max(...points.map(point => point.time));
  const maxPrice = Math.max(1, ...points.map(point => point.price)) * 1.08;
  const left = 75, right = 975, top = 14, bottom = 245;
  const x = (time: number) => left + (right - left) * (maxTime === minTime ? .5 : (time - minTime) / (maxTime - minTime));
  const y = (price: number) => bottom - (bottom - top) * price / maxPrice;
  return <div className="scatter-chart"><div className="bar-axis-label">Цена, BRL · каждая точка — день и отдельная цена</div><svg viewBox="0 0 1000 285" role="img" aria-label="История цены товара по датам без усреднения разных цен за день">{[0,.25,.5,.75,1].map(t => <g key={t}><line x1={left} x2={right} y1={y(maxPrice*t)} y2={y(maxPrice*t)} stroke="#e5e9f1"/><text x={left-12} y={y(maxPrice*t)+5} textAnchor="end">{decimal(maxPrice*t,0)}</text></g>)}{[0,.25,.5,.75,1].map(t => { const time=minTime+(maxTime-minTime)*t; return <text key={t} x={x(time)} y={274} textAnchor="middle">{dateLabel(new Date(time).toISOString())}</text>; })}{points.map((point,index) => <circle key={index} cx={x(point.time)} cy={y(point.price)} r="4" fill="#6365d7" fillOpacity=".68" stroke="white" strokeWidth="1"><title>{dateLabel(point.date)}: {money(String(point.price))} BRL · {point.units} ед.</title></circle>)}</svg><p className="chart-footnote">{integer.format(question.row_count)} наблюдений. Несколько цен за день показаны отдельными точками; число проданных единиц — при наведении.</p></div>;
}

function QuestionChart({ question }: { question: Questions['questions'][number] }) {
  if (question.columns.includes('date') && question.columns.includes('price')) return <PriceScatter question={question}/>;
  const labelColumn = ['state','status','payment_type','score'].find(column => question.columns.includes(column));
  const valueColumn = question.columns.includes('avg_delivery_days') ? 'avg_delivery_days' : question.columns.includes('amount') ? 'amount' : question.columns.includes('payment_type') ? 'avg_installments' : 'orders';
  if (!labelColumn || !question.columns.includes(valueColumn)) return <Empty text="Для этого результата доступна таблица."/>;
  const labelIndex = question.columns.indexOf(labelColumn), valueIndex = question.columns.indexOf(valueColumn);
  const label = valueColumn === 'avg_delivery_days' ? 'Средний срок доставки' : valueColumn === 'amount' ? 'Сумма платежей' : valueColumn === 'avg_installments' ? 'Средняя рассрочка' : 'Число заказов';
  const unit = valueColumn === 'avg_delivery_days' ? 'дн.' : valueColumn === 'amount' ? 'BRL' : valueColumn === 'avg_installments' ? 'платежей' : '';
  return <HorizontalBars rows={question.rows.map(row => ({ label: labelColumn === 'status' ? statuses[String(row[labelIndex])] || String(row[labelIndex]) : labelColumn === 'score' ? `Оценка ${row[labelIndex]}` : String(row[labelIndex] ?? 'Неизвестен'), value: row[valueIndex] }))} label={label} unit={unit} limit={12}/>;
}

function DeliveryChart({ rows }: { rows: Dashboard['delivery'] }) {
  const [metric, setMetric] = useState<'average_days' | 'late_pct'>('average_days');
  return <><div className="chart-metric-switch segmented" aria-label="Показатель доставки"><button className={metric === 'average_days' ? 'selected' : ''} aria-pressed={metric === 'average_days'} onClick={() => setMetric('average_days')}>Средний срок</button><button className={metric === 'late_pct' ? 'selected' : ''} aria-pressed={metric === 'late_pct'} onClick={() => setMetric('late_pct')}>Опоздания</button></div><HorizontalBars rows={rows.map(row => ({ label: row.state || 'Неизвестен', value: row[metric], hint: `${integer.format(row.orders)} заказов` }))} label={metric === 'average_days' ? 'Средний срок доставки' : 'Доля опозданий'} unit={metric === 'average_days' ? 'дн.' : '%'} limit={10}/></>;
}

function QuestionPanel({ question, exporting, onExport }: { question: Questions['questions'][number]; exporting: boolean; onExport: () => void }) {
  return <Panel title={question.title} subtitle={`${integer.format(question.row_count)} строк · полный результат запроса`} action={<button className="text-button" disabled={exporting} onClick={onExport}><Icon name="download"/>Скачать CSV</button>}><ChartOrTable chart={<QuestionChart question={question}/>}><PagedTable rows={question.rows} pageSize={10} head={<tr>{question.columns.map(column => <th key={column} className={['product_id','date','state','status','payment_type'].includes(column) ? undefined : 'numeric'}>{columnNames[column] || column}</th>)}</tr>} renderRow={(row,index) => <tr key={index}>{row.map((value,column) => <td key={column} className={['product_id','date','state','status','payment_type'].includes(question.columns[column]) ? undefined : 'numeric'}>{questionCell(value,question.columns[column])}</td>)}</tr>} empty="Запрос не вернул строк на текущей версии данных."/></ChartOrTable><details className="question-sql"><summary>SQL расчёта <span>{question.sql_file}</span></summary><pre><code>{question.sql}</code></pre></details></Panel>;
}

function HistoryPanels({ history }: { history: History }) {
  const [view, setView] = useState<'categories' | 'addresses'>('categories');
  return <div className="history-grid"><Panel title="История категории товара" subtitle="Периоды наблюдения изменений"><code className="selected-product" title={history.selected_product || ''}>{history.selected_product || 'Выберите товар'}</code><PagedTable rows={history.category_history} head={<tr><th>Версия / категория</th><th>Период наблюдения</th></tr>} renderRow={row => <tr key={`${row.product_id}-${row.version_no}`}><td><strong>v{row.version_no}</strong><span className="cell-secondary">{row.category_name || row.category_key}</span></td><td>{row.observed_from ? dateLabel(row.observed_from) : 'Начальный снимок'}<span className="cell-secondary">{row.observed_to ? `до ${dateLabel(row.observed_to)}` : 'Текущая версия'}</span></td></tr>} empty="Выберите товар, чтобы посмотреть версии категории."/><div className="history-note">Время наблюдения — момент получения снимка системой. Дата изменения до первого наблюдения неизвестна. Прошлые позиции сохраняют свою категорию.</div></Panel><div className="history-records"><div className="view-tabs" aria-label="Исторические записи"><button className={view === 'categories' ? 'selected' : ''} aria-pressed={view === 'categories'} onClick={() => setView('categories')}>Категории в заказах</button><button className={view === 'addresses' ? 'selected' : ''} aria-pressed={view === 'addresses'} onClick={() => setView('addresses')}>Адреса заказов</button></div>{view === 'categories' ? <Panel title="Категория в позициях заказов" subtitle="Категория позиции и текущая категория товара"><PagedTable key={history.selected_product} rows={history.product_orders} head={<tr><th>Заказ / дата</th><th>Категория позиции</th><th>Текущая категория</th><th>Версия</th><th className="numeric">Цена, BRL</th></tr>} renderRow={(row,index) => <tr key={`${row.order_id}-${index}`}><td><code title={row.order_id}>{row.order_id.slice(0,10)}…</code><span className="cell-secondary">{dateLabel(row.purchased_at)}</span></td><td>{row.category_at_order}</td><td>{row.current_category}</td><td>{row.version_no}</td><td className="numeric">{money(row.price)}</td></tr>} empty="Для выбранного товара нет позиций заказов."/></Panel> : <Panel title="Адрес покупателя на момент заказа" subtitle="Снимок заказа сохраняется при переезде · до 20 последних заказов"><PagedTable rows={history.orders} head={<tr><th>Заказ / дата</th><th>Адрес в заказе</th><th>Текущий профиль</th></tr>} renderRow={row => <tr key={row.order_id}><td><code title={row.order_id}>{row.order_id.slice(0,10)}…</code><span className="cell-secondary">{dateLabel(row.purchased_at)}</span></td><td>{row.snapshot_city || 'Неизвестен'}<span className="state-pill">{row.snapshot_state || '—'}</span></td><td>{row.current_city || 'Неизвестен'}<span className="state-pill">{row.current_state || '—'}</span></td></tr>} empty="Заказ не найден. Проверьте полный идентификатор."/></Panel>}</div></div>;
}

function OrderDialog({ order, close }: { order: Order; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="order-dialog" onClose={close} onClick={event => { if (event.target === event.currentTarget) ref.current?.close(); }}><div className="dialog-heading"><h2>Детали заказа</h2><button className="close-button" aria-label="Закрыть детали заказа" onClick={() => ref.current?.close()}>×</button></div><code className="full-order-id">{order.order_id}</code><Status value={order.status_code}/><dl className="order-details"><dt>Дата оформления</dt><dd>{dateLabel(order.purchased_at)}</dd><dt>Штат покупателя</dt><dd>{order.state || 'Неизвестен'}</dd><dt>Товары</dt><dd>{money(order.goods_amount)} BRL</dd><dt>Доставка</dt><dd>{money(order.freight_amount)} BRL</dd><dt>Сумма заказа</dt><dd><strong>{money(order.order_amount)} BRL</strong></dd><dt>Строк / единиц</dt><dd>{order.lines} / {order.units}</dd><dt>Срок доставки</dt><dd>{order.delivery_days === null ? 'Дата неизвестна' : `${order.delivery_days} дн.`}</dd><dt>Опоздание</dt><dd>{order.is_late === null ? 'Недостаточно дат' : order.is_late ? 'Да' : 'Нет'}</dd><dt>Последняя оценка</dt><dd>{order.latest_review_score === null ? 'Нет отзыва' : `${order.latest_review_score} из 5`}</dd></dl></dialog>;
}


function DemoPanel({ status, advancing, onAdvance, onOpen, onOriginal }: { status: DemoStatus | null; advancing: boolean; onAdvance: () => void; onOpen: () => void; onOriginal: () => void }) {
  const running = status?.state === 'running';
  const complete = status?.state === 'complete';
  const ready = Boolean(status && status.day > 0 && status.version_id);
  const summary = status?.summary;
  return <><div className="notice">Синтетические данные демонстрируют новые заказы, доставку и изменения истории. Для каждого дня нажмите кнопку; исходная выгрузка Olist доступна отдельно.</div><Panel title="Поступление данных по дням" subtitle="Каждый шаг публикует следующий снимок демонстрационного набора"><div className="demo-body"><ol className="demo-days" aria-label="Дни демонстрации">{Array.from({ length: status?.total_days || 5 }, (_, index) => <li key={index} className={index < (status?.day || 0) ? 'done' : running && index === (status?.day || 0) ? 'active' : ''} aria-current={running && index === (status?.day || 0) ? 'step' : undefined}><span>{index < (status?.day || 0) ? '✓' : index + 1}</span><strong>День {index + 1}</strong><small>{index < (status?.day || 0) ? 'Загружен' : running && index === (status?.day || 0) ? 'Загрузка' : 'Ожидает'}</small></li>)}</ol><div className="demo-status" role="status" aria-live="polite">{running && <span className="spinner"/>}<div><strong>{complete ? 'Все пять дней загружены' : running ? 'Загружаем следующий день' : status?.state === 'error' ? 'Не удалось загрузить день' : ready ? `Доступен день ${status?.day} из ${status?.total_days}` : 'Готово к первому шагу'}</strong><p>{status?.message || 'Получаем состояние демонстрации.'}</p></div></div><div className="demo-actions"><button className="button primary" onClick={onAdvance} disabled={!status || advancing || running || complete}>{running || advancing ? 'Загружаем день…' : complete ? 'Демонстрация завершена' : 'Загрузить следующий день'}</button><button className="button secondary" onClick={onOpen} disabled={!ready}>Открыть демоданные</button><button className="text-button" onClick={onOriginal}>Исходный набор</button></div>{status?.version_id && <div className="demo-version" title={status.version_id}>Версия: {versionName(status.version_id)}</div>}</div></Panel>{summary && <><div className="metrics demo-metrics"><div className="metric"><span>Новые заказы за день</span><strong>{integer.format(summary.new_orders || 0)}</strong><p>Добавлены в новый снимок</p></div><div className="metric"><span>Смены статуса за день</span><strong>{integer.format(summary.changed_statuses || 0)}</strong><p>Существующие заказы</p></div><div className="metric"><span>Заказы в демонаборе</span><strong>{integer.format(summary.orders || 0)}</strong><p>Все статусы</p></div><div className="metric"><span>Доставленные заказы</span><strong>{integer.format(summary.delivered_orders || 0)}</strong><p>Текущий опубликованный день</p></div></div><p className="demo-summary-note">Товарный оборот доставленных заказов: <strong>{money(summary.delivered_goods_amount ?? null)} BRL</strong>{summary.latest_purchase && <> · Последний заказ: {dateLabel(summary.latest_purchase)}</>}</p></>}</>;
}

function App() {
  const [section, setSection] = useState<Section>('overview');
  const [source, setSource] = useState<'original' | 'demo'>('original');
  const [demoStatus, setDemoStatus] = useState<DemoStatus | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [demoAdvancing, setDemoAdvancing] = useState(false);
  const [draft, setDraft] = useState<Filters>(emptyFilters);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [categorySearch, setCategorySearch] = useState('');
  const [selectedQuestionId, setSelectedQuestionId] = useState('');
  const [salesView, setSalesView] = useState<'categories' | 'sellers' | 'orders'>('categories');
  const [questions, setQuestions] = useState<Questions | null>(null);
  const [questionsLoading, setQuestionsLoading] = useState(false);
  const [questionsError, setQuestionsError] = useState<string | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyDraft, setHistoryDraft] = useState({ product_id: '', order_id: '' });
  const [historyFilters, setHistoryFilters] = useState({ product_id: '', order_id: '' });
  const selectedQuestion = questions?.questions.find(question => question.id === selectedQuestionId) || questions?.questions[0];
  const current = sections.find(item => item.id === section)!;
  const dashboardActive = section !== 'questions' && section !== 'history' && section !== 'demo';
  const demoAvailable = Boolean(demoStatus && demoStatus.day > 0 && demoStatus.version_id);
  function switchSource(next: 'original' | 'demo') {
    if (next === source) return;
    setSource(next); setDraft(emptyFilters); setFilters(emptyFilters);
    setHistoryDraft({ product_id: '', order_id: '' }); setHistoryFilters({ product_id: '', order_id: '' });
    setCategorySearch(''); setSelectedOrder(null); setSelectedQuestionId('');
    setData(null); setQuestions(null); setHistory(null); setExportError(null);
  }
  async function readDemoStatus(signal?: AbortSignal): Promise<DemoStatus> {
    const response = await fetch('/api/demo/status', { signal });
    if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === 'string' ? body.detail : 'Не удалось получить состояние демонстрации.'); }
    return response.json() as Promise<DemoStatus>;
  }
  useEffect(() => {
    const controller = new AbortController();
    setDemoLoading(true); setDemoError(null);
    readDemoStatus(controller.signal).then(setDemoStatus).catch(e => { if (e.name !== 'AbortError') setDemoError(e.message); }).finally(() => { if (!controller.signal.aborted) setDemoLoading(false); });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    if (demoStatus?.state !== 'running') return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const status = await readDemoStatus(controller.signal); if (controller.signal.aborted) return; setDemoStatus(status); setDemoError(null); if (status.state === 'running') timer = setTimeout(poll, 1500); }
      catch (e) { if (!controller.signal.aborted) { setDemoError(e instanceof Error ? e.message : 'Не удалось обновить статус.'); timer = setTimeout(poll, 2000); } }
    }
    timer = setTimeout(poll, 1500);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [demoStatus?.state]);
  useEffect(() => { if (source === 'demo' && demoStatus?.version_id) setRevision(value => value + 1); }, [demoStatus?.version_id]);
  async function advanceDemo() {
    if (demoAdvancing || demoStatus?.state === 'running' || demoStatus?.state === 'complete') return;
    setDemoAdvancing(true); setDemoError(null);
    try {
      const response = await fetch('/api/demo/advance', { method: 'POST' });
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === 'string' ? body.detail : 'Не удалось загрузить следующий день.'); }
      setDemoStatus(await response.json() as DemoStatus);
    } catch (e) { setDemoError(e instanceof Error ? e.message : 'Не удалось загрузить следующий день.'); } finally { setDemoAdvancing(false); }
  }
  useEffect(() => {
    if (!dashboardActive) return;
    const controller = new AbortController();
    setLoading(true); setError(null); setExportError(null); setData(null);
    fetch(`/api/dashboard?${queryString(filters)}&dataset=${source}`, { signal: controller.signal }).then(async response => {
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === 'string' ? body.detail : `Сервер вернул ошибку ${response.status}.`); }
      return response.json() as Promise<Dashboard>;
    }).then(setData).catch(e => { if (e.name !== 'AbortError') setError(e.message || 'Не удалось загрузить данные.'); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters, revision, source, dashboardActive]);
  useEffect(() => {
    if (section !== 'questions') return;
    const controller = new AbortController();
    setQuestionsLoading(true); setQuestionsError(null); setQuestions(null); setExportError(null);
    fetch(`/api/questions?dataset=${source}`, { signal: controller.signal }).then(async response => {
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === 'string' ? body.detail : 'Не удалось получить ответы.'); }
      return response.json() as Promise<Questions>;
    }).then(setQuestions).catch(e => { if (e.name !== 'AbortError') setQuestionsError(e.message); }).finally(() => { if (!controller.signal.aborted) setQuestionsLoading(false); });
    return () => controller.abort();
  }, [section, revision, source]);
  useEffect(() => {
    if (section !== 'history') return;
    const controller = new AbortController();
    setHistoryLoading(true); setHistoryError(null); setExportError(null);
    const query = new URLSearchParams({ dataset: source });
    if (historyFilters.product_id) query.set('product_id', historyFilters.product_id);
    if (historyFilters.order_id) query.set('order_id', historyFilters.order_id);
    fetch(`/api/history?${query}`, { signal: controller.signal }).then(async response => {
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === 'string' ? body.detail : 'Не удалось загрузить историю изменений.'); }
      return response.json() as Promise<History>;
    }).then(value => { setHistory(value); if (!historyFilters.product_id) setHistoryDraft(draft => ({ ...draft, product_id: value.selected_product || '' })); }).catch(e => { if (e.name !== 'AbortError') setHistoryError(e.message); }).finally(() => { if (!controller.signal.aborted) setHistoryLoading(false); });
    return () => controller.abort();
  }, [section, revision, historyFilters, source]);
  function apply(event: React.FormEvent) {
    event.preventDefault();
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setExportError('Начало периода должно быть не позже окончания.'); return; }
    setFilters({ ...draft }); setRevision(value => value + 1);
  }
  async function download(report: Report) {
    if (!data) return;
    setExporting(true); setExportError(null);
    const query = queryString(data.filters); query.set('dataset', source); query.set('report', report); query.set('expected_version', data.context.dataset_version);
    try {
      const response = await fetch(`/api/export?${query}`);
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === 'string' ? body.detail : 'Выгрузка не выполнена. Попробуйте обновить данные.'); }
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement('a'); a.href = url;
      const disposition = response.headers.get('Content-Disposition') || '';
      const matched = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
      a.download = matched ? decodeURIComponent(matched[1] || matched[2]) : `marketplace-${report}.csv`;
      a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setExportError(e instanceof Error ? e.message : 'Выгрузка не выполнена.'); } finally { setExporting(false); }
  }
  async function downloadQuestion(id: string) {
    if (!questions) return;
    setExporting(true); setExportError(null);
    try {
      const query = new URLSearchParams({ expected_version: questions.context.dataset_version, dataset: source });
      const response = await fetch(`/api/questions/${encodeURIComponent(id)}/export?${query}`);
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === 'string' ? body.detail : 'Не удалось выгрузить ответ.'); }
      const url = URL.createObjectURL(await response.blob()); const a = document.createElement('a');
      a.href = url; a.download = `marketplace-answer-${id}-${versionName(questions.context.dataset_version)}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setExportError(e instanceof Error ? e.message : 'Выгрузка не выполнена.'); } finally { setExporting(false); }
  }
  const exportButton = (report: Report, label = 'CSV') => <button className="text-button" disabled={!data || exporting} onClick={() => download(report)}><Icon name="download"/>{label}</button>;
  const categoryRows = data?.categories.filter(row => `${row.name} ${row.category_key}`.toLowerCase().includes(categorySearch.toLowerCase())) || [];
  const pageLoading = section === 'demo' ? demoLoading : section === 'questions' ? questionsLoading : section === 'history' ? historyLoading : loading;
  const connected = section === 'demo' ? Boolean(demoStatus) : section === 'questions' ? Boolean(questions) : section === 'history' ? Boolean(history) : Boolean(data);
  const pageError = section === 'demo' ? demoError : section === 'questions' ? questionsError : section === 'history' ? historyError : error;
  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="#" onClick={e => { e.preventDefault(); setSection('overview'); }} aria-label="Аналитика маркетплейса — обзор"><span>Аналитика<span className="brand-caption">маркетплейса</span></span></a><nav aria-label="Разделы аналитики">{sections.map(item => <button key={item.id} className={section === item.id ? 'nav-item active' : 'nav-item'} aria-current={section === item.id ? 'page' : undefined} aria-label={item.label} title={item.label} onClick={() => setSection(item.id)}><span className="nav-icon" aria-hidden="true">{item.icon}</span><span className="nav-label">{item.label}</span><span className="nav-label-short">{shortSectionLabels[item.id]}</span>{section === item.id && <span className="nav-active-dot"/>}</button>)}</nav><div className="sidebar-bottom"><span>Рабочее место аналитика</span></div></aside>
    <main><header className="topbar"><span>Аналитика маркетплейса</span><div className="source-switch segmented" aria-label="Набор данных"><button className={source === 'original' ? 'selected' : ''} aria-pressed={source === 'original'} onClick={() => switchSource('original')}>Исходные</button><button className={source === 'demo' ? 'selected' : ''} aria-pressed={source === 'demo'} disabled={!demoAvailable} title={demoAvailable ? 'Открыть демонстрационный набор' : 'Загрузите первый день во вкладке Демонстрация'} onClick={() => switchSource('demo')}>Демонстрационные</button></div><span className="topbar-right"><span className="live-dot"/>{connected ? 'Данные доступны' : pageLoading ? 'Подключение к данным' : 'Нет соединения'}</span></header><div className={`workspace section-${section}`}><div className="page-heading"><div><h1>{current.title}</h1><p>{current.description}</p></div><button className="button secondary" onClick={() => setRevision(v => v + 1)} disabled={pageLoading}><Icon name="refresh"/>{pageLoading ? 'Загрузка' : 'Обновить'}</button></div>
    {dashboardActive && <form className="filterbar" onSubmit={apply}><div className="filter-group"><span className="filter-label">Дата оформления</span><div className="date-inputs"><input type="date" aria-label="Дата оформления с" value={draft.date_from || ''} onChange={e => setDraft({ ...draft, date_from: e.target.value || null })}/><span>—</span><input type="date" aria-label="Дата оформления по" value={draft.date_to || ''} onChange={e => setDraft({ ...draft, date_to: e.target.value || null })}/></div></div><label className="filter-group state-filter"><span className="filter-label">Штат покупателя</span><select value={draft.state || ''} onChange={e => setDraft({ ...draft, state: e.target.value || null })}><option value="">Все штаты</option>{data?.options.states.map(state => <option key={state}>{state}</option>)}</select></label><div className="filter-actions"><button className="button primary" type="submit" disabled={loading}>Применить</button><button className="text-button muted" type="button" disabled={loading} onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); setRevision(v => v + 1); }}>Сбросить</button></div></form>}
    {exportError && <div className="notice error-notice" role="alert">{exportError}<button aria-label="Закрыть сообщение" onClick={() => setExportError(null)}>×</button></div>}
    {pageLoading && <div className="loading-state" role="status"><span className="spinner"/><h2>Получаем показатели</h2><p>Читаем данные и версию из одного снимка модели.</p></div>}
    {pageError && <div className="load-error" role="alert"><span className="error-symbol">!</span><h2>Не удалось получить данные</h2><p>{pageError}</p><button className="button primary" onClick={() => setRevision(v => v + 1)}>Попробовать ещё раз</button></div>}
    {data && dashboardActive && <><div className="dataset-line"><span className={`dataset-badge ${data.context.kind === 'synthetic' ? 'synthetic' : ''}`}><span/>{data.context.kind === 'synthetic' ? 'Синтетическая демонстрация' : data.context.kind === 'external' ? 'Внешний снимок' : 'Исходная выгрузка Olist'}</span><span>{dateLabel(data.filters.date_from || data.context.data_from)} — {dateLabel(data.filters.date_to || data.context.data_to)}</span><span title={data.context.dataset_version}>Версия: <strong>{versionName(data.context.dataset_version)}</strong></span></div>
      {section !== 'quality' && <div className="metrics"><div className="metric"><span>Товарный оборот <small>BRL</small></span><strong>{money(data.summary.revenue_brl)}</strong><p>Доставленные заказы, без доставки</p></div><div className="metric"><span>Доставленные заказы</span><strong>{integer.format(data.summary.delivered_orders)}</strong><p>Один заказ считается один раз</p></div><div className="metric"><span>Средний чек <small>BRL</small></span><strong>{money(data.summary.average_check_brl)}</strong><p>Товары и доставка в заказе</p></div><div className="metric"><span>Повторные покупатели</span><strong>{decimal(data.summary.repeat_pct, 2)}<small>{data.summary.repeat_pct !== null ? '%' : ''}</small></strong><p>{integer.format(data.summary.repeat_buyers)} из {integer.format(data.summary.buyers)} покупателей · все статусы</p></div></div>}
      {data.orders_total === 0 && section !== 'quality' && <div className="notice">В выбранном срезе нет заказов. Измените период или сбросьте фильтры.</div>}
      {section === 'overview' && <OverviewPanels data={data} onOpen={setSelectedOrder} onSales={orders => { setSalesView(orders ? 'orders' : 'categories'); setSection('sales'); }} onDelivery={() => setSection('delivery')} exportButton={exportButton} downloadMonthly={() => download('monthly')} exporting={exporting}/>}
      {section === 'sales' && <><div className="view-tabs" aria-label="Разрез продаж">{([{id:'categories',label:'Категории'},{id:'sellers',label:'Продавцы'},{id:'orders',label:'Заказы'}] as const).map(view => <button key={view.id} className={salesView === view.id ? 'selected' : ''} aria-pressed={salesView === view.id} onClick={() => setSalesView(view.id)}>{view.label}</button>)}</div></>}
      {section === 'sales' && salesView === 'categories' && <Panel title="Оборот по категориям" subtitle="Доли рассчитаны от всего оборота выбранного среза" action={exportButton('categories')}><ChartOrTable chart={<HorizontalBars rows={data.categories.map(row => ({ label: row.name === 'unknown' ? 'Без категории' : row.name, value: row.revenue_brl, hint: `${decimal(row.revenue_pct,2)}% оборота` }))} label="Товарный оборот по категориям" unit="BRL" limit={8}/>}><div className="table-tools"><input className="search-input" type="search" aria-label="Найти категорию" placeholder="Найти категорию" value={categorySearch} onChange={e => setCategorySearch(e.target.value)}/><span>{integer.format(categoryRows.length)} категорий</span></div><div className="table-scroll category-table"><table><thead><tr><th>Категория</th><th className="numeric">Оборот, BRL</th><th className="numeric">Доля</th></tr></thead><tbody>{categoryRows.map(row => <tr key={row.category_key}><td>{row.name === 'unknown' ? 'Без категории' : row.name}</td><td className="numeric">{money(row.revenue_brl)}</td><td className="numeric">{decimal(row.revenue_pct, 2)}%</td></tr>)}</tbody></table>{!categoryRows.length && <Empty text="Категории не найдены."/>}</div></ChartOrTable></Panel>}
      {section === 'sales' && salesView === 'sellers' && <Panel title="Продавцы" subtitle="Топ-10 по стоимости доставленных товаров · CSV содержит всех продавцов" action={exportButton('sellers')}><ChartOrTable chart={<HorizontalBars rows={data.sellers.map((row,index) => ({ label: `${index+1}. ${row.seller_id.slice(0,10)}…`, value: row.revenue_brl, hint: `${row.city || 'Город неизвестен'} · ${row.state || '—'} · ${integer.format(row.orders)} заказов` }))} label="Товарный оборот продавцов" unit="BRL" limit={8}/>}><div className="table-scroll"><table><thead><tr><th>Продавец</th><th>Город / штат</th><th className="numeric">Заказы</th><th className="numeric">Единицы</th><th className="numeric">Оборот, BRL</th></tr></thead><tbody>{data.sellers.slice(0, 10).map((row, index) => <tr key={row.seller_id}><td><span className="rank">{index + 1}</span><code title={row.seller_id}>{row.seller_id.slice(0, 12)}…</code></td><td>{row.city || 'Неизвестен'}<span className="state-pill">{row.state || '—'}</span></td><td className="numeric">{integer.format(row.orders)}</td><td className="numeric">{integer.format(row.units)}</td><td className="numeric">{money(row.revenue_brl)}</td></tr>)}</tbody></table>{!data.sellers.length && <Empty text="В этом срезе нет продаж."/>}</div></ChartOrTable></Panel>}
      {section === 'delivery' && <><div className="notice">Сроки считаются по календарным датам. Доля опозданий — только среди доставленных заказов с известными фактической и обещанной датами.</div><div className="two-columns"><Panel title="Доставка по штатам покупателя" subtitle="Все штаты с доставленными заказами; малые выборки отмечены" action={exportButton('delivery')}><ChartOrTable chart={<DeliveryChart rows={data.delivery}/>}><div className="table-scroll"><table><thead><tr><th>Штат</th><th className="numeric">Доставлено</th><th className="numeric">Средний срок, дн.</th><th className="numeric">Опоздания</th><th className="numeric">Доля опозданий</th><th className="numeric">Без дат</th></tr></thead><tbody>{data.delivery.map(row => <tr key={row.state || 'unknown'}><td><strong>{row.state || 'Неизвестен'}</strong>{row.orders < 500 && <span className="small-sample" title="Менее 500 заказов: осторожнее с выводами">Малая выборка</span>}</td><td className="numeric">{integer.format(row.orders)}</td><td className="numeric">{decimal(row.average_days, 2)}</td><td className="numeric">{integer.format(row.late_orders)}</td><td className="numeric"><span className={Number(row.late_pct) > 15 ? 'late-value' : ''}>{decimal(row.late_pct, 2)}{row.late_pct !== null ? '%' : ''}</span></td><td className="numeric">{integer.format(row.missing_dates)}</td></tr>)}</tbody></table>{!data.delivery.length && <Empty text="Нет доставленных заказов в выбранном срезе."/>}</div></ChartOrTable></Panel><Panel title="Распределение статусов" subtitle="Срез по дате оформления, включая отмены и заказы без товаров" action={exportButton('statuses')}><ChartOrTable chart={<HorizontalBars rows={data.statuses.map(row => ({ label: statuses[row.status_code] || row.status_code, value: row.orders, hint: `${decimal(row.orders_pct,2)}%` }))} label="Число заказов по статусам"/>}><div className="table-scroll"><table><thead><tr><th>Статус</th><th className="numeric">Заказы</th><th className="numeric">Доля</th><th className="numeric">Без товаров</th></tr></thead><tbody>{data.statuses.map(row => <tr key={row.status_code}><td><Status value={row.status_code}/></td><td className="numeric">{integer.format(row.orders)}</td><td className="numeric">{decimal(row.orders_pct, 2)}%</td><td className="numeric">{integer.format(row.orders_without_items)}</td></tr>)}</tbody></table></div></ChartOrTable></Panel></div></>}
      {section === 'quality' && <><div className="notice quality-notice"><strong>Проверки относятся ко всему набору.</strong> Период и штат в верхней панели не изменяют эту таблицу. Число проблем может превышать число заказов: одна сущность может нарушать несколько правил.</div><Panel title="Реестр качества" subtitle="Ошибки блокируют публикацию; предупреждения сохраняются для анализа" action={exportButton('quality')}><div className="table-scroll"><table><thead><tr><th>Уровень</th><th>Проверка</th><th>Сущность</th><th className="numeric">Проблемы</th><th className="numeric">Уникальные сущности</th></tr></thead><tbody>{data.quality.map(row => <tr key={`${row.severity}-${row.issue_code}-${row.entity_type}`}><td><span className={`severity severity-${row.severity}`}>{row.severity === 'error' ? 'Ошибка' : row.severity === 'warning' ? 'Внимание' : 'Информация'}</span></td><td><strong className="issue-label">{issues[row.issue_code] || row.issue_code}</strong><code className="issue-code">{row.issue_code}</code></td><td>{row.entity_type}</td><td className="numeric">{integer.format(row.issues)}</td><td className="numeric">{integer.format(row.affected_entities)}</td></tr>)}</tbody></table>{!data.quality.length && <Empty text="Проблем качества в текущем наборе не обнаружено."/>}</div></Panel></>}
      {section === 'sales' && salesView === 'orders' && <OrdersPanel data={data} onOpen={setSelectedOrder} action={exportButton('orders', 'Выгрузить все')}/>}

      <details className="methodology"><summary>Как рассчитаны показатели<span>Формулы, гранулярность и ограничения</span></summary><div className="definitions">{data.definitions.map(row => <div key={row.id}><h3>{row.label}</h3><p>{row.formula}</p><dl><dt>Уровень</dt><dd>{row.grain}</dd><dt>Статусы</dt><dd>{row.status_scope}</dd><dt>Дата</dt><dd>{row.date_field}</dd></dl>{row.notes && <p className="definition-note">{row.notes}</p>}</div>)}</div><p className="methodology-note">Средние, доли и число уникальных покупателей нельзя складывать по срезам. Товарный оборот отражает стоимость товаров, а не доход или прибыль площадки.</p></details>
      <footer className="page-footer"><span>Marketplace Analytics</span><span>Валюта: BRL · Даты источника без изменения часового пояса</span></footer>
    </>}
    {section === 'demo' && <DemoPanel status={demoStatus} advancing={demoAdvancing} onAdvance={advanceDemo} onOpen={() => { switchSource('demo'); setSection('overview'); }} onOriginal={() => { switchSource('original'); setSection('overview'); }}/>}
    {section === 'questions' && questions && <><div className="dataset-line"><span className={`dataset-badge ${questions.context.kind === 'synthetic' ? 'synthetic' : ''}`}><span/>{questions.context.kind === 'synthetic' ? 'Синтетическая демонстрация' : questions.context.kind === 'external' ? 'Внешний снимок' : 'Исходная выгрузка Olist'}</span><span title={questions.context.dataset_version}>Версия: <strong>{versionName(questions.context.dataset_version)}</strong></span></div><div className="notice">Расчёты по условиям задания. Вопрос 9: штаты — 2018 год, способы оплаты — вся история. Фильтры продаж здесь не применяются.</div><div className="view-tabs question-tabs" aria-label="Выбор вопроса">{questions.questions.map((question, index) => <button key={question.id} title={question.title} className={selectedQuestion?.id === question.id ? 'selected' : ''} aria-pressed={selectedQuestion?.id === question.id} onClick={() => setSelectedQuestionId(question.id)}>{['6 · История цены', '7 · Доставка', '8 · Статусы', '9 · Штаты', '9 · Способы оплаты', '10 · Оценки'][index] || question.title}</button>)}</div>{selectedQuestion && <QuestionPanel key={selectedQuestion.id} question={selectedQuestion} exporting={exporting} onExport={() => downloadQuestion(selectedQuestion.id)}/>}</>}

    {section === 'history' && history && !historyLoading && !historyError && <><div className="dataset-line"><span className={`dataset-badge ${history.context.kind === 'synthetic' ? 'synthetic' : ''}`}><span/>{history.context.kind === 'synthetic' ? 'Синтетическая демонстрация' : history.context.kind === 'external' ? 'Внешний снимок' : 'Исходная выгрузка Olist'}</span><span title={history.context.dataset_version}>Версия: <strong>{versionName(history.context.dataset_version)}</strong></span></div><div className="metrics"><div className="metric"><span>Товары со сменой категории</span><strong>{integer.format(history.summary.products_with_changes)}</strong><p>Зафиксированные изменения</p></div><div className="metric"><span>Версии категорий</span><strong>{integer.format(history.summary.category_versions)}</strong><p>Сохранённые наблюдения</p></div><div className="metric"><span>Адреса заказов</span><strong>{integer.format(history.summary.frozen_order_addresses)}</strong><p>Снимок адреса для каждого заказа</p></div><div className="metric"><span>Адрес отличается от профиля</span><strong>{integer.format(history.summary.addresses_different_from_profile)}</strong><p>Исторический адрес сохранён</p></div></div>{history.summary.products_with_changes === 0 && <div className="notice">В исходном снимке нет событий смены категории. Версии фиксируются при обновлениях; начальная версия и адреса заказов уже сохранены.</div>}<form className="filterbar history-filters" onSubmit={event => { event.preventDefault(); setHistoryFilters({ ...historyDraft }); }}><label className="filter-group"><span className="filter-label">Товар</span><select value={historyDraft.product_id} onChange={event => setHistoryDraft({ ...historyDraft, product_id: event.target.value })}><option value="">Выбрать товар</option>{history.products.map(product => <option key={product.product_id} value={product.product_id}>{product.product_id} · {product.versions} верс.</option>)}</select></label><label className="filter-group"><span className="filter-label">Адрес конкретного заказа</span><input type="search" placeholder="Полный ID заказа" value={historyDraft.order_id} onChange={event => setHistoryDraft({ ...historyDraft, order_id: event.target.value })}/></label><button className="button primary" type="submit">Показать</button></form><HistoryPanels history={history}/></>}
    </div></main>{selectedOrder && <OrderDialog order={selectedOrder} close={() => setSelectedOrder(null)}/>}</div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
