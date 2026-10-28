#!/usr/bin/env python3
"""Выполнить исследование и сохранить ipynb с выводами + статический HTML.

Базу notebook только читает. Сохранённые выводы позволяют показать жюри
фактическое выполнение без работающего Jupyter на машине просмотра.
Зависимости: .venv/bin/python -m pip install -r requirements-notebook.txt
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter
from jupyter_client import KernelManager

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notebook',type=Path,default=ROOT/'notebooks/01_data_investigation.ipynb')
    args=parser.parse_args()
    notebook_path=args.notebook.resolve()
    notebook=nbformat.read(notebook_path,as_version=4)
    nbformat.validate(notebook)
    # Кэши и kernel-файлы не засоряют профиль пользователя и не попадают в Git.
    with tempfile.TemporaryDirectory(prefix='capibara-notebook-') as temporary:
        for variable,folder in [('IPYTHONDIR','ipython'),('JUPYTER_RUNTIME_DIR','runtime'),
                                ('JUPYTER_CONFIG_DIR','config'),('MPLCONFIGDIR','matplotlib')]:
            directory=Path(temporary)/folder
            directory.mkdir()
            os.environ[variable]=str(directory)
        manager=KernelManager(kernel_name='python3', transport='ipc' if os.name=='posix' else 'tcp')
        # Используем именно Python из .venv, с которым вызван этот скрипт.
        manager.kernel_spec.argv=[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}']
        client=NotebookClient(notebook,km=manager,timeout=180,
            resources={'metadata':{'path':str(ROOT)}},allow_errors=False)
        try:
            executed=client.execute()
        finally:
            if manager.has_kernel:
                manager.shutdown_kernel(now=True)
            manager.cleanup_resources()
    nbformat.validate(executed)
    if any(output.output_type=='error' for cell in executed.cells if cell.cell_type=='code'
           for output in cell.get('outputs',[])):
        raise RuntimeError('Notebook содержит ошибку выполнения')
    # Сохраняем только после успешного исполнения: не затираем рабочий отчёт
    # частично выполненной версией при ошибке подключения/SQL.
    source_hash=hashlib.sha256(json.dumps([cell.source for cell in executed.cells],
        ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    executed.metadata.setdefault('capibara',{})['executed_source_sha256']=source_hash
    exporter=HTMLExporter(template_name='lab')
    html,_=exporter.from_notebook_node(executed)
    nbformat.write(executed,notebook_path)
    html_path=notebook_path.with_suffix('.html')
    html_path.write_text(f'<!-- capibara-source-sha256: {source_hash} -->\n'+html,encoding='utf-8')
    code_cells=[cell for cell in executed.cells if cell.cell_type=='code']
    print('Выполненных ячеек:',len(code_cells))
    print('Notebook:',notebook_path)
    print('HTML для просмотра без Python:',html_path)


if __name__=='__main__':
    main()
