"""Ручная демонстрация: одна кнопка публикует один готовый полный снимок."""
import logging
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread

from fastapi import APIRouter, HTTPException

ROOT = Path(__file__).resolve().parent.parent
# CLI-модули сохраняют существующий способ импорта из scripts/.
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))
from db import connect  # noqa: E402
from ingestion import current_version, ingest  # noqa: E402
from simulate import generate  # noqa: E402

DEMO_DATABASE = 'marketplace_demo_dashboard'
DEMO_ROOT = ROOT / 'artifacts/runtime/dashboard-demo'
INCOMING = DEMO_ROOT / 'incoming'
ARCHIVE = DEMO_ROOT / 'archive'
TOTAL_DAYS = 5
router = APIRouter(prefix='/api/demo', tags=['demo'])
logger = logging.getLogger(__name__)
_lock = Lock()
_running = False
_last_error = None


class DemoError(Exception):
    """Диагностика, которую безопасно показывать в интерфейсе."""


def database_exists():
    conn = connect('postgres')
    try:
        with conn, conn.cursor() as cur:
            cur.execute('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)', (DEMO_DATABASE,))
            return cur.fetchone()[0]
    finally:
        conn.close()


def ensure_database():
    """Создаём только отсутствующую БД; существующая никогда не пересобирается."""
    if database_exists():
        conn = connect(DEMO_DATABASE)
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='core' AND table_type='BASE TABLE'")
                if cur.fetchone()[0] != 13:
                    raise DemoError('Демонстрационная база существует, но модель не готова. Нужна проверка подготовки; существующие данные не изменены.')
        finally:
            conn.close()
        return
    # Существующий CLI создаёт только новую пустую БД и собирает её из data/.
    result = subprocess.run([sys.executable, str(ROOT / 'run.py'), 'demo-init', '--database', DEMO_DATABASE],
                            cwd=ROOT, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise DemoError('Не удалось подготовить отдельную демонстрационную базу. Проверьте доступ PostgreSQL и исходные CSV.')


def published_status():
    exists = database_exists()
    current = None
    if exists:
        conn = connect(DEMO_DATABASE)
        try:
            with conn, conn.cursor() as cur:
                current = current_version(cur)
        finally:
            conn.close()
    day = int(current['sequence']) if current else 0
    if day < 0 or day > TOTAL_DAYS:
        raise DemoError('Демонстрационная база содержит несовместимую последовательность снимков.')
    state = 'complete' if day == TOTAL_DAYS else 'ready' if exists else 'idle'
    message = (f'Демонстрация завершена: опубликованы все {TOTAL_DAYS} снимков.' if state == 'complete'
               else f'Опубликовано снимков: {day} из {TOTAL_DAYS}. Следующий снимок запускается кнопкой.' if day
               else 'Готова отдельная демонстрационная база. Можно загрузить первый снимок.' if exists
               else 'Первый запуск подготовит отдельную базу и загрузит первый снимок.')
    return dict(state=state, day=day, total_days=TOTAL_DAYS, database=DEMO_DATABASE,
                message=message, version_id=current['version_id'] if current else None,
                summary=current.get('summary') if current else None)


def get_status():
    try:
        result = published_status()
    except Exception as exc:
        message = str(exc) if isinstance(exc, DemoError) else 'Не удалось прочитать состояние демонстрационной базы.'
        result = dict(state='error', day=0, total_days=TOTAL_DAYS, database=DEMO_DATABASE,
                      message=message, version_id=None, summary=None)
    with _lock:
        if _running:
            result.update(state='running', message='Загружается следующий снимок. Предыдущая версия доступна для чтения.')
        elif _last_error:
            result.update(state='error', message=_last_error)
    return result


def advance_one_day():
    global _running, _last_error
    try:
        ensure_database()
        if not INCOMING.exists():
            generate(ROOT / 'data', INCOMING, days=TOTAL_DAYS, orders_per_day=20, seed=42, with_history=True)
        status = published_status()
        if status['day'] < TOTAL_DAYS:
            batch = INCOMING / f"batch-{status['day'] + 1:03d}"
            if not (batch / 'manifest.json').is_file():
                raise DemoError('Готовый демонстрационный снимок не найден. Существующая серия не перезаписана.')
            result = ingest(batch, ARCHIVE, dbname=DEMO_DATABASE)
            if result['status'] == 'busy':
                raise DemoError('Демонстрационная база уже обрабатывает снимок. Повторите после завершения загрузки.')
            if result['status'] not in {'published', 'skipped'}:
                raise DemoError('Снимок не опубликован. Прежняя версия сохранена; проверьте журнал загрузки и повторите.')
    except Exception as exc:
        logger.exception('Не удалось обработать демонстрационный снимок')
        message = str(exc) if isinstance(exc, DemoError) else 'Не удалось подготовить или загрузить снимок. Проверьте доступ к PostgreSQL и исходные CSV.'
        with _lock:
            _last_error = message
    finally:
        with _lock:
            _running = False


@router.get('/status')
def demo_status():
    return get_status()


@router.post('/advance', status_code=202)
def demo_advance():
    global _running, _last_error
    # Чтение БД также защищено: два одновременных POST не стартуют два потока.
    with _lock:
        if _running:
            raise HTTPException(409, 'Демонстрационный снимок уже загружается')
        try:
            status = published_status()
        except Exception as exc:
            message = str(exc) if isinstance(exc, DemoError) else 'Не удалось прочитать состояние демонстрационной базы.'
            raise HTTPException(503, message) from exc
        if status['state'] == 'complete':
            return status
        _last_error = None
        _running = True
        try:
            Thread(target=advance_one_day, name='dashboard-demo', daemon=True).start()
        except Exception:
            _running = False
            _last_error = 'Не удалось запустить загрузку демонстрационного снимка.'
            raise HTTPException(503, _last_error)
        return dict(status, state='running', message='Запущена загрузка следующего полного снимка.')
