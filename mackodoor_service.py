"""
HTTP-сервис для просчёта цены дверей/HPL-панелей MACKO.

Оборачивает https://app.macko.com.ua/api1/ (см. mackodoor_client.py) и
отдаёт результат простым HTTP-ответом (JSON или голое число text/plain).
Нужен для того, чтобы внешние приложения (например Delphi-приложение,
которое ставится на разные компьютеры пользователей) могли получать цену
обычным HTTP-запросом, не имея на своей машине ни Python, ни этих скриптов -
Python нужен только там, где запущен сам сервис.

Запуск для разработки:
    pip install -r requirements.txt
    python mackodoor_service.py
    (сервис слушает http://127.0.0.1:5000/)

Запуск как "продакшн"-сервис на Windows (без окна dev-сервера Flask,
можно оставить работать в фоне/как задачу планировщика или Windows-службу
через NSSM):
    waitress-serve --host=0.0.0.0 --port=5000 mackodoor_service:app

Эндпоинты:
    GET /health
        -> {"status": "ok"}

    GET /price?colour_outside=22&currency=UAH&...
        Любой из параметров shape, model, colour_outside, colour_inside,
        glass, furniture, options, inox, view, mirrored, safeglass, black,
        colorOutsideIs3, colorInsideIs3, currency - необязателен: то, что не
        передано, берётся из конфигурации PDF (см. panel_defaults.py).
        -> 200 {"price": 37526, "currency": "UAH", "code": "...",
                "link": "https://app.macko.com.ua/#/?code=...", "messages": []}
        -> 400/502 {"error": "..."}

    GET /price/text?colour_outside=22&currency=UAH
        Та же логика, но в ответе только число цены (Content-Type: text/plain),
        либо текст ошибки с кодом 400/502 - удобнее всего вызывать из Delphi.

    GET /defaults
        -> базовая конфигурация (из PDF), которая подставляется вместо
           непереданных параметров.

    GET /hpl-colors
        -> [{"id": "22", "title": "HPL", "colour_name": "..."}, ...]
           список всех активных цветов с материалом HPL (is_hpl=1).

    GET /api/<resource> - справочники для выпадающих списков в UI (index.html):
        models, shapes, colors, glass, furniture, construction, inox, view,
        mirrored, safeglass -> [{"id": "...", "title": "..."}, ...]

    GET / - простая HTML-страница с формой выбора параметров и результатом
        (цена + ссылка на КП).
"""
from __future__ import annotations

import os

from flask import Flask, Response, jsonify, request, send_from_directory

from mackodoor_client import MackodoorAPIError, MackodoorClient
from panel_defaults import PDF_DEFAULTS

app = Flask(__name__)
client = MackodoorClient()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PARAMS = [
    "shape", "model", "colour_outside", "colour_inside", "glass", "furniture",
    "options", "inox", "view", "mirrored", "safeglass", "black",
]


def _config_from_request() -> dict:
    cfg = {}
    for key in CONFIG_PARAMS:
        value = request.args.get(key)
        cfg[key] = value if value not in (None, "") else PDF_DEFAULTS.get(key)
    cfg["color_outside_is3"] = request.args.get("colorOutsideIs3") or None
    cfg["color_inside_is3"] = request.args.get("colorInsideIs3") or None
    return cfg


def _compute_price():
    """Общая логика для /price и /price/text. Возвращает (http_status, payload)."""
    config = _config_from_request()
    currency = request.args.get("currency", "UAH")
    active_check = request.args.get("active_check") in ("1", "true", "True")

    try:
        code = client.encode_code(**config)
        result = client.get_price(currency_name=currency, active=active_check, **config)
    except MackodoorAPIError as e:
        return 502, {"error": f"Ошибка API Mackodoor: {e.message}"}
    except Exception as e:  # сеть недоступна, таймаут и т.п.
        return 502, {"error": f"Не удалось обратиться к API Mackodoor: {e}"}

    if not isinstance(result, dict) or "price" not in result:
        return 400, {
            "error": "API вернул неожиданный ответ - проверьте, что все id "
                     "существуют (см. GET /hpl-colors, GET /defaults).",
            "raw": result,
        }

    return 200, {
        "price": result.get("price"),
        "currency": currency,
        "code": code,
        "link": f"https://app.macko.com.ua/#/?code={code}",
        "messages": result.get("messages") or [],
    }


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/defaults")
def defaults():
    return jsonify(PDF_DEFAULTS)


@app.get("/hpl-colors")
def hpl_colors():
    try:
        colors = client.get_colors(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    hpl = [
        {"id": c.get("id"), "title": c.get("title"), "colour_name": c.get("colour_name")}
        for c in colors if str(c.get("is_hpl")) == "1"
    ]
    return jsonify(hpl)


@app.get("/price")
def price_json():
    status, payload = _compute_price()
    return jsonify(payload), status


@app.get("/price/text")
def price_text():
    status, payload = _compute_price()
    if status != 200:
        return Response(payload.get("error", "error"), status=status, mimetype="text/plain; charset=utf-8")
    return Response(str(payload["price"]), status=200, mimetype="text/plain; charset=utf-8")


# -- справочники для выпадающих списков в UI --------------------------------

# Картинки в API отдаются относительными путями вида "/uploads/..." -
# реально лежат на этом же хосте, без /api1.
IMAGE_BASE = "https://app.macko.com.ua"


def _image_url(path):
    return f"{IMAGE_BASE}{path}" if path else None


def _rows(items, *, id_key="id", title_key="title", extra=None, image_key=None):
    extra = extra or {}
    out = []
    for it in items:
        row = {"id": it.get(id_key), "title": it.get(title_key)}
        for out_key, src_key in extra.items():
            row[out_key] = it.get(src_key)
        if image_key:
            row["image"] = _image_url(it.get(image_key))
        out.append(row)
    return out


@app.get("/api/models")
def api_models():
    try:
        data = client.get_models(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    return jsonify(_rows(data, image_key="image_svg"))


@app.get("/api/shapes")
def api_shapes():
    try:
        data = client.get_shapes(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    return jsonify(_rows(data, image_key="image_svg"))


@app.get("/api/colors")
def api_colors():
    try:
        data = client.get_colors(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    rows = []
    for c in data:
        # у HPL/ламинированных цветов обычно есть фото текстуры (pattern_image),
        # у однотонных - только hex-код (colour) - используем его как заливку.
        pattern = c.get("pattern_image") or c.get("pattern_svg")
        rows.append({
            "id": c.get("id"),
            "title": c.get("title"),
            "colour_name": c.get("colour_name"),
            "is_hpl": c.get("is_hpl"),
            "colour": c.get("colour") or None,
            "image": _image_url(pattern),
        })
    return jsonify(rows)


@app.get("/api/glass")
def api_glass():
    try:
        data = client.get_glass(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    return jsonify(_rows(data))


@app.get("/api/furniture")
def api_furniture():
    try:
        categories = client.get_furniture(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    rows = []
    for cat in categories:
        for item in cat.get("items", []) or []:
            rows.append({"id": item.get("id"), "title": item.get("title")})
    return jsonify(rows)


@app.get("/api/construction")
def api_construction():
    """Плоский список конструкций/товщин двери - это то, что уходит в параметр
    `options` у /code/ и /price/ (id самой товщини, не категории конструкции)."""
    try:
        groups = client.get_options()
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    rows = []
    for group in groups:
        for item in group.get("construction_thikness", []) or []:
            thickness = item.get("construction_thikness")
            price = item.get("price")
            title = item.get("title", "").strip()
            # у части позиций толщина уже есть в самом title - не дублируем
            if thickness and f"{thickness} мм" not in title:
                label = f"{title} - {thickness} мм"
            else:
                label = title
            if price and price != "0":
                label += f" ({price})"
            rows.append({
                "id": item.get("id"), "title": label,
                "image": _image_url(item.get("image_png")),
            })
    return jsonify(rows)


@app.get("/api/inox")
def api_inox():
    try:
        data = client.get_inox(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    return jsonify(_rows(data))


@app.get("/api/view")
def api_view():
    try:
        data = client.get_view(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    return jsonify(_rows(data))


@app.get("/api/mirrored")
def api_mirrored():
    try:
        data = client.get_mirrored(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    return jsonify(_rows(data))


@app.get("/api/safeglass")
def api_safeglass():
    try:
        data = client.get_safeglass(active=True)
    except MackodoorAPIError as e:
        return jsonify({"error": e.message}), 502
    return jsonify(_rows(data))


# -- UI -----------------------------------------------------------------

@app.get("/")
def ui():
    return send_from_directory(BASE_DIR, "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
