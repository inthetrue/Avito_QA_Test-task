"""API-тесты варианта 2.1. Данные каждого теста создаются независимо."""

from uuid import uuid4

import pytest

from api_client import (
    check_no_token, check_registered_user, check_status, check_token,
    item_id, json_body, request,
)


def test_register_new_user(api, credentials):
    """REG-01."""
    check_registered_user(request(api, "POST", "/api/1/register", json=credentials), credentials)


def test_register_duplicate_username(api, registered_user):
    """REG-02."""
    check_status(request(api, "POST", "/api/1/register", json=registered_user), 409, "REG-02")


@pytest.mark.parametrize("field,value", [
    ("username", "__missing__"), ("password", "__missing__"),
    ("username", ""), ("password", ""),
    ("username", None), ("password", None),
    ("username", 123), ("password", 123),
])
def test_register_invalid_credentials(api, credentials, field, value):
    """REG-03..06, REG-08: отсутствующие, пустые и неверно типизированные данные."""
    payload = dict(credentials)
    if value == "__missing__":
        payload.pop(field)
    else:
        payload[field] = value
    check_status(request(api, "POST", "/api/1/register", json=payload), 400, "REG validation")


@pytest.mark.parametrize("path", ["/api/1/register", "/api/1/autorize"])
def test_auth_endpoints_malformed_json(api, path):
    """REG-07, AUTH-05."""
    response = request(api, "POST", path, data='{"username":',
                       headers={"Content-Type": "application/json"})
    check_status(response, 400, "Malformed JSON")


def test_authorize_registered_user(api, registered_user):
    """AUTH-01."""
    check_token(request(api, "POST", "/api/1/autorize", json=registered_user))


def test_authorize_wrong_password(api, registered_user):
    """AUTH-02."""
    response = request(api, "POST", "/api/1/autorize",
                       json={**registered_user, "password": "wrong-password"})
    check_status(response, 401, "AUTH-02")
    check_no_token(response)


def test_authorize_unknown_user(api, credentials):
    """AUTH-03: уникальное имя не регистрируется."""
    response = request(api, "POST", "/api/1/autorize", json=credentials)
    check_status(response, 401, "AUTH-03")
    check_no_token(response)


@pytest.mark.parametrize("field", ["username", "password"])
def test_authorize_missing_field(api, registered_user, field):
    """AUTH-04, AUTH-06."""
    payload = dict(registered_user)
    payload.pop(field)
    response = request(api, "POST", "/api/1/autorize", json=payload)
    check_status(response, 400, "AUTH missing field")
    check_no_token(response)


def read_item(api, owner, identifier):
    response = request(api, "GET", f"/api/1/item/{identifier}", token=owner["token"])
    check_status(response, 200, "GET-01")
    body = json_body(response, list)
    assert len(body) == 1, "По UUID должно возвращаться одно объявление"
    assert isinstance(body[0], dict)
    assert body[0].get("id") == identifier, "Вернулся другой UUID"
    return body[0]


def seller_items(api, owner):
    response = request(api, "GET", f'/api/1/{owner["id"]}/item', token=owner["token"])
    check_status(response, 200, "LIST")
    rows = json_body(response, list)
    assert all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in rows)
    return rows


def test_create_and_read_item(api, owner, items):
    """ITEM-01, GET-01: создание, чтение и сохранность переданных полей."""
    identifier, payload = items(owner)
    body = read_item(api, owner, identifier)
    assert body.get("name") == payload["name"]
    assert body.get("price") == payload["price"]
    # В опубликованном описании не зафиксирован регистр имени поля продавца.
    seller_key = next((key for key in body if key.lower() == "sellerid"), None)
    assert seller_key is not None, "Не возвращён идентификатор продавца"
    assert body[seller_key] == owner["id"]


def test_create_duplicate_payloads(api, owner, items):
    """ITEM-02."""
    name = f"same_item_{uuid4().hex}"
    first, payload = items(owner, name=name)
    second, _ = items(owner, **payload)
    assert first != second, "У разных объявлений должны быть разные UUID"
    identifiers = {row["id"] for row in seller_items(api, owner)}
    assert {first, second} <= identifiers


def test_reject_foreign_seller(api, owner, users, items):
    """ITEM-03: токен A не позволяет создать объявление на B."""
    other = users()
    payload = {"sellerID": other["id"], "name": f"foreign_{uuid4().hex}",
               "price": 9900, "statistics": {"likes": 21, "viewCount": 11, "contacts": 43}}
    response = request(api, "POST", "/api/1/item", token=owner["token"], json=payload)
    # При нарушении доступа всё равно сохраняем UUID для попытки очистки.
    if response.status_code == 200:
        items.track(item_id(response), other)
    assert response.status_code in (400, 401, 403), (
        f'ITEM-03: чужой sellerID принят, HTTP {response.status_code}'
    )
    assert not any(row.get("name") == payload["name"] for row in seller_items(api, other))


def test_x_user_id_does_not_override_owner(api, owner, users, items):
    """ITEM-04."""
    other = users()
    payload = {"sellerID": owner["id"], "name": f"header_{uuid4().hex}",
               "price": 9900, "statistics": {"likes": 21, "viewCount": 11, "contacts": 43}}
    response = request(api, "POST", "/api/1/item", token=owner["token"],
                       json=payload, headers={"X-UserId": str(other["id"])})
    if response.status_code == 200:
        identifier = item_id(response)
        items.track(identifier, owner)
        assert identifier in {row["id"] for row in seller_items(api, owner)}
    else:
        assert response.status_code in (400, 401, 403)
    assert not any(row.get("name") == payload["name"] for row in seller_items(api, other))


def test_create_malformed_json(api, owner):
    """ITEM-05."""
    response = request(api, "POST", "/api/1/item", token=owner["token"],
                       data='{"name":', headers={"Content-Type": "application/json"})
    check_status(response, 400, "ITEM-05")
    assert seller_items(api, owner) == []


@pytest.mark.parametrize("price", [-1, 0, 1])
def test_price_near_zero(api, owner, items, price):
    """BOUND-01: политика нулевой/отрицательной цены не задана, проверяем согласованность."""
    payload = {"sellerID": owner["id"], "name": f"boundary_{uuid4().hex}",
               "price": price, "statistics": {"likes": 21, "viewCount": 11, "contacts": 43}}
    response = request(api, "POST", "/api/1/item", token=owner["token"], json=payload)
    print(f"BOUND-01: price={price}, HTTP {response.status_code}")
    if response.status_code == 200:
        identifier = item_id(response)
        items.track(identifier, owner)
        assert read_item(api, owner, identifier).get("price") == price
    else:
        check_status(response, 400, "BOUND-01")
        assert seller_items(api, owner) == []


@pytest.mark.parametrize("count", [0, 1, 2])
def test_seller_item_count(api, owner, items, count):
    """LIST-01..03: граница пустого списка и соседние количества."""
    identifiers = {items(owner)[0] for _ in range(count)}
    rows = seller_items(api, owner)
    assert len(rows) == count
    assert {row["id"] for row in rows} == identifiers


def test_deleted_item_not_in_list(api, owner, items):
    """LIST-04, DEL-01, GET-02."""
    first, _ = items(owner)
    second, _ = items(owner)
    check_status(request(api, "DELETE", f"/api/2/item/{first}", token=owner["token"]), 200, "DEL-01")
    assert {row["id"] for row in seller_items(api, owner)} == {second}
    check_status(request(api, "GET", f"/api/1/item/{first}", token=owner["token"]), 404, "GET-02")


@pytest.mark.parametrize("version", [1, 2])
def test_statistics(api, owner, items, version):
    """STAT1-01, STAT2-01: статистика объявления с данными из коллекции."""
    identifier, _ = items(owner)
    response = request(api, "GET", f"/api/{version}/statistic/{identifier}", token=owner["token"])
    check_status(response, 200, f"STAT{version}-01")
    # Для v1 явно документирован массив. Для v2 схема не задана:
    # поддерживаются JSON-объект и массив из одного объекта статистики.
    body = json_body(response, list if version == 1 else (dict, list))
    if isinstance(body, list):
        assert len(body) == 1, "Ожидалась статистика одного объявления"
        body = body[0]
    assert isinstance(body, dict)
    for key in ("likes", "viewCount", "contacts"):
        assert key in body, f"В статистике нет счётчика {key}"
        assert type(body[key]) in (int, float), f"{key} должен быть числом"
        assert body[key] >= 0, f"{key} не может быть отрицательным"
    # Проверка здесь ограничена структурой и допустимыми значениями счётчиков.


@pytest.mark.parametrize("counter", [0, 1])
def test_statistics_input_near_zero(api, owner, items, counter):
    """BOUND-02: проверка валидации счётчиков вокруг нуля без выдуманных границ."""
    payload = {"sellerID": owner["id"], "name": f"counter_{uuid4().hex}",
               "price": 9900,
               "statistics": {"likes": counter, "viewCount": counter, "contacts": counter}}
    response = request(api, "POST", "/api/1/item", token=owner["token"], json=payload)
    if response.status_code == 200:
        identifier = item_id(response)
        items.track(identifier, owner)
        read_item(api, owner, identifier)
    else:
        check_status(response, 400, "BOUND-02")
        assert seller_items(api, owner) == []


@pytest.mark.parametrize("version", [1, 2])
def test_deleted_item_statistics(api, owner, items, version):
    """STAT1-02, STAT2-02."""
    identifier, _ = items(owner)
    check_status(request(api, "DELETE", f"/api/2/item/{identifier}", token=owner["token"]), 200)
    check_status(request(api, "GET", f"/api/1/item/{identifier}", token=owner["token"]), 404)
    response = request(api, "GET", f"/api/{version}/statistic/{identifier}", token=owner["token"])
    check_status(response, 404, f"STAT{version}-02; подтверждённый дефект API-0{version} в BUGS.md")


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/1/item/not-a-uuid"),
    ("GET", "/api/1/statistic/not-a-uuid"),
    ("DELETE", "/api/2/item/not-a-uuid"),
])
def test_invalid_uuid(api, owner, method, path):
    """GET-03, STAT1-03, DEL-03."""
    check_status(request(api, method, path, token=owner["token"]), 400, "Invalid UUID")


def test_delete_twice(api, owner, items):
    """DEL-02."""
    identifier, _ = items(owner)
    path = f"/api/2/item/{identifier}"
    check_status(request(api, "DELETE", path, token=owner["token"]), 200)
    check_status(request(api, "DELETE", path, token=owner["token"]), 404, "DEL-02")


@pytest.mark.parametrize("operation", ["create", "get", "list", "stat1", "stat2", "delete"])
@pytest.mark.parametrize("bad_token", [None, "invalid-token"], ids=["no-token", "invalid-token"])
def test_protected_access(api, owner, items, operation, bad_token):
    """ACCESS-01..02 для каждой из шести защищённых ручек."""
    identifier, payload = items(owner)
    method, path = {
        "create": ("POST", "/api/1/item"),
        "get": ("GET", f"/api/1/item/{identifier}"),
        "list": ("GET", f'/api/1/{owner["id"]}/item'),
        "stat1": ("GET", f"/api/1/statistic/{identifier}"),
        "stat2": ("GET", f"/api/2/statistic/{identifier}"),
        "delete": ("DELETE", f"/api/2/item/{identifier}"),
    }[operation]
    response = request(api, method, path, token=bad_token,
                       **({"json": payload} if operation == "create" else {}))
    check_status(response, 401, "ACCESS")
    if operation in ("create", "delete"):
        assert {row["id"] for row in seller_items(api, owner)} == {identifier}
