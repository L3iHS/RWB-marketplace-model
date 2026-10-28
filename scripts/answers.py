"""Запросы A1–A5 -> CSV и JSON; только чтение модели."""
import csv
import json
from pathlib import Path
from db import connect

ROOT = Path(__file__).resolve().parent.parent

def main():
    output = ROOT / 'artifacts' / 'answers'
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        for path in sorted((ROOT/'queries').glob('a[1-5]_*.sql')):
            cur.execute(path.read_text())
            names = [c.name for c in cur.description]
            rows = cur.fetchall()
            with (output/(path.stem+'.csv')).open('w',newline='',encoding='utf-8') as f:
                writer=csv.writer(f)
                writer.writerow(names)
                writer.writerows(rows)
            report[path.stem] = [dict(zip(names,row)) for row in rows]
            print(f'{path.stem}: {len(rows)} строк')
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')

if __name__ == '__main__':
    main()
