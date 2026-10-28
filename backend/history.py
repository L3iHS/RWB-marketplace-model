"""История категорий и адресов из переданного согласованного снимка БД."""


def history_data(cur, product_id=None, order_id=None):
    def rows(statement, params=None):
        cur.execute(statement, params)
        columns = [column.name for column in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    summary = rows('''SELECT
        (SELECT count(*) FROM (SELECT product_id FROM core.product_category_history
            GROUP BY product_id HAVING count(*) > 1) changed) AS products_with_changes,
        (SELECT count(*) FROM core.product_category_history) AS category_versions,
        (SELECT count(*) FROM core.order_addresses) AS frozen_order_addresses,
        (SELECT count(*) FROM core.order_addresses a JOIN core.orders o USING(order_id)
            JOIN core.customer_order_profiles p USING(customer_id)
            WHERE (a.zip_code_prefix,a.city,a.state) IS DISTINCT FROM
                  (p.zip_code_prefix,p.city,p.state)) AS addresses_different_from_profile''')[0]
    products = rows('''SELECT p.product_id,count(*) AS versions,c.name AS current_category
        FROM core.products p JOIN core.product_category_history h USING(product_id)
        JOIN core.categories c ON c.category_key=p.category_key
        GROUP BY p.product_id,c.name ORDER BY versions DESC,p.product_id LIMIT 25''')
    selected_product = product_id or (products[0]['product_id'] if products else None)
    category_history = rows('''SELECT h.product_id,h.version_no,h.category_key,
            c.name AS category_name,h.observed_from,h.observed_to
        FROM core.product_category_history h JOIN core.categories c USING(category_key)
        WHERE h.product_id=%s ORDER BY h.version_no''', (selected_product,))
    product_orders = rows('''SELECT i.order_id,o.purchased_at,
            previous.name AS category_at_order,current.name AS current_category,
            i.price,h.version_no
        FROM core.order_items i JOIN core.orders o USING(order_id)
        JOIN core.product_category_history h
          ON h.product_id=i.product_id AND h.version_no=i.category_version_no
        JOIN core.categories previous ON previous.category_key=h.category_key
        JOIN core.products p ON p.product_id=i.product_id
        JOIN core.categories current ON current.category_key=p.category_key
        WHERE i.product_id=%s
        ORDER BY o.purchased_at DESC,i.order_id,i.order_item_id LIMIT 20''', (selected_product,))
    orders = rows('''SELECT o.order_id,o.purchased_at,a.city AS snapshot_city,
            a.state AS snapshot_state,p.city AS current_city,p.state AS current_state,a.observed_at
        FROM core.orders o JOIN core.order_addresses a USING(order_id)
        JOIN core.customer_order_profiles p USING(customer_id)
        WHERE (%s::text IS NULL OR o.order_id=%s)
        ORDER BY ((a.zip_code_prefix,a.city,a.state) IS DISTINCT FROM
                  (p.zip_code_prefix,p.city,p.state)) DESC,o.purchased_at DESC,o.order_id
        LIMIT 20''', (order_id or None, order_id or None))
    return dict(summary=summary, products=products, selected_product=selected_product,
                category_history=category_history, product_orders=product_orders, orders=orders)
