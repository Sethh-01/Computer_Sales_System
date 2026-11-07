import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import HTTPCookieProcessor, Request, build_opener
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.api import alerts, auth
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

    def test_security_events_are_recorded_and_admin_only(self):
        response = self.request(
            "/api/login",
            {"username": "not-the-admin", "password": "wrong"},
            method="POST",
        )
        self.assertEqual(response.status, 401)
        events = self.body(self.request("/api/security/events"))["events"]
        event = next(item for item in events if item["category"] == "Failed sign-in")
        self.assertEqual(event["severity"], "warning")
        self.assertNotIn("not-the-admin", event["message"])

        unauthenticated = build_opener()
        try:
            unauthenticated.open(self.url + "/api/security/events")
            self.fail("Security events should require administrator authentication.")
        except HTTPError as error:
            self.assertEqual(error.code, 401)

    def test_telegram_alert_message_excludes_secrets(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "test-chat"},
        ):
            with patch("apps.api.alerts.urlopen", return_value=response) as send:
                alerts._send_telegram(
                    "Failed sign-in", "warning", "An administrator sign-in attempt failed."
                )
        request = send.call_args.args[0]
        text = parse_qs(request.data.decode("utf-8"))["text"][0]
        self.assertIn("Failed sign-in", text)
        self.assertNotIn("test-token", text)
        self.assertNotIn("test-chat", text)
        self.assertNotIn("password", text.lower())

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

    def test_customer_checkout_tracking_and_verified_review(self):
        customer = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def customer_request(path, payload=None, method=None):
            data = json.dumps(payload).encode() if payload is not None else None
            request = Request(self.url + path, data=data, method=method)
            if data is not None:
                request.add_header("Content-Type", "application/json")
            try:
                return customer.open(request, timeout=5)
            except HTTPError as error:
                return error

        registration = customer_request(
            "/api/customer/register",
            {
                "email": "buyer@example.test",
                "password": "customer-password-123",
                "full_name": "Test Buyer",
                "phone": "012345678",
            },
            "POST",
        )
        self.assertEqual(registration.status, 201)
        products = self.body(self.request("/api/products"))["products"]
        product = next(item for item in products if item["sku"] == "ACC-KB-01")
        checkout = customer_request(
            "/api/customer/orders",
            {
                "items": [{"product_id": product["id"], "quantity": 1}],
                "shipping_address": "Phnom Penh",
                "payment_method": "khqr",
            },
            "POST",
        )
        self.assertEqual(checkout.status, 201)
        order_number = self.body(checkout)["order"]["order_number"]
        tracked = self.body(customer_request(f"/api/customer/orders/{order_number}"))["order"]
        self.assertEqual(tracked["status"], "processing")
        self.assertEqual(tracked["payment_method"], "khqr")
        self.assertEqual(tracked["shipping_address"], "Phnom Penh")

        forbidden_admin_route = customer_request("/api/dashboard")
        self.assertEqual(forbidden_admin_route.status, 403)
        review = customer_request(
            f"/api/products/{product['id']}/reviews",
            {"rating": 5, "comment": "Works well"},
            "POST",
        )
        self.assertEqual(review.status, 201)
        details = self.body(customer_request(f"/api/storefront/products/{product['id']}"))
        self.assertEqual(details["product"]["reviews"][0]["comment"], "Works well")
        duplicate_review = customer_request(
            f"/api/products/{product['id']}/reviews", {"rating": 4}, "POST"
        )
        self.assertEqual(duplicate_review.status, 409)


if __name__ == "__main__":
    unittest.main()
