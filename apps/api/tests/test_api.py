import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.api import auth
from apps.api import main as api_main
from apps.api.db import initialize_database
from apps.api.main import SalesHandler


class SalesAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = cls.temp_dir.name
        os.environ["ADMIN_USERNAME"] = "test-admin"
        os.environ["ADMIN_PASSWORD"] = "test-password-123!"
        initialize_database()
        auth.ensure_admin_account()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SalesHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        auth.clear_sessions()
        cls.temp_dir.cleanup()
        os.environ.pop("DATA_DIR", None)
        os.environ.pop("ADMIN_USERNAME", None)
        os.environ.pop("ADMIN_PASSWORD", None)

    def setUp(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = build_opener(HTTPCookieProcessor(self.cookies))
        response = self.request(
            "/api/login",
            {"username": "test-admin", "password": "test-password-123!"},
            method="POST",
        )
        self.assertEqual(response.status, 200)

    def request(self, path, payload=None, method=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            return self.client.open(request, timeout=3)
        except HTTPError as error:
            return error

    def body(self, response):
        return json.loads(response.read())

    def test_api_requires_login(self):
        client = build_opener()
        try:
            client.open(self.url + "/api/products")
            self.fail("Unauthenticated request should be rejected.")
        except HTTPError as error:
            self.assertEqual(error.code, 401)

    def test_wrong_password_is_rejected(self):
        response = self.request(
            "/api/login",
            {"username": "test-admin", "password": "wrong"},
            method="POST",
        )
        self.assertEqual(response.status, 401)

    def test_login_is_rate_limited_after_repeated_failures(self):
        api_main._login_attempts.clear()
        for _ in range(5):
            response = self.request(
                "/api/login",
                {"username": "test-admin", "password": "wrong"},
                method="POST",
            )
            self.assertEqual(response.status, 401)
        limited = self.request(
            "/api/login",
            {"username": "test-admin", "password": "test-password-123!"},
            method="POST",
        )
        self.assertEqual(limited.status, 429)
        api_main._login_attempts.clear()

    def test_admin_can_create_staff_account_but_staff_cannot_manage_accounts(self):
        created = self.request(
            "/api/accounts",
            {
                "username": "cashier-1",
                "password": "cashier-password-123",
                "role": "admin",
            },
            "POST",
        )
        self.assertEqual(created.status, 201)
        account = self.body(created)["account"]
        self.assertEqual(account["role"], "staff")

        staff_client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        login = staff_client.open(
            Request(
                self.url + "/api/login",
                data=json.dumps(
                    {"username": "cashier-1", "password": "cashier-password-123"}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout=3,
        )
        self.assertEqual(login.status, 200)
        self.assertEqual(json.loads(login.read())["user"]["role"], "staff")

        try:
            staff_client.open(self.url + "/api/accounts")
            self.fail("Staff must not be allowed to manage accounts.")
        except HTTPError as error:
            self.assertEqual(error.code, 403)
        try:
            staff_client.open(
                Request(
                    self.url + "/api/accounts",
                    data=json.dumps(
                        {"username": "cashier-4", "password": "cashier-password-123"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=3,
            )
            self.fail("Staff must not be allowed to create accounts.")
        except HTTPError as error:
            self.assertEqual(error.code, 403)

    def test_duplicate_usernames_and_short_passwords_are_rejected(self):
        first = self.request(
            "/api/accounts",
            {"username": "cashier-2", "password": "cashier-password-123"},
            "POST",
        )
        self.assertEqual(first.status, 201)
        duplicate = self.request(
            "/api/accounts",
            {"username": "CASHIER-2", "password": "another-password-123"},
            "POST",
        )
        self.assertEqual(duplicate.status, 409)
        short_password = self.request(
            "/api/accounts",
            {"username": "cashier-3", "password": "short"},
            "POST",
        )
        self.assertEqual(short_password.status, 400)

    def test_create_product_rejects_duplicate_sku(self):
        product = {
            "name": "Test laptop",
            "sku": "LAP-014",
            "category": "Laptop",
            "price": 799.99,
            "stock": 2,
        }
        response = self.request("/api/products", product, "POST")
        self.assertEqual(response.status, 409)

    def test_order_deducts_stock_and_uses_server_price(self):
        products = self.body(self.request("/api/products"))["products"]
        product = next(item for item in products if item["sku"] == "ACC-KB-01")
        response = self.request(
            "/api/orders",
            {"customer_name": "Test customer", "items": [{"product_id": product["id"], "quantity": 2}]},
            "POST",
        )
        self.assertEqual(response.status, 201)
        self.assertEqual(self.body(response)["order"]["total"], 179.98)
        updated = self.body(self.request("/api/products"))["products"]
        keyboard = next(item for item in updated if item["id"] == product["id"])
        self.assertEqual(keyboard["stock"], product["stock"] - 2)

    def test_insufficient_stock_does_not_create_order_or_change_stock(self):
        products = self.body(self.request("/api/products"))["products"]
        mouse = next(item for item in products if item["sku"] == "ACC-MS-02")
        before_orders = len(self.body(self.request("/api/orders"))["orders"])
        response = self.request(
            "/api/orders",
            {"items": [{"product_id": mouse["id"], "quantity": mouse["stock"] + 1}]},
            "POST",
        )
        self.assertEqual(response.status, 409)
        refreshed = self.body(self.request("/api/products"))["products"]
        self.assertEqual(next(item for item in refreshed if item["id"] == mouse["id"])["stock"], mouse["stock"])
        self.assertEqual(len(self.body(self.request("/api/orders"))["orders"]), before_orders)


if __name__ == "__main__":
    unittest.main()
