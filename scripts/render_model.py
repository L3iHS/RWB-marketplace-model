"""Render the current core DDL as an ER diagram; requires Graphviz, no database."""

from dataclasses import dataclass
from hashlib import sha256
from html import escape
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "model/schema.sql"
OUTPUT = ROOT / "docs/images"
CAPTIONS = {
    "buyers": ("Покупатели", "Одна строка — один покупатель"),
    "customer_profiles": ("Профили покупателей", "Адресный контекст из источника"),
    "sellers": ("Продавцы", "Одна строка — один продавец"),
    "categories": ("Категории", "Включая неизвестную категорию"),
    "products": ("Товары", "Одна строка — одна карточка товара"),
    "order_statuses": ("Статусы заказов", "Одна строка — один статус"),
    "orders": ("Заказы", "Одна строка — один заказ"),
    "order_items": ("Позиции заказов", "Одна строка — одна единица товара"),
    "order_payments": ("Платежи", "Одна строка — одна запись платежа"),
    "order_reviews": ("Отзывы", "Одна строка — пара отзыв / заказ"),
}


@dataclass
class Column:
    name: str
    kind: str
    primary: bool
    required: bool
    reference: str | None


def read_schema(source: str) -> dict[str, list[Column]]:
    """Read the CREATE TABLE subset used by model/schema.sql; reject unknown lines."""
    tables = {}
    for name, body in re.findall(r"CREATE TABLE core\.(\w+) \(\n(.*?)\n\);", source, re.S):
        columns = []
        primary = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if match := re.fullmatch(r"PRIMARY KEY \(([^)]+)\)", line):
                primary = [part.strip() for part in match[1].split(",")]
                continue
            if re.fullmatch(r"CHECK \(.*\)", line):
                continue
            match = re.fullmatch(r"(\w+) (text|integer|smallint|numeric|timestamp|boolean)\b(.*)", line)
            if not match:
                raise ValueError(f"Unsupported DDL in {name}: {line}")
            column, kind, constraints = match.groups()
            reference = re.search(r"REFERENCES core\.(\w+)\b", constraints)
            columns.append(Column(column, kind, "PRIMARY KEY" in constraints,
                                  "NOT NULL" in constraints, reference[1] if reference else None))
        for column in columns:
            column.primary |= column.name in primary
            column.required |= column.primary
        if set(primary) - {column.name for column in columns}:
            raise ValueError(f"Unknown primary key column in {name}")
        tables[name] = columns
    if len(tables) != source.count("CREATE TABLE ") or set(tables) != set(CAPTIONS):
        raise ValueError("Table list changed: update diagram captions and layout")
    return tables


def make_dot(tables: dict[str, list[Column]], digest: str) -> str:
    references = sum(bool(column.reference) for columns in tables.values() for column in columns)
    lines = [
        "digraph model {",
        'graph [rankdir=LR, bgcolor="#ffffff", pad="0.4", nodesep="0.55", ranksep="0.85",',
        '  splines=spline, outputorder=edgesfirst, fontname="Arial", fontsize=24,',
        '  fontcolor="#18232c", labelloc=t, labeljust=l,',
        f'  label="Capibara · Модель данных\\n\\ncore · {len(tables)} таблиц · {references} внешних ключей\\n"];',
        'node [shape=plain, fontname="Arial", fontsize=13];',
        'edge [color="#72808b", penwidth=1.2, arrowsize=0.7, dir=both,',
        '  arrowtail=teetee, arrowhead=crowodot, fontname="Arial", fontsize=11,',
        '  fontcolor="#364954", labeldistance=1.8];',
    ]
    for name, columns in tables.items():
        title, grain = CAPTIONS[name]
        rows = [
            '<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="7" COLOR="#c6ced4" BGCOLOR="#ffffff">',
            f'<TR><TD COLSPAN="3" ALIGN="LEFT" BGCOLOR="#eaf0f2"><FONT POINT-SIZE="15"><B>core.{name}</B></FONT></TD></TR>',
            f'<TR><TD COLSPAN="3" ALIGN="LEFT"><FONT POINT-SIZE="12">{title} · {grain}</FONT></TD></TR>',
            '<HR/>',
        ]
        for column in columns:
            badge = ", ".join(tag for tag, active in (("PK", column.primary), ("FK", column.reference)) if active) or "&#160;"
            field = escape(column.name) + (" *" if column.required else "")
            rows.append(
                f'<TR><TD PORT="in_{column.name}" ALIGN="LEFT"><FONT COLOR="#21695e"><B>{badge}</B></FONT></TD>'
                f'<TD ALIGN="LEFT">{field}</TD>'
                f'<TD PORT="out_{column.name}" ALIGN="LEFT"><FONT COLOR="#5a6670">{column.kind}</FONT></TD></TR>'
            )
        rows.append("</TABLE>")
        lines.append(f'{name} [label=<{"".join(rows)}>];')
    for name, columns in tables.items():
        for column in columns:
            if not column.reference:
                continue
            parent = tables[column.reference]
            keys = [key.name for key in parent if key.primary]
            if len(keys) != 1:
                raise ValueError("Implicit reference requires a single parent primary key")
            tooltip = escape(f"{name}.{column.name} → {column.reference}.{keys[0]}", quote=True)
            minimum = "1" if column.required else "0..1"
            tail = "teetee" if column.required else "teeodot"
            lines.append(
                f'{column.reference}:out_{keys[0]}:e -> {name}:in_{column.name}:w '
                f'[arrowtail={tail}, taillabel="{minimum}", headlabel="0..N", tooltip="{tooltip}"];'
            )
    lines += [
        '{rank=same; buyers; categories; order_statuses; sellers;}',
        '{rank=same; customer_profiles; products;}',
        '{rank=same; orders;}',
        '{rank=same; order_items; order_payments; order_reviews;}',
        'legend [shape=plain, label=<<TABLE BORDER="0" CELLBORDER="0" CELLPADDING="5">',
        '<TR><TD ALIGN="LEFT"><B>Как читать схему</B></TD></TR>',
        '<TR><TD ALIGN="LEFT">PK — первичный ключ · FK — внешний ключ · * — NOT NULL</TD></TR>',
        '<TR><TD ALIGN="LEFT">1 → 0..N: каждой дочерней строке соответствует один родитель;</TD></TR>',
        '<TR><TD ALIGN="LEFT">у родителя может не быть дочерних строк. Пара PK — составной ключ.</TD></TR>',
        f'<TR><TD ALIGN="LEFT"><FONT COLOR="#5a6670">Источник: model/schema.sql · SHA-256: {digest[:12]}</FONT></TD></TR>',
        '</TABLE>>];',
        '{rank=same; orders; legend;}',
        'orders -> legend [style=invis];',
        "}",
    ]
    return "\n".join(lines)


def main() -> None:
    dot = shutil.which("dot")
    if not dot:
        raise SystemExit("Для генерации диаграммы установите Graphviz (команда dot).")
    raw = SCHEMA.read_bytes()
    tables = read_schema(raw.decode("utf-8"))
    source = make_dot(tables, sha256(raw).hexdigest()).encode("utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for kind in ("svg", "png"):
        destination = OUTPUT / f"model.{kind}"
        subprocess.run([dot, f"-T{kind}", "-Gdpi=120", "-o", str(destination)],
                       input=source, check=True)
        print(destination.relative_to(ROOT))
    references = sum(bool(column.reference) for columns in tables.values() for column in columns)
    print(f"{len(tables)} tables, {sum(map(len, tables.values()))} columns, {references} foreign keys")


if __name__ == "__main__":
    main()
