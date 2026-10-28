-- A1: товары доставленных заказов, месяц оформления; доставка не входит в выручку.
SELECT month,order_count,revenue
FROM mart.sales_by_month(DATE '2016-09-01',DATE '2018-08-01') ORDER BY month;
