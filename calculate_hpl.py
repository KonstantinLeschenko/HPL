"""
Программа для просчёта цены HPL-панелей дверей через API Mackodoor v2
(https://app.macko.com.ua/api1/swagger/).

В API нет отдельной сущности "HPL-панель" - HPL это материал цвета панели
двери (поле is_hpl у /color/). Расчёт цены и справочники теперь публичные
(токен не нужен); Bearer-токен требуется только для оформления заказа,
"моих дверей" и данных пользователя.

Если элемент конфигурации не передан явно, API сам подставляет стандартное
значение сайта - поэтому для расчёта достаточно указать только то, что
отличается от стандартной двери (например только цвет HPL-панели).

Быстрый старт:
    pip install -r requirements.txt

    python calculate_hpl.py list colors --hpl-only
    python calculate_hpl.py price --colour-outside 22 --currency UAH
    python calculate_hpl.py hpl-report --currency UAH --out hpl_prices.csv
    python calculate_hpl.py batch --input orders.csv --output results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Optional

from mackodoor_client import MackodoorClient, MackodoorAPIError

DEFAULT_BASE_URL = "https://app.macko.com.ua/api1"

CONFIG_FIELDS = [
    "shape", "model", "colour_outside", "colour_inside", "glass", "furniture",
    "options", "inox", "view", "mirrored", "safeglass", "black",
    "colorOutsideIs3", "colorInsideIs3", "currency_name",
]


# --------------------------------------------------------------------------
# вспомогательные функции
# --------------------------------------------------------------------------

def get_client(args) -> MackodoorClient:
    client = MackodoorClient(base_url=args.base_url)
    token = getattr(args, "token", None) or os.environ.get("MACKO_TOKEN")
    if token:
        client.token = token
        return client
    email = getattr(args, "email", None) or os.environ.get("MACKO_EMAIL")
    password = getattr(args, "password", None) or os.environ.get("MACKO_PASSWORD")
    if email and password:
        client.login(email, password)
    return client  # для списков/цены токен не обязателен


def require_auth_client(args) -> MackodoorClient:
    client = get_client(args)
    if not client.token:
        raise SystemExit(
            "Эта команда требует авторизации: укажите --token/MACKO_TOKEN "
            "или --email/--password (MACKO_EMAIL/MACKO_PASSWORD)."
        )
    return client


def print_table(rows: list, columns: list):
    if not rows:
        print("(пусто)")
        return
    widths = [max(len(str(c)), *(len(str(r.get(c, ""))) for r in rows)) for c in columns]
    header = "  ".join(c.ljust(w) for c, w in zip(columns, widths))
    print(header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w) for c, w in zip(columns, widths)))


def config_kwargs_from_args(args) -> dict:
    return {
        "shape": args.shape, "model": args.model,
        "colour_outside": args.colour_outside, "colour_inside": args.colour_inside,
        "glass": args.glass, "furniture": args.furniture,
        "options": args.options, "inox": args.inox, "view": args.view,
        "mirrored": args.mirrored, "safeglass": args.safeglass, "black": args.black,
        "color_outside_is3": args.color_outside_is3, "color_inside_is3": args.color_inside_is3,
    }


def extract_price_result(result):
    """Вернуть (price, messages, error) из ответа /price/.

    API иногда возвращает пустой список [] вместо объекта {"price":...},
    если один из переданных id не существует/недопустим для этой комбинации
    (например несуществующий model) - без этой проверки код падал с
    AttributeError на result.get(...).
    """
    if isinstance(result, dict) and "price" in result:
        return result.get("price"), result.get("messages") or [], None
    return None, [], f"Неожиданный ответ API: {result!r} (проверьте, что все id существуют)"


def add_config_args(p: argparse.ArgumentParser):
    p.add_argument("--shape", help="Ид формы двери")
    p.add_argument("--model", help="Ид модели двери")
    p.add_argument("--colour-outside", help="Ид цвета снаружи (сюда подставляется HPL-цвет)")
    p.add_argument("--colour-inside", help="Ид цвета изнутри")
    p.add_argument("--glass", help="Ид стекла")
    p.add_argument("--furniture", help="Ид фурнитуры (ручки)")
    p.add_argument("--options", help="Ид опций через запятую")
    p.add_argument("--inox", help="Ид inox")
    p.add_argument("--view", help="Ид открывания")
    p.add_argument("--mirrored", help="Ид вида модели (стандарт/зеркальная)")
    p.add_argument("--safeglass", help="Ид типа безопасного стекла")
    p.add_argument("--black", help="Чёрный дизайн: 1 или 0")
    p.add_argument("--color-outside-is3", dest="color_outside_is3", help="Алюминий 3мм снаружи: 1 или 0")
    p.add_argument("--color-inside-is3", dest="color_inside_is3", help="Алюминий 3мм внутри: 1 или 0")


# --------------------------------------------------------------------------
# подкоманды
# --------------------------------------------------------------------------

def cmd_list(args):
    client = get_client(args)
    resource = args.resource

    if resource == "colors":
        data = client.get_colors(active=args.active, category=[args.category] if args.category else None)
        if args.hpl_only:
            data = [c for c in data if str(c.get("is_hpl")) == "1"]
        rows = [
            {"id": c.get("id"), "title": c.get("title"), "colour_name": c.get("colour_name"),
             "is_hpl": c.get("is_hpl"), "is_alu": c.get("is_alu"), "active": c.get("active")}
            for c in data
        ]
        columns = ["id", "title", "colour_name", "is_hpl", "is_alu", "active"]
    elif resource == "models":
        # без --series API и так возвращает все модели по всем сериям
        data = client.get_models(series=[args.series] if args.series else None, active=args.active)
        series_map = {s["id"]: s.get("url", s.get("title")) for s in client.get_model_series()}
        rows = [{"id": m.get("id"), "title": m.get("title"),
                 "series": series_map.get(m.get("series"), m.get("series")),
                 "active": m.get("active")} for m in data]
        columns = ["id", "title", "series", "active"]
    elif resource == "shapes":
        data = client.get_shapes(active=args.active)
        rows = [{"id": s.get("id"), "title": s.get("title"), "active": s.get("active")} for s in data]
        columns = ["id", "title", "active"]
    elif resource == "glass":
        data = client.get_glass(active=args.active)
        rows = [{"id": g.get("id"), "title": g.get("title"), "price": g.get("price")} for g in data]
        columns = ["id", "title", "price"]
    elif resource == "furniture":
        categories = client.get_furniture(active=args.active)
        rows = []
        for cat in categories:
            for item in cat.get("items", []) or []:
                rows.append({"id": item.get("id"), "title": item.get("title"), "category": cat.get("title")})
        columns = ["id", "title", "category"]
    elif resource == "molding":
        data = client.get_molding(active=args.active)
        rows = [{"id": m.get("id"), "title": m.get("title"), "price": m.get("price")} for m in data]
        columns = ["id", "title", "price"]
    elif resource == "inox":
        data = client.get_inox(active=args.active)
        rows = [{"id": i.get("id"), "title": i.get("title"), "inox_type": i.get("inox_type")} for i in data]
        columns = ["id", "title", "inox_type"]
    elif resource == "view":
        data = client.get_view(active=args.active)
        rows = [{"id": v.get("id"), "title": v.get("title"), "view_type": v.get("view_type")} for v in data]
        columns = ["id", "title", "view_type"]
    elif resource == "mirrored":
        data = client.get_mirrored(active=args.active)
        rows = [{"id": m.get("id"), "title": m.get("title"), "mirrored_type": m.get("mirrored_type")} for m in data]
        columns = ["id", "title", "mirrored_type"]
    elif resource == "safeglass":
        data = client.get_safeglass(active=args.active)
        rows = [{"id": s.get("id"), "title": s.get("title"), "safeglass_type": s.get("safeglass_type")} for s in data]
        columns = ["id", "title", "safeglass_type"]
    elif resource == "currencies":
        data = client.get_currencies()
        rows = [{"name": c.get("name"), "symbol": c.get("symbol")} for c in data]
        columns = ["name", "symbol"]
    else:
        raise SystemExit(f"Неизвестный ресурс: {resource}")

    print_table(rows, columns)

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nСохранено в {args.out} ({len(rows)} строк)", file=sys.stderr)


def cmd_defaults(args):
    client = get_client(args)
    d = client.get_default()
    rows = [
        {"поле": "shape", "id": d.get("shape", {}).get("id"), "title": d.get("shape", {}).get("title")},
        {"поле": "model", "id": d.get("model", {}).get("id"), "title": d.get("model", {}).get("title")},
        {"поле": "colour_outside", "id": d.get("color", {}).get("outside", {}).get("id"),
         "title": d.get("color", {}).get("outside", {}).get("title")},
        {"поле": "colour_inside", "id": d.get("color", {}).get("inside", {}).get("id"),
         "title": d.get("color", {}).get("inside", {}).get("title")},
        {"поле": "glass", "id": d.get("glass", {}).get("id"), "title": d.get("glass", {}).get("title")},
        {"поле": "furniture", "id": d.get("furniture", {}).get("id"), "title": d.get("furniture", {}).get("title")},
        {"поле": "inox", "id": d.get("inox", {}).get("id"), "title": d.get("inox", {}).get("title")},
        {"поле": "view", "id": d.get("view", {}).get("id"), "title": d.get("view", {}).get("title")},
        {"поле": "mirrored", "id": d.get("mirrored", {}).get("id"), "title": d.get("mirrored", {}).get("title")},
        {"поле": "safeglass", "id": d.get("safeglass", {}).get("id"), "title": d.get("safeglass", {}).get("title")},
    ]
    print_table(rows, ["поле", "id", "title"])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        print(f"\nПолный ответ /default/ сохранён в {args.out}", file=sys.stderr)


def cmd_price(args):
    client = get_client(args)
    if args.code:
        result = client.get_price(code=args.code, currency_name=args.currency, active=args.active_check)
        code = args.code
    else:
        config = config_kwargs_from_args(args)
        result = client.get_price(currency_name=args.currency, active=args.active_check, **config)
        code = client.encode_code(**config)

    price, messages, error = extract_price_result(result)
    print(f"Код: {code}")
    if error:
        print(error, file=sys.stderr)
        sys.exit(1)
    print(f"Цена: {price} {args.currency or ''}".strip())
    if messages:
        print("Сообщения API:")
        for m in messages:
            print(f"  - {m}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"code": code, "price": price, "messages": messages}, f, ensure_ascii=False, indent=2)
        print(f"\nПолный ответ сохранён в {args.out}", file=sys.stderr)


def cmd_hpl_report(args):
    """Посчитать цену для каждого доступного цвета HPL-панели (снаружи)."""
    client = get_client(args)
    colors = client.get_colors(active=True)
    hpl_colors = [c for c in colors if str(c.get("is_hpl")) == "1"]
    if not hpl_colors:
        raise SystemExit("Не найдено ни одного цвета с is_hpl=1.")

    base = config_kwargs_from_args(args)
    rows = []
    for c in hpl_colors:
        cfg = dict(base)
        cfg["colour_outside"] = c["id"]
        if args.both_sides:
            cfg["colour_inside"] = c["id"]
        try:
            result = client.get_price(currency_name=args.currency, **cfg)
            price, msgs, error = extract_price_result(result)
            messages = error if error else "; ".join(msgs)
        except MackodoorAPIError as e:
            price = None
            messages = e.message
        rows.append({
            "id": c.get("id"), "title": c.get("title"), "colour_name": c.get("colour_name"),
            "price": price, "messages": messages,
        })
        print(f"[{c.get('id')}] {c.get('title')} ({c.get('colour_name')}) -> {price}")

    priced = [r for r in rows if r["price"] is not None]
    priced.sort(key=lambda r: r["price"])
    unpriced = [r for r in rows if r["price"] is None]

    print()
    print_table(priced + unpriced, ["id", "title", "colour_name", "price", "messages"])

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "title", "colour_name", "price", "messages"])
            writer.writeheader()
            writer.writerows(priced + unpriced)
        print(f"\nРезультаты сохранены в {args.out}", file=sys.stderr)


def cmd_batch(args):
    client = get_client(args)

    with open(args.input, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        input_rows = list(reader)

    fieldnames = list(reader.fieldnames or []) + ["code", "price", "messages", "error"]
    results = []

    for i, row in enumerate(input_rows, start=1):
        cfg = {
            "shape": row.get("shape") or args.shape,
            "model": row.get("model") or args.model,
            "colour_outside": row.get("colour_outside") or args.colour_outside,
            "colour_inside": row.get("colour_inside") or args.colour_inside,
            "glass": row.get("glass") or args.glass,
            "furniture": row.get("furniture") or args.furniture,
            "options": row.get("options") or args.options,
            "inox": row.get("inox") or args.inox,
            "view": row.get("view") or args.view,
            "mirrored": row.get("mirrored") or args.mirrored,
            "safeglass": row.get("safeglass") or args.safeglass,
            "black": row.get("black") or args.black,
            "color_outside_is3": row.get("colorOutsideIs3") or args.color_outside_is3,
            "color_inside_is3": row.get("colorInsideIs3") or args.color_inside_is3,
        }
        currency = row.get("currency_name") or args.currency
        out_row = dict(row)
        try:
            code = client.encode_code(**cfg)
            result = client.get_price(currency_name=currency, **cfg)
            price, msgs, error = extract_price_result(result)
            out_row["code"] = code
            out_row["price"] = price if price is not None else ""
            out_row["messages"] = "; ".join(msgs)
            out_row["error"] = error or ""
        except MackodoorAPIError as e:
            out_row["code"] = ""
            out_row["price"] = ""
            out_row["messages"] = ""
            out_row["error"] = e.message
        print(f"[{i}/{len(input_rows)}] {out_row.get('code') or '(ошибка)'} -> {out_row['price']}")
        results.append(out_row)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nГотово. Результаты записаны в {args.output}")


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description="Просчёт цены HPL-панелей дверей через API Mackodoor.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", help="JWT токен (или переменная окружения MACKO_TOKEN)")
    parser.add_argument("--email", help="Email (или переменная окружения MACKO_EMAIL) — только для заказов/личного кабинета")
    parser.add_argument("--password", help="Пароль (или переменная окружения MACKO_PASSWORD)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Показать справочные списки (цвета, модели, стёкла и т.д.)")
    p_list.add_argument("resource", choices=[
        "colors", "models", "shapes", "glass", "furniture", "molding",
        "inox", "view", "mirrored", "safeglass", "currencies",
    ])
    p_list.add_argument("--hpl-only", action="store_true", help="Только цвета с материалом HPL (is_hpl=1)")
    p_list.add_argument("--category", choices=["color", "laminat", "aluminum"])
    p_list.add_argument("--series", choices=["base", "vertical", "horizontal", "square", "radius", "line", "klasika"])
    p_list.add_argument("--active", action="store_true", help="Только активные элементы")
    p_list.add_argument("--out", help="Сохранить результат в CSV")
    p_list.set_defaults(func=cmd_list)

    p_def = sub.add_parser("defaults", help="Показать стандартную конфигурацию двери сайта (/default/)")
    p_def.add_argument("--out", help="Сохранить полный JSON-ответ в файл")
    p_def.set_defaults(func=cmd_defaults)

    p_price = sub.add_parser("price", help="Посчитать цену одной конфигурации (не указанные поля берутся стандартные)")
    add_config_args(p_price)
    p_price.add_argument("--code", help="Готовый код конфигурации (пропускает остальные --поля)")
    p_price.add_argument("--currency", help="Код валюты, например UAH")
    p_price.add_argument("--active-check", action="store_true", help="Ошибка, если в конфигурации есть неактивный элемент")
    p_price.add_argument("--out", help="Сохранить полный JSON-ответ в файл")
    p_price.set_defaults(func=cmd_price)

    p_report = sub.add_parser("hpl-report", help="Посчитать цену для каждого доступного цвета HPL-панели")
    add_config_args(p_report)
    p_report.add_argument("--currency", help="Код валюты, например UAH")
    p_report.add_argument("--both-sides", action="store_true", help="Также ставить этот HPL-цвет изнутри (не только снаружи)")
    p_report.add_argument("--out", help="Сохранить результаты в CSV")
    p_report.set_defaults(func=cmd_hpl_report)

    p_batch = sub.add_parser("batch", help="Посчитать цены пачкой конфигураций из CSV")
    p_batch.add_argument("--input", required=True,
                          help="Входной CSV, колонки: " + ", ".join(CONFIG_FIELDS))
    p_batch.add_argument("--output", required=True, help="Выходной CSV с ценами")
    add_config_args(p_batch)
    p_batch.add_argument("--currency", help="Валюта по умолчанию, если нет колонки currency_name")
    p_batch.set_defaults(func=cmd_batch)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except MackodoorAPIError as e:
        print(f"Ошибка API: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
