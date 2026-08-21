"""
Клиент для API Mackodoor v2: https://app.macko.com.ua/api1/swagger/

Большинство справочных и ценовых эндпоинтов теперь публичные (не требуют
токена). Bearer-токен нужен только для /order/, /doors/, /userinfo/, /question/.
"""
from __future__ import annotations

import requests
from typing import Any, Iterable, Optional


class MackodoorAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str, payload: Any = None):
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload


def _active_param(active: Optional[bool], true_value: str = "true"):
    return true_value if active else None


class MackodoorClient:
    def __init__(
        self,
        base_url: str = "https://app.macko.com.ua/api1",
        token: Optional[str] = None,
        auth_scheme: str = "Bearer",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.auth_scheme = auth_scheme
        self.timeout = timeout
        self.session = requests.Session()

    # -- internals ---------------------------------------------------
    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"{self.auth_scheme} {self.token}".strip()
        return headers

    def _request(self, method: str, path: str, *, params: dict = None, json_body: dict = None):
        url = f"{self.base_url}{path}"
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        resp = self.session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            try:
                data = resp.json()
                message = data.get("message") or "; ".join(data.get("errors", [])) or resp.text
            except ValueError:
                data = resp.text
                message = resp.text
            raise MackodoorAPIError(resp.status_code, message, data)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def _get(self, path: str, params: dict = None):
        return self._request("GET", path, params=params)

    def _post(self, path: str, json_body: dict = None):
        return self._request("POST", path, json_body=json_body)

    # -- auth (нужен только для /order/, /doors/, /userinfo/, /question/) --
    def login(self, email: str, password: str) -> dict:
        data = self._post("/login/", {"email": email, "password": password})
        if isinstance(data, dict) and data.get("jwt"):
            self.token = data["jwt"]
        return data

    def register(self, email: str, password: str) -> dict:
        return self._post("/register/", {"email": email, "password": password})

    # -- справочники ----------------------------------------------------
    def get_shapes(self, active: Optional[bool] = None):
        return self._get("/shape/", {"active": _active_param(active)})

    def get_models(self, series: Optional[Iterable[str]] = None, active: Optional[bool] = None):
        params = {"active": _active_param(active)}
        if series is not None:
            params["series"] = list(series)
        return self._get("/models/", params)

    def get_model_series(self):
        return self._get("/modelseries/")

    def get_colors(self, active: Optional[bool] = None, category: Optional[Iterable[str]] = None):
        params = {"active": _active_param(active)}
        if category is not None:
            params["category"] = list(category)
        return self._get("/color/", params)

    def get_glass(self, active: Optional[bool] = None, model: Optional[str] = None, shape: Optional[str] = None):
        return self._get("/glass/", {"active": _active_param(active), "model": model, "shape": shape})

    def get_furniture(self, active: Optional[bool] = None, model: Optional[str] = None):
        """Возвращает furniture_categories (категории с вложенными items), например ручки."""
        return self._get("/furniture/", {"active": _active_param(active), "model": model})

    def get_options(self):
        return self._get("/options/")

    def get_molding(self, active: Optional[bool] = None, id: Optional[int] = None):
        return self._get("/molding/", {"active": "1" if active else None, "id": id})

    def get_inox(self, active: Optional[bool] = None, model: Optional[str] = None):
        return self._get("/inox/", {"active": _active_param(active), "model": model})

    def get_view(self, active: Optional[bool] = None, model: Optional[str] = None):
        return self._get("/view/", {"active": _active_param(active), "model": model})

    def get_mirrored(self, active: Optional[bool] = None, model: Optional[str] = None):
        return self._get("/mirrored/", {"active": _active_param(active), "model": model})

    def get_safeglass(self, active: Optional[bool] = None, glass_id: Optional[str] = None):
        return self._get("/safeglass/", {"active": _active_param(active), "glass_id": glass_id})

    def get_currencies(self):
        return self._get("/currencies/")

    def get_banner(self, active: Optional[bool] = None):
        return self._get("/banner/", {"active": _active_param(active)})

    def get_news(self):
        return self._get("/news/")

    def get_default(self):
        return self._get("/default/")

    # -- конфигурация / цена ------------------------------------------
    # Общие поля запроса для /code/, /price/, /isactive/, /pdf/:
    #   shape, model, colour_outside, colour_inside, glass, furniture,
    #   options (id через запятую), inox, view, mirrored, safeglass, black,
    #   colorOutsideIs3, colorInsideIs3
    # Если поле не передано - API подставляет стандартное значение сайта.

    @staticmethod
    def _config_params(
        shape=None, model=None, colour_outside=None, colour_inside=None,
        glass=None, furniture=None, options=None, inox=None, view=None,
        mirrored=None, safeglass=None, black=None,
        color_outside_is3=None, color_inside_is3=None,
    ) -> dict:
        if options is not None and not isinstance(options, str):
            options = ",".join(str(o) for o in options)
        return {
            "shape": shape, "model": model,
            "colour_outside": colour_outside, "colour_inside": colour_inside,
            "glass": glass, "furniture": furniture, "options": options,
            "inox": inox, "view": view, "mirrored": mirrored, "safeglass": safeglass,
            "black": black,
            "colorOutsideIs3": color_outside_is3, "colorInsideIs3": color_inside_is3,
        }

    def encode_code(
        self, active: Optional[bool] = None,
        first_inox_if_no_submodel: Optional[bool] = None,
        first_glass_if_no_model: Optional[bool] = None,
        **config,
    ) -> str:
        params = self._config_params(**config)
        params["active"] = _active_param(active)
        params["first_inox_if_no_submodel"] = _active_param(first_inox_if_no_submodel)
        params["first_glass_if_no_model"] = _active_param(first_glass_if_no_model)
        data = self._get("/code/", params)
        return data["code"] if isinstance(data, dict) else data

    def decode_code(self, code: str, active: Optional[bool] = None):
        return self._get("/decode/", {"code": code, "active": _active_param(active)})

    def get_price(
        self, code: Optional[str] = None, currency_name: Optional[str] = None,
        active: Optional[bool] = None,
        form_sub_id=None, color_inside_sub_id=None, color_outside_sub_id=None,
        **config,
    ) -> dict:
        """Цена по коду ИЛИ по набору id элементов (не указанные - берутся стандартные сайта)."""
        params = self._config_params(**config)
        params["code"] = code
        params["currency_name"] = currency_name
        params["active"] = _active_param(active)
        params["formSubId"] = form_sub_id
        params["colorInsideSubId"] = color_inside_sub_id
        params["colorOutsideSubId"] = color_outside_sub_id
        return self._get("/price/", params)

    def check_active(self, code: Optional[str] = None, **config):
        params = self._config_params(**config)
        params["code"] = code
        return self._get("/isactive/", params)

    # -- пользователь / заказ (требуют Bearer) -------------------------
    def get_userinfo(self):
        return self._get("/userinfo/")

    def get_doors(self, active: Optional[bool] = None):
        return self._get("/doors/", {"active": _active_param(active)})

    def add_door(self, code: str, door_image: Optional[str] = None, active: Optional[bool] = None):
        return self._post("/doors/", {"code": code, "door": door_image, "active": _active_param(active)})

    def delete_door(self, code: str):
        return self._request("DELETE", "/doors/", json_body={"code": code})

    def create_order(self, **params) -> dict:
        return self._post("/order/", {"params": params})

    def ask_question(self, phone: str, question: str) -> dict:
        return self._post("/question/", {"params": {"phone": phone, "question": question}})
