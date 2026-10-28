export type Filters = { date_from: string | null; date_to: string | null; state: string | null };
export type Money = string | null;
export type Order = { order_id: string; purchased_at: string; status_code: string; state: string | null; goods_amount: Money; freight_amount: Money; order_amount: Money; units: number; lines: number; delivery_days: number | null; is_late: boolean | null; latest_review_score: number | null };
export type Dashboard = {
  context: { dataset_version: string; kind: 'original' | 'synthetic' | 'external'; currency: string; published_at: string | null; data_from: string | null; data_to: string | null };
  filters: Filters;
  options: { states: string[]; date_min: string | null; date_max: string | null };
  summary: { revenue_brl: string; delivered_orders: number; average_check_brl: Money; buyers: number; repeat_buyers: number; repeat_pct: Money };
  monthly: { month: string; revenue_brl: string; delivered_orders: number }[];
  sellers: { seller_id: string; city: string | null; state: string | null; orders: number; units: number; revenue_brl: string }[];
  categories: { category_key: string; name: string; revenue_brl: string; revenue_pct: Money }[];
  statuses: { status_code: string; orders: number; orders_pct: Money; orders_without_items: number }[];
  delivery: { state: string | null; orders: number; known_delivery_dates: number; average_days: Money; late_orders: number; late_pct: Money; missing_dates: number }[];
  quality: { severity: string; issue_code: string; entity_type: string; issues: number; affected_entities: number }[];
  orders: Order[]; orders_total: number;
  definitions: { id: string; label: string; formula: string; grain: string; status_scope: string; date_field: string; notes: string }[];
};
export type Report = 'orders' | 'monthly' | 'sellers' | 'categories' | 'delivery' | 'statuses' | 'quality';
export type Questions = { context: Dashboard['context']; questions: { id: string; title: string; columns: string[]; rows: (string | number | null)[][]; row_count: number; sql_file: string; sql: string }[] };
export type History = {
  context: Dashboard['context'];
  summary: { products_with_changes: number; category_versions: number; frozen_order_addresses: number; addresses_different_from_profile: number };
  products: { product_id: string; versions: number; current_category: string }[];
  selected_product: string | null;
  category_history: { product_id: string; version_no: number; category_key: string; category_name: string; observed_from: string | null; observed_to: string | null }[];
  product_orders: { order_id: string; purchased_at: string; category_at_order: string; current_category: string; price: string; version_no: number }[];
  orders: { order_id: string; purchased_at: string; snapshot_city: string | null; snapshot_state: string | null; current_city: string | null; current_state: string | null; observed_at: string | null }[];
};

export type DemoStatus = {
  state: 'idle' | 'running' | 'ready' | 'complete' | 'error';
  day: number; total_days: number; database: string; message: string; version_id: string | null;
  summary: { orders?: number; delivered_orders?: number; goods_amount?: string; delivered_goods_amount?: string; latest_purchase?: string; new_orders?: number; changed_statuses?: number; quality?: { severity: string; issue_code: string; rows: number }[] } | null;
};
