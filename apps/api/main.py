import json
import logging
import os
import secrets
import threading
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from apps.api import auth
from apps.api.db import WEB_ROOT, connect, initialize_database


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("computer-sales")
MAX_BODY_BYTES = 64 * 1024
LOW_STOCK_THRESHOLD = 5
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
_login_attempts: dict[str, list[float]] = {}
_login_attempts_lock = threading.Lock()


class APIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


class SalesHandler(SimpleHTTPRequestHandler):
    server_version = "ComputerSales/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, format_string, *args):
        logger.info("%s - %s", self.address_string(), format_string % args)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return
        if not path.startswith("/api/"):
            if path == "/":
                self.path = "/index.html"
            super().do_GET()
            return
        self._dispatch(self._get)

    def do_POST(self):
        self._dispatch(self._post)

    def do_PUT(self):
        self._dispatch(self._put)

    def do_DELETE(self):
        self._dispatch(self._delete)

    def _dispatch(self, handler):
        try:
            path = urlparse(self.path).path
            self.current_user = None
            if path != "/api/login":
                self.current_user = auth.get_session(self._session_token())
                if self.current_user is None:
                    raise APIError(401, "Please sign in to continue.")
            if path in ("/api/accounts",) and self.current_user["role"] != "admin":
                raise APIError(403, "Only an administrator can manage accounts.")
            handler()
        except APIError as error:
            self._send_json(error.status, {"error": error.message})
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid request data."})
        except Exception:
            logger.exception("Unhandled request error for %s %s", self.command, self.path)
            self._send_json(500, {"error": "An unexpected server error occurred."})

    def _authenticated(self) -> bool:
        return auth.get_session(self._session_token()) is not None

    def _session_token(self) -> str | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get(auth.SESSION_COOKIE)
        return morsel.value if morsel else None

    @staticmethod
    def _login_attempt_key(username: str) -> str:
        return username.strip().casefold()

    def _check_login_rate_limit(self, client_ip: str) -> None:
        now = time.time()
        with _login_attempts_lock:
            attempts = [
                attempt
                for attempt in _login_attempts.get(client_ip, [])
                if now - attempt < LOGIN_WINDOW_SECONDS
            ]
            if attempts:
                _login_attempts[client_ip] = attempts
            else:
                _login_attempts.pop(client_ip, None)
            if len(attempts) >= LOGIN_MAX_FAILURES:
                raise APIError(429, "Too many sign-in attempts. Try again in 15 minutes.")

    def _record_login_failure(self, client_ip: str) -> None:
        now = time.time()
        with _login_attempts_lock:
            attempts = [
                attempt
                for attempt in _login_attempts.get(client_ip, [])
                if now - attempt < LOGIN_WINDOW_SECONDS
            ]
            attempts.append(now)
            _login_attempts[client_ip] = attempts

    def _clear_login_failures(self, client_ip: str) -> None:
        with _login_attempts_lock:
            _login_attempts.pop(client_ip, None)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise APIError(400, "Invalid content length.") from exc
        if length < 1 or length > MAX_BODY_BYTES:
            raise APIError(400, "Request body is missing or too large.")
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise APIError(415, "Content-Type must be application/json.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError(400, "Request body must contain valid JSON.") from exc
        if not isinstance(payload, dict):
            raise APIError(400, "Request body must be a JSON object.")
        return payload

    def _send_json(self, status: int, payload: dict, headers: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _product_payload(payload: dict) -> dict:
        name = payload.get("name")
        sku = payload.get("sku")
        category = payload.get("category")
        if not all(isinstance(value, str) for value in (name, sku, category)):
            raise APIError(400, "Name, SKU, and category are required.")
        name, sku, category = name.strip(), sku.strip().upper(), category.strip()
        if not name or len(name) > 120 or not sku or len(sku) > 40:
            raise APIError(400, "Name or SKU is empty or too long.")
        if not category or len(category) > 60:
            raise APIError(400, "Category is empty or too long.")
        price = payload.get("price")
        stock = payload.get("stock")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise APIError(400, "Price must be a non-negative number.")
        try:
            price_cents = int(
                (Decimal(str(price)) * 100).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        except (InvalidOperation, ValueError) as exc:
            raise APIError(400, "Price must be a valid amount.") from exc
        if price_cents < 0 or price_cents > 100_000_000:
            raise APIError(400, "Price is outside the allowed range.")
        if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
            raise APIError(400, "Stock must be a non-negative whole number.")
        if stock > 1_000_000:
            raise APIError(400, "Stock is outside the allowed range.")
        return {
            "name": name,
            "sku": sku,
            "category": category,
            "price_cents": price_cents,
            "stock": stock,
        }

    @staticmethod
    def _product_row(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "sku": row["sku"],
            "category": row["category"],
            "price": row["price_cents"] / 100,
            "stock": row["stock"],
        }

    def _get(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/me":
            self._send_json(200, {"user": self.current_user})
            return
        if parsed.path == "/api/accounts":
            self._send_json(200, {"accounts": auth.list_accounts()})
            return
        if parsed.path == "/api/dashboard":
            with connect() as connection:
                today = connection.execute(
                    "SELECT COALESCE(SUM(total_cents), 0) AS revenue, COUNT(*) AS count "
                    "FROM orders "
                    "WHERE date(created_at, 'localtime') = date('now', 'localtime')"
                ).fetchone()
                products = connection.execute(
                    "SELECT COUNT(*) AS count, "
                    "SUM(CASE WHEN stock <= ? THEN 1 ELSE 0 END) AS low_stock "
                    "FROM products WHERE active = 1",
                    (LOW_STOCK_THRESHOLD,),
                ).fetchone()
            self._send_json(
                200,
                {
                    "today_revenue": today["revenue"] / 100,
                    "today_orders": today["count"],
                    "active_products": products["count"],
                    "low_stock_products": products["low_stock"] or 0,
                },
            )
            return
        if parsed.path == "/api/products":
            query = parse_qs(parsed.query)
            search = query.get("search", [""])[0].strip()
            category = query.get("category", [""])[0].strip()
            statement = (
                "SELECT id, name, sku, category, price_cents, stock "
                "FROM products WHERE active = 1"
            )
            values = []
            if search:
                statement += " AND (name LIKE ? OR sku LIKE ? OR category LIKE ?)"
                pattern = f"%{search[:100]}%"
                values.extend((pattern, pattern, pattern))
            if category:
                statement += " AND category = ?"
                values.append(category[:60])
            statement += " ORDER BY name COLLATE NOCASE"
            with connect() as connection:
                rows = connection.execute(statement, values).fetchall()
            self._send_json(200, {"products": [self._product_row(row) for row in rows]})
            return
        if parsed.path == "/api/orders":
            with connect() as connection:
                order_rows = connection.execute(
                    "SELECT id, order_number, customer_name, total_cents, created_at "
                    "FROM orders ORDER BY id DESC LIMIT 100"
                ).fetchall()
                orders = []
                for row in order_rows:
                    items = connection.execute(
                        "SELECT product_name, sku, quantity, unit_price_cents "
                        "FROM order_items WHERE order_id = ? ORDER BY id",
                        (row["id"],),
                    ).fetchall()
                    orders.append(
                        {
                            "id": row["id"],
                            "order_number": row["order_number"],
                            "customer_name": row["customer_name"],
                            "total": row["total_cents"] / 100,
                            "created_at": row["created_at"],
                            "items": [
                                {
                                    "name": item["product_name"],
                                    "sku": item["sku"],
                                    "quantity": item["quantity"],
                                    "unit_price": item["unit_price_cents"] / 100,
                                }
                                for item in items
                            ],
                        }
                    )
            self._send_json(200, {"orders": orders})
            return
        raise APIError(404, "API route not found.")

    def _post(self):
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/api/login":
            username = payload.get("username")
            password = payload.get("password")
            if not isinstance(username, str) or not isinstance(password, str):
                raise APIError(400, "Username and password are required.")
            login_key = self._login_attempt_key(username)
            self._check_login_rate_limit(login_key)
            user = auth.verify_credentials(username, password)
            if user is None:
                self._record_login_failure(login_key)
                raise APIError(401, "Username or password is incorrect.")
            self._clear_login_failures(login_key)
            token = auth.create_session(user["username"], user["role"])
            secure = "; Secure" if os.environ.get("APP_ENV") == "production" else ""
            self._send_json(
                200,
                {"user": user},
                {
                    "Set-Cookie": (
                        f"{auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                        f"SameSite=Strict; Max-Age={auth.SESSION_TTL_SECONDS}{secure}"
                    )
                },
            )
            return
        if path == "/api/accounts":
            username = payload.get("username")
            password = payload.get("password")
            if not isinstance(username, str) or not isinstance(password, str):
                raise APIError(400, "Username and password are required.")
            try:
                account = auth.create_account(username, password)
            except ValueError as exc:
                raise APIError(400, str(exc)) from exc
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise APIError(409, "An account with this username already exists.") from exc
                raise
            self._send_json(201, {"account": account})
            return
        if path == "/api/logout":
            auth.revoke_session(self._session_token())
            self._send_json(
                200,
                {"status": "ok"},
                {
                    "Set-Cookie": (
                        f"{auth.SESSION_COOKIE}=; Path=/; HttpOnly; "
                        "SameSite=Strict; Max-Age=0"
                    )
                },
            )
            return
        if path == "/api/products":
            product = self._product_payload(payload)
            try:
                with connect() as connection:
                    cursor = connection.execute(
                        "INSERT INTO products (name, sku, category, price_cents, stock) "
                        "VALUES (:name, :sku, :category, :price_cents, :stock)",
                        product,
                    )
                    row = connection.execute(
                        "SELECT id, name, sku, category, price_cents, stock "
                        "FROM products WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise APIError(409, "A product with this SKU already exists.") from exc
                raise
            self._send_json(201, {"product": self._product_row(row)})
            return
        if path == "/api/orders":
            self._create_order(payload)
            return
        raise APIError(404, "API route not found.")

    def _create_order(self, payload: dict):
        customer = payload.get("customer_name", "")
        items = payload.get("items")
        if not isinstance(customer, str) or len(customer.strip()) > 120:
            raise APIError(400, "Customer name must be 120 characters or fewer.")
        if not isinstance(items, list) or not items or len(items) > 50:
            raise APIError(400, "An order must contain between 1 and 50 items.")
        quantities = {}
        for item in items:
            if not isinstance(item, dict):
                raise APIError(400, "Each order item must be an object.")
            product_id, quantity = item.get("product_id"), item.get("quantity")
            if (
                isinstance(product_id, bool)
                or not isinstance(product_id, int)
                or product_id <= 0
                or isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity <= 0
                or quantity > 1_000_000
            ):
                raise APIError(400, "Each item needs a valid product and quantity.")
            quantities[product_id] = quantities.get(product_id, 0) + quantity

        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            products = []
            for product_id, quantity in quantities.items():
                product = connection.execute(
                    "SELECT id, name, sku, price_cents, stock FROM products "
                    "WHERE id = ? AND active = 1",
                    (product_id,),
                ).fetchone()
                if product is None:
                    raise APIError(404, f"Product {product_id} is unavailable.")
                if product["stock"] < quantity:
                    raise APIError(
                        409,
                        f"Not enough stock for {product['name']} "
                        f"(available: {product['stock']}).",
                    )
                products.append((product, quantity))
            total_cents = sum(
                product["price_cents"] * quantity for product, quantity in products
            )
            order_number = "ORD-" + secrets.token_hex(4).upper()
            cursor = connection.execute(
                "INSERT INTO orders (order_number, customer_name, total_cents) "
                "VALUES (?, ?, ?)",
                (order_number, customer.strip(), total_cents),
            )
            order_id = cursor.lastrowid
            for product, quantity in products:
                connection.execute(
                    "INSERT INTO order_items "
                    "(order_id, product_id, product_name, sku, quantity, unit_price_cents) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        order_id,
                        product["id"],
                        product["name"],
                        product["sku"],
                        quantity,
                        product["price_cents"],
                    ),
                )
                connection.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (quantity, product["id"]),
                )
        self._send_json(
            201,
            {
                "order": {
                    "id": order_id,
                    "order_number": order_number,
                    "customer_name": customer.strip(),
                    "total": total_cents / 100,
                }
            },
        )

    def _put(self):
        path = urlparse(self.path).path
        prefix = "/api/products/"
        if not path.startswith(prefix):
            raise APIError(404, "API route not found.")
        try:
            product_id = int(path[len(prefix):])
        except ValueError as exc:
            raise APIError(400, "Invalid product id.") from exc
        if product_id <= 0:
            raise APIError(400, "Invalid product id.")
        product = self._product_payload(self._read_json())
        with connect() as connection:
            try:
                cursor = connection.execute(
                    "UPDATE products SET name = :name, sku = :sku, category = :category, "
                    "price_cents = :price_cents, stock = :stock "
                    "WHERE id = :id AND active = 1",
                    {**product, "id": product_id},
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise APIError(409, "A product with this SKU already exists.") from exc
                raise
            if cursor.rowcount == 0:
                raise APIError(404, "Product not found.")
            row = connection.execute(
                "SELECT id, name, sku, category, price_cents, stock "
                "FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
        self._send_json(200, {"product": self._product_row(row)})

    def _delete(self):
        path = urlparse(self.path).path
        prefix = "/api/products/"
        if not path.startswith(prefix):
            raise APIError(404, "API route not found.")
        try:
            product_id = int(path[len(prefix):])
        except ValueError as exc:
            raise APIError(400, "Invalid product id.") from exc
        with connect() as connection:
            cursor = connection.execute(
                "UPDATE products SET active = 0 WHERE id = ? AND active = 1",
                (product_id,),
            )
        if cursor.rowcount == 0:
            raise APIError(404, "Product not found.")
        self._send_json(200, {"status": "archived"})


def main():
    initialize_database()
    auth.ensure_admin_account()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), SalesHandler)
    logger.info("Computer Sales System listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
