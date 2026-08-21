"""
Отдельный скрипт для просчёта цены конкретной панели/двери MACKO.

Значения по умолчанию соответствуют конфигурации из
MACKO_ZZF5.MBMM.AH4_J-0000.0o.pdf (код ZZF5MBMMAH4J00000o, модель L00,
цена 37526 UAH) - проверено вживую через API, код и цена совпадают с PDF
один в один. Любой параметр можно переопределить флагом, чтобы посчитать
другой вариант той же двери (другой цвет/материал панели, другую
конструкцию, другое стекло и т.д.) - непереопределённые параметры остаются
как в PDF.

Примеры:
    # просто перепроверить цену из PDF
    python panel_price.py

    # та же дверь, но с другим цветом панели снаружи
    python panel_price.py --colour-outside 22 --currency UAH

    # полностью другая конфигурация - любой параметр можно задать явно
    python panel_price.py --model 8 --colour-outside 25 --colour-inside 25
        --glass 2 --furniture 1 --options 0 --inox 4 --view 4 --mirrored 1 --safeglass 1
"""
from __future__ import annotations

import argparse
import json
import sys

from mackodoor_client import MackodoorClient, MackodoorAPIError
from panel_defaults import PDF_DEFAULTS

DEFAULT_BASE_URL = "https://app.macko.com.ua/api1"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Просчёт цены двери/панели MACKO. По умолчанию воспроизводит "
            "конфигурацию из MACKO_ZZF5.MBMM.AH4_J-0000.0o.pdf "
            "(код ZZF5MBMMAH4J00000o, 37526 UAH) - переопределяйте только то, "
            "что хотите изменить."
        ),
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--shape", default=PDF_DEFAULTS["shape"], help="Ид формы двери")
    p.add_argument("--model", default=PDF_DEFAULTS["model"], help="Ид модели двери")
    p.add_argument("--colour-outside", default=PDF_DEFAULTS["colour_outside"],
                    help="Ид цвета/материала панели снаружи")
    p.add_argument("--colour-inside", default=PDF_DEFAULTS["colour_inside"],
                    help="Ид цвета/материала панели изнутри")
    p.add_argument("--glass", default=PDF_DEFAULTS["glass"], help="Ид стекла")
    p.add_argument("--furniture", default=PDF_DEFAULTS["furniture"], help="Ид фурнитуры (ручка снаружи)")
    p.add_argument("--options", default=PDF_DEFAULTS["options"],
                    help="Ид конструкции/товщини двері (через запятую, если несколько)")
    p.add_argument("--inox", default=PDF_DEFAULTS["inox"], help="Ид inox/декора")
    p.add_argument("--view", default=PDF_DEFAULTS["view"], help="Ид открывания")
    p.add_argument("--mirrored", default=PDF_DEFAULTS["mirrored"], help="Ид вида (стандарт/зеркальная)")
    p.add_argument("--safeglass", default=PDF_DEFAULTS["safeglass"], help="Ид типа безопасного стекла")
    p.add_argument("--black", help="Чёрный дизайн: 1 или 0 (в PDF не задан)")
    p.add_argument("--color-outside-is3", dest="color_outside_is3", help="Алюминий 3мм снаружи: 1 или 0")
    p.add_argument("--color-inside-is3", dest="color_inside_is3", help="Алюминий 3мм внутри: 1 или 0")
    p.add_argument("--currency", default="UAH", help="Код валюты, например UAH или USD")
    p.add_argument("--active-check", action="store_true",
                    help="Считать ошибкой, если в конфигурации есть неактивный элемент")
    p.add_argument("--out", help="Сохранить код + полный JSON-ответ цены в файл")
    p.add_argument(
        "--price-only", action="store_true",
        help="Вывести в stdout только число цены (без текста) - удобно для вызова из другой программы",
    )
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    client = MackodoorClient(base_url=args.base_url)

    config = {
        "shape": args.shape, "model": args.model,
        "colour_outside": args.colour_outside, "colour_inside": args.colour_inside,
        "glass": args.glass, "furniture": args.furniture, "options": args.options,
        "inox": args.inox, "view": args.view, "mirrored": args.mirrored, "safeglass": args.safeglass,
        "black": args.black,
        "color_outside_is3": args.color_outside_is3, "color_inside_is3": args.color_inside_is3,
    }

    try:
        code = client.encode_code(**config)
        result = client.get_price(currency_name=args.currency, active=args.active_check, **config)
    except MackodoorAPIError as e:
        print(f"Ошибка API: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(result, dict) or "price" not in result:
        print(
            "Не удалось получить цену: API вернул неожиданный ответ "
            f"({result!r}). Обычно это значит, что один из переданных id "
            "не существует (например несуществующий model/glass/inox и т.п.). "
            "Проверьте id командой `python calculate_hpl.py list <ресурс>`.",
            file=sys.stderr,
        )
        sys.exit(1)

    price = result.get("price")

    if args.price_only:
        # Только число в stdout, ничего лишнего - удобно парсить из другой программы.
        print(price)
    else:
        print(f"Код: {code}")
        print(f"Ссылка: https://app.macko.com.ua/#/?code={code}")
        print(f"Цена: {price} {args.currency}")
        for m in result.get("messages") or []:
            print(f"Сообщение API: {m}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"code": code, **result}, f, ensure_ascii=False, indent=2)
        print(f"Сохранено в {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
