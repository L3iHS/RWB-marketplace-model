"""Детерминированные полные снимки Olist + вымышленные новые операции."""
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import uuid

from batches import FILES, seal_batch, sha256, write_json


def read_rows(source, table):
    name = next(name for name, (name_table, _) in FILES.items() if table == name_table)
    with (source / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def timestamp(value):
    return value.strftime('%Y-%m-%d %H:%M:%S')


def append_rows(source, destination, rows, columns):
    # Исторические строки копируются побайтно, включая BOM/переводы строк.
    shutil.copyfile(source, destination)
    if not rows:
        return
    with source.open('rb') as f:
        header = f.readline()
    ending = '\r\n' if b'\r\n' in header else '\r' if b'\r' in header else '\n'
    with destination.open('rb+') as f:
        f.seek(-1, os.SEEK_END)
        if f.read(1) not in {b'\n', b'\r'}:
            f.write(ending.encode())
    with destination.open('a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator=ending)
        writer.writerows(rows)


def generate(source, output, days=5, orders_per_day=20, seed=42, with_history=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError(f'{output}: каталог уже существует; готовая демонстрация не перезаписывается')
    if days < 1 or orders_per_day < 1:
        raise ValueError('Число дней и заказов должно быть положительным')
    base_hashes = {name: sha256(source / name) for name in FILES}
    identity = dict(base_sha256=base_hashes, days=days, orders_per_day=orders_per_day, seed=seed)
    if with_history:
        identity['with_history'] = True
    source_id = 'synthetic-' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, source_id)

    def identifier(kind, number):
        return 'syn_' + uuid.uuid5(namespace, f'{kind}:{number}').hex

    rng = random.Random(seed)
    products = read_rows(source, 'products')
    sellers = read_rows(source, 'sellers')
    customers = read_rows(source, 'customers')
    if not products or not sellers or not customers:
        raise ValueError('Для симуляции нужны непустые товары, продавцы и покупатели')
    orders_name = next(name for name, (table, _) in FILES.items() if table == 'orders')
    with (source / orders_name).open(encoding='utf-8-sig', newline='') as f:
        latest = max(datetime.fromisoformat(value) for row in csv.DictReader(f)
                     for column, value in row.items()
                     if value and column in {'order_purchase_timestamp', 'order_approved_at',
                                             'order_delivered_carrier_date', 'order_delivered_customer_date'})
    reviews_name = next(name for name, (table, _) in FILES.items() if table == 'order_reviews')
    with (source / reviews_name).open(encoding='utf-8-sig', newline='') as f:
        latest = max([latest, *(datetime.fromisoformat(value) for row in csv.DictReader(f)
                               for column, value in row.items()
                               if value and column in {'review_creation_date', 'review_answer_timestamp'})])
    start = (latest + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    new_product = dict(products[0], product_id=identifier('product', 0))
    new_seller = dict(sellers[0], seller_id=identifier('seller', 0))
    history_change = None
    if with_history:
        categories = read_rows(source, 'product_category_translation')
        new_category = next((row['product_category_name'] for row in categories
                             if row['product_category_name'] != new_product['product_category_name']), None)
        if new_category is None:
            raise ValueError('Для демонстрации истории нужны две категории в справочнике')
    plans = []
    for day in range(days):
        for index in range(orders_per_day):
            number = day * orders_per_day + index
            purchase = start + timedelta(days=day, hours=9, minutes=rng.randrange(240))
            profile = dict(rng.choice(customers), customer_id=identifier('profile', number))
            # Каждый третий заказ — покупка уже известного человека с новым адресным ID.
            if number % 3:
                profile['customer_unique_id'] = identifier('buyer', number)
            product = new_product if number % 4 == 0 else rng.choice(products)
            seller = new_seller if number % 4 == 0 else rng.choice(sellers)
            items, total = [], Decimal('0')
            for item in range(1, rng.randrange(1, 4) + 1):
                price = Decimal(rng.randrange(1000, 50001)) / 100
                freight = Decimal(rng.randrange(100, 3001)) / 100
                total += price + freight
                items.append(dict(order_id=identifier('order', number), order_item_id=str(item),
                                  product_id=product['product_id'], seller_id=seller['seller_id'],
                                  shipping_limit_date=timestamp(purchase + timedelta(days=1)),
                                  price=f'{price:.2f}', freight_value=f'{freight:.2f}'))
            payments = [dict(order_id=identifier('order', number), payment_sequential='1',
                             payment_type='credit_card', payment_installments=str(rng.choice([1, 2, 4])),
                             payment_value=f'{total:.2f}')]
            if number % 4 == 0:
                voucher = Decimal('5.00')
                payments[0]['payment_value'] = f'{total - voucher:.2f}'
                payments.append(dict(order_id=identifier('order', number), payment_sequential='2',
                                     payment_type='voucher', payment_installments='1', payment_value=f'{voucher:.2f}'))
            lifecycle = number % 5
            carrier = purchase + timedelta(hours=2 if lifecycle == 0 else 18)
            delivery = purchase + timedelta(hours=8) if lifecycle == 0 else purchase + timedelta(days={1: 1, 2: 3, 3: 2, 4: 2}[lifecycle])
            plans.append(dict(number=number, day=day, profile=profile, items=items, payments=payments,
                              purchase=purchase, carrier=carrier, delivery=delivery,
                              canceled=lifecycle == 3, late=lifecycle == 2))
    if with_history:
        first_profile = plans[0]['profile']
        new_address = next((row for row in customers
                            if row['customer_state'] != first_profile['customer_state']
                            and row['customer_city'] != first_profile['customer_city']), None)
        if new_address is None:
            raise ValueError('Для демонстрации истории нужны адреса в разных городах и штатах')
        history_change = dict(
            from_sequence=3, product_id=new_product['product_id'], order_id=identifier('order', 0),
            customer_id=first_profile['customer_id'],
            category_before=new_product['product_category_name'], category_after=new_category,
            address_before={key: first_profile[key] for key in ('customer_state', 'customer_city')},
            address_after={key: new_address[key] for key in ('customer_state', 'customer_city')},
            notice='С третьего снимка меняются текущая категория синтетического товара и адрес профиля. '
                   'Ранее опубликованные позиции и адрес первого заказа сохраняются в истории модели.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.simulation-', dir=output.parent) as temporary:
        stage = Path(temporary)
        snapshots = []
        for day in range(days):
            cutoff = start + timedelta(days=day + 1) - timedelta(seconds=1)
            extras = {table: [] for table, _ in FILES.values()}
            snapshot_product = dict(new_product)
            if with_history and day >= 2:
                snapshot_product['product_category_name'] = new_category
            extras['products'].append(snapshot_product)
            extras['sellers'].append(new_seller)
            statuses = {}
            for plan in plans:
                if plan['day'] > day:
                    continue
                purchase, number = plan['purchase'], plan['number']
                delivered = not plan['canceled'] and plan['delivery'] <= cutoff
                shipped = not plan['canceled'] and plan['carrier'] <= cutoff
                order_status = 'canceled' if plan['canceled'] else 'delivered' if delivered else 'shipped' if shipped else 'approved'
                statuses[order_status] = statuses.get(order_status, 0) + 1
                extras['orders'].append(dict(
                    order_id=identifier('order', number), customer_id=plan['profile']['customer_id'],
                    order_status=order_status, order_purchase_timestamp=timestamp(purchase),
                    order_approved_at=timestamp(purchase + timedelta(minutes=10)),
                    order_delivered_carrier_date=timestamp(plan['carrier']) if shipped else '',
                    order_delivered_customer_date=timestamp(plan['delivery']) if delivered else '',
                    order_estimated_delivery_date=timestamp((purchase + timedelta(days=2)).replace(hour=23, minute=59, second=59))))
                profile = dict(plan['profile'])
                if with_history and day >= 2 and plan['number'] == 0:
                    profile.update({key: new_address[key] for key in
                                    ('customer_state', 'customer_city', 'customer_zip_code_prefix')})
                extras['customers'].append(profile)
                extras['order_items'].extend(plan['items'])
                extras['order_payments'].extend(plan['payments'])
                review_time = plan['delivery'] + timedelta(hours=1)
                if delivered and review_time + timedelta(minutes=30) <= cutoff:
                    extras['order_reviews'].append(dict(
                        review_id=identifier('review', number), order_id=identifier('order', number),
                        review_score='2' if plan['late'] else '5', review_comment_title='Synthetic demo',
                        review_comment_message='Синтетический отзыв для демонстрации обновления',
                        review_creation_date=timestamp(review_time), review_answer_timestamp=timestamp(review_time + timedelta(minutes=30))))
            batch = stage / f'batch-{day + 1:03d}'
            batch.mkdir()
            for name, (table, columns) in FILES.items():
                append_rows(source / name, batch / name, extras[table], columns)
            metadata = dict(seed=seed, simulation_date=cutoff.date().isoformat(),
                            synthetic_orders=(day + 1) * orders_per_day, statuses=statuses,
                            base_sha256=base_hashes,
                            notice='Вымышленные операции; исторические строки Olist сохранены. Это не поток WB.')
            if with_history:
                metadata['history_scenario'] = dict(history_change, applied=day >= 2)
            manifest = seal_batch(batch, source_id, day + 1, 'synthetic', simulation=metadata)
            snapshots.append(dict(directory=batch.name, sequence=day + 1, **metadata,
                                  orders=manifest['files'][orders_name]['rows']))
        report = dict(format_version=1, source_id=source_id, **identity, snapshots=snapshots)
        # Сканер рассматривает только каталоги готовых пакетов, не этот отчёт.
        write_json(stage / 'simulation.json', report)
        os.replace(stage, output)
    return report
