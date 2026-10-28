"""Контракт готового полного снимка: восемь CSV и атомарный manifest.json."""
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from load_raw import MAPPING

FILES = {name: (table.split('.')[1], columns) for name, table, columns in MAPPING}
KEYS = {
    'orders': ('order_id',), 'order_items': ('order_id', 'order_item_id'),
    'order_payments': ('order_id', 'payment_sequential'),
    'order_reviews': ('review_id', 'order_id'), 'products': ('product_id',),
    'sellers': ('seller_id',), 'customers': ('customer_id',),
    'product_category_translation': ('product_category_name',),
}
REQUIRED = {
    'orders': ('customer_id', 'order_status', 'order_purchase_timestamp'),
    'order_items': ('product_id', 'seller_id', 'price', 'freight_value'),
    'order_payments': ('payment_type', 'payment_installments', 'payment_value'),
    'order_reviews': ('review_score',), 'customers': ('customer_unique_id',),
}
INTEGER_COLUMNS = {
    'order_item_id', 'payment_sequential', 'payment_installments', 'review_score',
    'product_name_lenght', 'product_description_lenght', 'product_photos_qty',
    'product_weight_g', 'product_length_cm', 'product_height_cm', 'product_width_cm',
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    with Path(path).open('w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def inspect_csv(path, table, columns):
    """Диагностика файла/строки до изменения core; FK проверяет PostgreSQL."""
    keys, rows = set(), 0
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f, strict=True)
        if next(reader, None) != columns:
            raise ValueError(f'{Path(path).name}: несовместимый заголовок')
        try:
            for values in reader:
                rows += 1
                location = f'{Path(path).name}, строка {reader.line_num}'
                if len(values) != len(columns):
                    raise ValueError(f'{location}: ожидалось {len(columns)} полей, получено {len(values)}')
                record = dict(zip(columns, values))
                for column in (*KEYS[table], *REQUIRED.get(table, ())):
                    if not record[column]:
                        raise ValueError(f'{location}: пустое обязательное поле {column}')
                for column, value in record.items():
                    if not value:
                        continue
                    try:
                        if column in INTEGER_COLUMNS:
                            record[column] = int(value)
                        elif column in {'price', 'freight_value', 'payment_value'}:
                            number = Decimal(value)
                            if not number.is_finite() or number < 0:
                                raise ValueError('нужна конечная неотрицательная сумма')
                        elif column.endswith(('_timestamp', '_date')) or column == 'order_approved_at':
                            parsed = datetime.fromisoformat(value)
                            if parsed.tzinfo is not None:
                                raise ValueError('бизнес-время должно быть без часового пояса')
                    except (ValueError, InvalidOperation) as error:
                        raise ValueError(f'{location}: {column}={value!r}: {error}') from error
                key = tuple(record[c] for c in KEYS[table])
                if key in keys:
                    raise ValueError(f'{location}: повтор ключа {KEYS[table]}={key}')
                keys.add(key)
        except csv.Error as error:
            raise ValueError(f'{Path(path).name}, строка {reader.line_num}: {error}') from error
    return {'rows': rows, 'bytes': Path(path).stat().st_size, 'sha256': sha256(path)}


def inspect_files(directory):
    directory = Path(directory)
    actual = {p.name for p in directory.iterdir()}
    if actual - set(FILES) - {'manifest.json'} or set(FILES) - actual:
        raise ValueError(f'Состав снимка: отсутствуют {sorted(set(FILES) - actual)}, '
                         f'неожиданные файлы {sorted(actual - set(FILES) - {"manifest.json"})}')
    return {name: inspect_csv(directory / name, table, columns)
            for name, (table, columns) in FILES.items()}


def validate_manifest(value):
    if not isinstance(value, dict):
        raise ValueError('manifest должен быть JSON-объектом')
    if value.get('format_version') != 1 or value.get('snapshot_type') != 'full':
        raise ValueError('Поддерживается manifest версии 1 и snapshot_type=full')
    if value.get('kind') not in {'synthetic', 'external'}:
        raise ValueError('kind должен быть synthetic или external')
    if not isinstance(value.get('source_id'), str) or not value['source_id'].strip():
        raise ValueError('Нужен непустой source_id')
    if type(value.get('sequence')) is not int or value['sequence'] < 1:
        raise ValueError('sequence должен быть положительным целым числом')
    if set(value.get('files', {})) != set(FILES):
        raise ValueError('manifest должен описывать все восемь CSV')
    return value


def read_manifest(directory):
    return validate_manifest(json.loads((Path(directory) / 'manifest.json').read_text(encoding='utf-8')))


def seal_batch(directory, source_id, sequence, kind='external', **metadata):
    directory = Path(directory)
    if (directory / 'manifest.json').exists():
        raise ValueError('Готовый пакет уже имеет manifest; создайте новый каталог')
    manifest = dict(metadata, format_version=1, snapshot_type='full', kind=kind,
                    source_id=source_id, sequence=sequence,
                    created_at=datetime.now(timezone.utc).isoformat(), files=inspect_files(directory))
    validate_manifest(manifest)
    # Manifest — сигнал готовности; он появляется только после всех CSV.
    temporary = directory / '.manifest.tmp'
    try:
        write_json(temporary, manifest)
        os.replace(temporary, directory / 'manifest.json')
        read_manifest(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def fingerprint(manifest):
    data = [(name, manifest['files'][name]['sha256']) for name in sorted(FILES)]
    return hashlib.sha256(json.dumps(data, separators=(',', ':')).encode()).hexdigest()


def archive_batch(directory, archive_root, attempt_id):
    """Читаем только собственную проверенную копию, источник далее не используется."""
    directory, archive_root = Path(directory), Path(archive_root)
    archive_root.mkdir(parents=True, exist_ok=True)
    destination = archive_root / attempt_id
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=archive_root) as temporary:
        stage = Path(temporary)
        for name in (*FILES, 'manifest.json'):
            source = directory / name
            if source.is_symlink() or not source.is_file():
                raise ValueError(f'{name}: нужен обычный файл')
            with source.open('rb') as src, (stage / name).open('wb') as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
        # Не принимаем лишние файлы даже если они не скопированы в архив.
        if {p.name for p in directory.iterdir()} != set(FILES) | {'manifest.json'}:
            raise ValueError('В каталоге снимка есть неожиданные файлы')
        manifest = read_manifest(stage)
        if manifest['files'] != inspect_files(stage):
            raise ValueError('Размер, число строк или SHA-256 не совпали с manifest')
        os.replace(stage, destination)
    return destination, manifest
