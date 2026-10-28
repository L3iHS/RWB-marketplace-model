"""Интеграционные контракты на PostgreSQL 16. Искусственные случаи — в отдельной временной БД."""
import hashlib
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

from psycopg2 import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
from db import connect


def run_sql_file(dbname, path, success=True):
    result = subprocess.run(
        ['docker','compose','exec','-T','postgres','psql','-X','-v','ON_ERROR_STOP=1',
         '-U','hack','-d',dbname,'-f',path], cwd=ROOT,capture_output=True,text=True,
    )
    if success and result.returncode:
        raise AssertionError(result.stdout+result.stderr)
    return result


def rows(dbname, query):
    with connect(dbname) as conn, conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def fingerprint(dbname, schema):
    with connect(dbname) as conn, conn.cursor() as cur:
        cur.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename',(schema,))
        tables = [row[0] for row in cur.fetchall()]
        digest = hashlib.sha256()
        for table in tables:
            cur.execute(sql.SQL("SELECT count(*),md5(string_agg(row_hash,'' ORDER BY row_hash)) FROM (SELECT md5(to_jsonb(t)::text) AS row_hash FROM {}.{} t) s").format(sql.Identifier(schema),sql.Identifier(table)))
            digest.update(str((table,cur.fetchone())).encode())
        return digest.hexdigest()


class DatasetContract(unittest.TestCase):
    def test_reference_and_invariants(self):
        run_sql_file('marketplace','/checks/invariants.sql')
        run_sql_file('marketplace','/checks/reference.sql')

    def test_rebuild_preserves_raw_and_results(self):
        before_raw = fingerprint('marketplace','raw')
        before_core = fingerprint('marketplace','core')
        run_sql_file('marketplace','/model/build.sql')
        self.assertEqual(before_raw,fingerprint('marketplace','raw'))
        self.assertEqual(before_core,fingerprint('marketplace','core'))
        run_sql_file('marketplace','/checks/reference.sql')

    def test_reports_do_not_read_raw(self):
        for path in (ROOT/'queries').glob('*.sql'):
            with self.subTest(path=path.name):
                self.assertNotRegex(path.read_text(),r'\braw\.')


class EdgeCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dbname='rwb_test_'+uuid.uuid4().hex[:12]
        admin=connect('postgres')
        admin.autocommit=True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        admin.close()
        cls.addClassCleanup(cls.drop_database)
        with connect(cls.dbname) as conn,conn.cursor() as cur:
            cur.execute('CREATE SCHEMA raw')
            cur.execute((ROOT/'scripts/init/02_raw_ddl.sql').read_text())
            cur.execute("""
                INSERT INTO raw.customers(customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state) VALUES
                ('c1','b1','00123','first','SP'),('c2','b1','00456','second','RJ'),
                ('c3','b2','00123','third','SP'),('c4','b3','00567','fourth','SP');
                INSERT INTO raw.sellers(seller_id,seller_city,seller_state) VALUES ('s1','city1','SP'),('s2','city2','RJ');
                INSERT INTO raw.product_category_translation VALUES ('known','Known',NULL,now());
                INSERT INTO raw.products(product_id,product_category_name) VALUES
                ('p1','known'),('p2','known'),('p3',NULL),('p4','untranslated');
                INSERT INTO raw.orders(order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date,order_estimated_delivery_date) VALUES
                ('o1','c1','delivered','2017-01-15 10:00','2017-01-20 17:00','2017-01-20'),
                ('o2','c2','delivered','2017-03-01 10:00','2017-03-05 12:00','2017-03-04'),
                ('o3','c3','canceled','2017-03-01 12:00',NULL,NULL),
                ('o4','c4','delivered','2017-03-02 10:00',NULL,NULL);
                INSERT INTO raw.order_items(order_id,order_item_id,product_id,seller_id,price,freight_value) VALUES
                ('o1','1','p1','s1','10.00','1.00'),('o1','2','p1','s1','10.00','1.00'),
                ('o1','3','p2','s2','20.00','2.00'),('o2','1','p3','s1','30.00','3.00'),
                ('o3','1','p1','s1','100.00','10.00'),('o4','1','p4','s1','5.00','0.00');
                INSERT INTO raw.order_payments(order_id,payment_sequential,payment_type,payment_installments,payment_value) VALUES
                ('o1','1','credit_card','4','40.00'),('o1','2','voucher','1','4.00'),
                ('o2','1','credit_card','1','33.00'),('o3','1','credit_card','1','110.00');
                INSERT INTO raw.order_reviews(review_id,order_id,review_score,review_creation_date,review_answer_timestamp) VALUES
                ('r1','o1','1','2017-01-21','2017-01-22'),('r2','o1','5','2017-01-23','2017-01-24'),
                ('r1','o2','3','2017-03-06','2017-03-07');
            """)
        run_sql_file(cls.dbname,'/model/build.sql')

    @classmethod
    def drop_database(cls):
        if not cls.dbname.startswith('rwb_test_'):
            raise AssertionError('Unsafe test database name')
        admin=connect('postgres')
        admin.autocommit=True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.dbname)))
        admin.close()

    def query(self, query):
        return rows(self.dbname,query)

    def test_multiple_children_do_not_inflate_totals(self):
        self.assertEqual(self.query("SELECT item_rows,units,goods_total,freight_total,paid_total,review_count FROM mart.order_summary WHERE order_id='o1'"),
                         [(3,3,Decimal('40'),Decimal('4'),Decimal('44'),2)])

    def test_installments_do_not_multiply_payment(self):
        self.assertEqual(self.query("SELECT sum(payment_value) FROM core.order_payments WHERE order_id='o1'")[0][0],Decimal('44'))

    def test_seller_receives_only_own_items(self):
        self.assertEqual(self.query('SELECT seller_id,order_count,units,revenue FROM mart.seller_sales ORDER BY seller_id'),
                         [('s1',3,4,Decimal('55')),('s2',1,1,Decimal('20'))])

    def test_missing_category_and_translation_preserved(self):
        self.assertEqual(self.query('SELECT category_key,revenue FROM mart.category_sales ORDER BY category_key'),
                         [('__unknown__',Decimal('30')),('known',Decimal('40')),('untranslated',Decimal('5'))])

    def test_average_at_order_level(self):
        self.assertEqual(self.query("SELECT round(avg(order_total),2) FROM mart.order_summary WHERE order_status='delivered'")[0][0],Decimal('27.33'))

    def test_stable_buyer_and_address_context(self):
        self.assertEqual(self.query("SELECT order_count FROM mart.buyer_activity WHERE buyer_id='b1'"),[(2,)])
        self.assertEqual(self.query("SELECT customer_id,city,zip_code_prefix FROM core.customer_profiles WHERE buyer_id='b1' ORDER BY customer_id"),
                         [('c1','first','00123'),('c2','second','00456')])
        self.assertEqual(self.query('SELECT count(*) FROM core.buyers'),[(3,)])

    def test_empty_month_included(self):
        self.assertEqual(self.query("SELECT order_count,revenue FROM mart.sales_by_month('2017-01-01','2017-03-01') ORDER BY month"),
                         [(1,Decimal('40')),(0,Decimal('0')),(2,Decimal('35'))])

    def test_status_not_delivery_date_defines_sales(self):
        self.assertEqual(self.query('SELECT sum(price) FROM mart.sales_items'),[(Decimal('75'),)])
        self.assertEqual(self.query("SELECT count(*) FROM mart.quality_issues WHERE issue_code='delivered_without_date'"),[(1,)])

    def test_reviews_keep_shared_identifier_and_history(self):
        self.assertEqual(self.query('SELECT count(*) FROM core.order_reviews'),[(3,)])
        self.assertEqual(self.query("SELECT latest_review_score FROM mart.order_summary WHERE order_id='o1'"),[(5,)])

    def test_delivery_deadline_compared_by_date(self):
        self.assertEqual(self.query("SELECT delay_days FROM mart.order_summary WHERE order_id='o1'"),[(0,)])
        self.assertEqual(self.query("SELECT delay_days FROM mart.order_summary WHERE order_id='o2'"),[(1,)])

    def test_missing_payment_is_not_zero(self):
        self.assertEqual(self.query("SELECT payment_count,paid_total,payment_delta FROM mart.order_summary WHERE order_id='o4'"),[(0,None,None)])

    def test_rebuild_does_not_change_source(self):
        before=fingerprint(self.dbname,'raw')
        run_sql_file(self.dbname,'/model/build.sql')
        self.assertEqual(before,fingerprint(self.dbname,'raw'))

    def test_bad_input_rolls_back_model_without_deleting_raw(self):
        cases = [
            ("INSERT INTO raw.order_items(order_id,order_item_id,product_id,seller_id,price,freight_value) VALUES ('o1','9','p1','s1','oops','1')", "DELETE FROM raw.order_items WHERE order_item_id='9'"),
            ("INSERT INTO raw.order_items(order_id,order_item_id,product_id,seller_id,price,freight_value) VALUES ('missing','9','p1','s1','1','1')", "DELETE FROM raw.order_items WHERE order_id='missing'"),
            ("INSERT INTO raw.order_reviews(review_id,order_id,review_score) VALUES ('r1','o1','5')", "DELETE FROM raw.order_reviews WHERE review_id='r1' AND order_id='o1' AND review_creation_date IS NULL"),
        ]
        for insert,cleanup in cases:
            with self.subTest(insert=insert):
                before=fingerprint(self.dbname,'core')
                with connect(self.dbname) as conn,conn.cursor() as cur:
                    cur.execute(insert)
                dirty_raw=fingerprint(self.dbname,'raw')
                try:
                    result=run_sql_file(self.dbname,'/model/build.sql',success=False)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('ERROR',result.stderr)
                    self.assertEqual(before,fingerprint(self.dbname,'core'))
                    self.assertEqual(dirty_raw,fingerprint(self.dbname,'raw'))
                finally:
                    with connect(self.dbname) as conn,conn.cursor() as cur:
                        cur.execute(cleanup)


if __name__=='__main__':
    unittest.main()
