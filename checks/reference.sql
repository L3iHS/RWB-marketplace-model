-- Эталонные значения только для зафиксированного датасета организаторов.
DO $$
BEGIN
  ASSERT (SELECT sum(revenue) FROM mart.sales_by_month('2016-09-01','2018-08-01')) = 13221498.11, 'A1: выручка';
  ASSERT (SELECT count(*) FROM mart.sales_by_month('2016-09-01','2018-08-01')) = 24, 'A1: месяцы';
  ASSERT (SELECT count(*) FROM mart.sales_by_month('2016-09-01','2018-08-01') WHERE revenue=0) = 1, 'A1: пустой месяц';
  ASSERT (SELECT max(revenue) FROM mart.seller_sales) = 226987.93, 'A2: первый продавец';
  ASSERT (SELECT round(avg(order_total),2) FROM mart.order_summary WHERE order_status='delivered') = 159.88, 'A3: средний чек';
  ASSERT (SELECT count(*) FROM mart.buyer_activity) = 96096, 'A4: покупатели';
  ASSERT (SELECT round(100.0*count(*) FILTER(WHERE order_count>=2)/count(*),2) FROM mart.buyer_activity) = 3.12, 'A4: повторные заказы';
  ASSERT (SELECT count(*) FROM mart.category_sales) = 74, 'A5: категории';
  ASSERT (SELECT max(revenue) FROM mart.category_sales) = 1233131.72, 'A5: крупнейшая категория';
  ASSERT (SELECT sum(revenue) FROM mart.category_sales) = 13221498.11, 'A5: сумма';
END $$;
SELECT 'Эталонные проверки A1–A5 пройдены' AS result;
