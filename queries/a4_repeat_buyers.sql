-- A4: все покупатели и повторные оформления заказов, статусы не фильтруются.
SELECT count(*) AS buyers,count(*) FILTER(WHERE order_count>=2) AS returning_buyers,
       round(100.0*count(*) FILTER(WHERE order_count>=2)/nullif(count(*),0),2) AS returning_pct
FROM mart.buyer_activity;
