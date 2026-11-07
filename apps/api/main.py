import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from apps.api import alerts, auth
from apps.api.db import WEB_ROOT, connect, initialize_database


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("computer-sales")
MAX_BODY_BYTES = 64 * 1024
LOW_STOCK_THRESHOLD = 5
CUSTOMER_PASSWORD_ITERATIONS = 310_000
PAYMENT_METHODS = {"cash", "aba_payway", "khqr", "card"}


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
            "connect-src 'self'; img-src 'self' https: data:; base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, format_string, *args):
        logger.info("%s - %s", self.address_string(), format_string % args)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            try:
                with connect() as connection:
                    connection.execute("SELECT 1").fetchone()
            except Exception:
                logger.exception("Health check failed.")
                alerts.record_event(
                    "Health check failed",
                    "critical",
                    "The application health check could not access its database.",
                    route=path,
                )
                self._send_json(503, {"status": "unavailable"})
                return
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
            public_paths = {
                "/api/login",
                "/api/customer/login",
                "/api/customer/register",
                "/api/session",
                "/api/storefront/products",
            }
            public_pattern = re.fullmatch(
                r"/api/storefront/products/\d+|/api/products/\d+/reviews", path
            )
            if path not in public_paths and not public_pattern and not self._authenticated():
                raise APIError(401, "Please sign in to continue.")
            if (
                path == "/api/dashboard"
                or path == "/api/security/events"
                or path == "/api/products"
                or path == "/api/orders"
                or re.fullmatch(r"/api/products/\d+", path)
                or re.fullmatch(r"/api/orders/\d+/status", path)
            ):
                self._require_role("admin")
            if path.startswith("/api/customer/") and path not in {
                "/api/customer/login",
                "/api/customer/register",
            }:
                self._require_role("customer")
            handler()
        except APIError as error:
            if error.status in (401, 403):
                path = urlparse(self.path).path
                if path == "/api/login" or path == "/api/customer/login":
                    category = "Failed sign-in"
                    account_type = "customer" if path == "/api/customer/login" else "administrator"
                    message = f"An {account_type} sign-in attempt failed."
                else:
                    category = "Unauthorized access"
                    message = f"Request rejected with HTTP {error.status}."
                alerts.record_event(
                    category,
                    "warning",
                    message,
                    route=path,
                )
            self._send_json(error.status, {"error": error.message})
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid request data."})
        except Exception:
            logger.exception("Unhandled request error for %s %s", self.command, self.path)
            alerts.record_event(
                "Server error",
                "critical",
                f"Unhandled server error while processing {self.command}.",
                route=urlparse(self.path).path,
            )
            self._send_json(500, {"error": "An unexpected server error occurred."})

    def _authenticated(self) -> bool:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get(auth.SESSION_COOKIE)
        return auth.is_valid_session(morsel.value if morsel else None)

    def _session_token(self) -> str | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get(auth.SESSION_COOKIE)
        return morsel.value if morsel else None

    def _require_role(self, role: str):
        identity = auth.session_identity(self._session_token())
        if identity is None or identity[1] != role:
            raise APIError(403, "You do not have permission to access this resource.")

    def _customer_id(self) -> int:
        identity = auth.session_identity(self._session_token())
        if identity is None or identity[1] != "customer":
            raise APIError(403, "Please sign in with a customer account.")
        return int(identity[0])

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
        brand = payload.get("brand", "")
        description = payload.get("description", "")
        image_url = payload.get("image_url", "")
        if not all(isinstance(value, str) for value in (brand, description, image_url)):
            raise APIError(400, "Brand, description, and image URL must be text.")
        brand, description, image_url = brand.strip(), description.strip(), image_url.strip()
        if image_url and not (
            image_url.startswith("https://")
            or (image_url.startswith("/") and not image_url.startswith("//"))
        ):
            raise APIError(400, "Product image must use HTTPS or a same-site path.")
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
            "brand": brand[:60],
            "description": description[:1000],
            "image_url": image_url[:500],
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
            "brand": row["brand"],
            "description": row["description"],
            "image_url": row["image_url"],
            "price": row["price_cents"] / 100,
            "stock": row["stock"],
        }

    def _get(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/session":
            identity = auth.session_identity(self._session_token())
            session = {"role": identity[1]} if identity else {"role": None}
            if identity and identity[1] == "customer":
                with connect() as connection:
                    customer = connection.execute(
                        "SELECT email, full_name FROM customers WHERE id = ?",
                        (int(identity[0]),),
                    ).fetchone()
                if customer:
                    session["profile"] = {
                        "email": customer["email"],
                        "full_name": customer["full_name"],
                    }
            self._send_json(200, session)
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
        if parsed.path == "/api/security/events":
            configured = bool(
                os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                and os.environ.get("TELEGRAM_CHAT_ID", "").strip()
            )
            self._send_json(
                200,
                {
                    "events": alerts.recent_events(),
                    "telegram_configured": configured,
                },
            )
            return
        if parsed.path == "/api/products":
            query = parse_qs(parsed.query)
            search = query.get("search", [""])[0].strip()
            category = query.get("category", [""])[0].strip()
            statement = (
                "SELECT id, name, sku, category, brand, description, image_url, "
                "price_cents, stock FROM products WHERE active = 1"
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
        if parsed.path == "/api/storefront/products":
            query = parse_qs(parsed.query)
            search = query.get("search", [""])[0].strip()[:100]
            category = query.get("category", [""])[0].strip()[:60]
            brand = query.get("brand", [""])[0].strip()[:60]
            clauses, values = ["active = 1"], []
            if search:
                clauses.append("(name LIKE ? OR sku LIKE ? OR category LIKE ? OR brand LIKE ?)")
                pattern = f"%{search}%"
                values.extend((pattern, pattern, pattern, pattern))
            if category:
                clauses.append("category = ?")
                values.append(category)
            if brand:
                clauses.append("brand = ?")
                values.append(brand)
            for key, operator in (("min_price", ">="), ("max_price", "<=")):
                raw = query.get(key, [""])[0]
                if raw:
                    try:
                        cents = int((Decimal(raw) * 100).quantize(Decimal("1")))
                    except (InvalidOperation, ValueError) as exc:
                        raise APIError(400, "Invalid price filter.") from exc
                    if cents < 0:
                        raise APIError(400, "Price filter cannot be negative.")
                    clauses.append(f"price_cents {operator} ?")
                    values.append(cents)
            with connect() as connection:
                rows = connection.execute(
                    "SELECT id, name, sku, category, brand, description, image_url, "
                    "price_cents, stock FROM products WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY name COLLATE NOCASE",
                    values,
                ).fetchall()
                categories = [
                    row[0] for row in connection.execute(
                        "SELECT DISTINCT category FROM products WHERE active = 1 ORDER BY category"
                    )
                ]
                brands = [
                    row[0] for row in connection.execute(
                        "SELECT DISTINCT brand FROM products "
                        "WHERE active = 1 AND brand <> '' ORDER BY brand"
                    )
                ]
            self._send_json(
                200,
                {
                    "products": [self._product_row(row) for row in rows],
                    "categories": categories,
                    "brands": brands,
                },
            )
            return
        product_match = re.fullmatch(r"/api/storefront/products/(\d+)", parsed.path)
        if product_match:
            with connect() as connection:
                row = connection.execute(
                    "SELECT id, name, sku, category, brand, description, image_url, "
                    "price_cents, stock FROM products WHERE id = ? AND active = 1",
                    (int(product_match.group(1)),),
                ).fetchone()
                if row is None:
                    raise APIError(404, "Product not found.")
                reviews = connection.execute(
                    "SELECT r.rating, r.comment, r.created_at, c.full_name "
                    "FROM reviews r JOIN customers c ON c.id = r.customer_id "
                    "WHERE r.product_id = ? ORDER BY r.id DESC",
                    (row["id"],),
                ).fetchall()
            product = self._product_row(row)
            product["reviews"] = [
                {"rating": review["rating"], "comment": review["comment"],
                 "customer_name": review["full_name"], "created_at": review["created_at"]}
                for review in reviews
            ]
            self._send_json(200, {"product": product})
            return
        review_match = re.fullmatch(r"/api/products/(\d+)/reviews", parsed.path)
        if review_match:
            with connect() as connection:
                reviews = connection.execute(
                    "SELECT r.rating, r.comment, r.created_at, c.full_name "
                    "FROM reviews r JOIN customers c ON c.id = r.customer_id "
                    "WHERE r.product_id = ? ORDER BY r.id DESC",
                    (int(review_match.group(1)),),
                ).fetchall()
            self._send_json(
                200,
                {"reviews": [
                    {"rating": row["rating"], "comment": row["comment"],
                     "customer_name": row["full_name"], "created_at": row["created_at"]}
                    for row in reviews
                ]},
            )
            return
        if parsed.path == "/api/customer/profile":
            with connect() as connection:
                row = connection.execute(
                    "SELECT email, full_name, phone, address FROM customers WHERE id = ?",
                    (self._customer_id(),),
                ).fetchone()
            if row is None:
                raise APIError(404, "Customer account not found.")
            self._send_json(200, {"profile": dict(row)})
            return
        if parsed.path == "/api/customer/orders":
            self._send_json(200, {"orders": self._customer_orders(self._customer_id())})
            return
        customer_order_match = re.fullmatch(r"/api/customer/orders/([A-Za-z0-9-]+)", parsed.path)
        if customer_order_match:
            customer_id = self._customer_id()
            with connect() as connection:
                order = connection.execute(
                    "SELECT id, order_number, status, payment_status, payment_method, "
                    "shipping_address, total_cents, created_at FROM orders "
                    "WHERE order_number = ? AND customer_id = ?",
                    (customer_order_match.group(1), customer_id),
                ).fetchone()
            if order is None:
                raise APIError(404, "Order not found.")
            self._send_json(200, {"order": self._customer_order_payload(order)})
            return
        if parsed.path == "/api/orders":
            with connect() as connection:
                order_rows = connection.execute(
                    "SELECT id, order_number, customer_name, total_cents, status, "
                    "payment_method, created_at "
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
                            "status": row["status"],
                            "payment_method": row["payment_method"],
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
        if path == "/api/customer/register":
            self._register_customer(payload)
            return
        if path == "/api/customer/login":
            self._login_customer(payload)
            return
        if path == "/api/login":
            username = payload.get("username")
            password = payload.get("password")
            if not isinstance(username, str) or not isinstance(password, str):
                raise APIError(400, "Username and password are required.")
            if not auth.verify_credentials(username, password):
                raise APIError(401, "Username or password is incorrect.")
            token = auth.create_session(username, "admin")
            secure = "; Secure" if os.environ.get("APP_ENV") == "production" else ""
            self._send_json(
                200,
                {"username": username},
                {
                    "Set-Cookie": (
                        f"{auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                        f"SameSite=Strict; Max-Age={auth.SESSION_TTL_SECONDS}{secure}"
                    )
                },
            )
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
                        "INSERT INTO products "
                        "(name, sku, category, brand, description, image_url, price_cents, stock) "
                        "VALUES (:name, :sku, :category, :brand, :description, :image_url, "
                        ":price_cents, :stock)",
                        product,
                    )
                    row = connection.execute(
                        "SELECT id, name, sku, category, brand, description, image_url, "
                        "price_cents, stock "
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
        if path == "/api/customer/orders":
            self._create_customer_order(payload)
            return
        review_match = re.fullmatch(r"/api/products/(\d+)/reviews", path)
        if review_match:
            self._create_review(int(review_match.group(1)), payload)
            return
        raise APIError(404, "API route not found.")

    def _register_customer(self, payload: dict):
        email, password = payload.get("email"), payload.get("password")
        full_name, phone = payload.get("full_name"), payload.get("phone", "")
        if not isinstance(email, str) or not re.fullmatch(
            r"[^@\s]{1,100}@[^@\s]{1,190}\.[^@\s]{2,30}", email.strip()
        ):
            raise APIError(400, "Enter a valid email address.")
        if not isinstance(password, str) or not 10 <= len(password) <= 256:
            raise APIError(400, "Password must contain 10 to 256 characters.")
        if not isinstance(full_name, str) or not full_name.strip() or len(full_name.strip()) > 120:
            raise APIError(400, "Full name is required and must be 120 characters or fewer.")
        if not isinstance(phone, str) or len(phone.strip()) > 40:
            raise APIError(400, "Phone number must be 40 characters or fewer.")
        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, CUSTOMER_PASSWORD_ITERATIONS
        )
        try:
            with connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO customers (email, password_hash, password_salt, full_name, phone) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (email.strip().lower(), password_hash, salt, full_name.strip(), phone.strip()),
                )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise APIError(409, "An account with this email already exists.") from exc
            raise
        token = auth.create_session(str(cursor.lastrowid), "customer")
        self._send_json(
            201,
            {"profile": {"email": email.strip().lower(), "full_name": full_name.strip()}},
            self._session_cookie(token),
        )

    def _login_customer(self, payload: dict):
        email, password = payload.get("email"), payload.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise APIError(400, "Email and password are required.")
        with connect() as connection:
            customer = connection.execute(
                "SELECT id, email, password_hash, password_salt, full_name "
                "FROM customers WHERE email = ?",
                (email.strip(),),
            ).fetchone()
        salt = customer["password_salt"] if customer else b"computer-sales-demo"
        submitted_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, CUSTOMER_PASSWORD_ITERATIONS
        )
        if customer is None or not hmac.compare_digest(
            submitted_hash, customer["password_hash"]
        ):
            raise APIError(401, "Email or password is incorrect.")
        token = auth.create_session(str(customer["id"]), "customer")
        self._send_json(
            200,
            {"profile": {"email": customer["email"], "full_name": customer["full_name"]}},
            self._session_cookie(token),
        )

    @staticmethod
    def _session_cookie(token: str) -> dict:
        secure = "; Secure" if os.environ.get("APP_ENV") == "production" else ""
        return {
            "Set-Cookie": (
                f"{auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                f"SameSite=Strict; Max-Age={auth.SESSION_TTL_SECONDS}{secure}"
            )
        }

    @staticmethod
    def _customer_order_payload(row) -> dict:
        return {
            "order_number": row["order_number"],
            "status": row["status"],
            "payment_status": row["payment_status"],
            "payment_method": row["payment_method"],
            "shipping_address": row["shipping_address"],
            "total": row["total_cents"] / 100,
            "created_at": row["created_at"],
        }

    def _customer_orders(self, customer_id: int) -> list[dict]:
        with connect() as connection:
            orders = connection.execute(
                "SELECT id, order_number, status, payment_status, payment_method, "
                "shipping_address, total_cents, created_at FROM orders "
                "WHERE customer_id = ? ORDER BY id DESC LIMIT 100",
                (customer_id,),
            ).fetchall()
            result = []
            for order in orders:
                data = self._customer_order_payload(order)
                data["items"] = [
                    {"name": item["product_name"], "quantity": item["quantity"],
                     "unit_price": item["unit_price_cents"] / 100}
                    for item in connection.execute(
                        "SELECT product_name, quantity, unit_price_cents "
                        "FROM order_items WHERE order_id = ?",
                        (order["id"],),
                    )
                ]
                result.append(data)
            return result

    def _create_customer_order(self, payload: dict):
        customer_id = self._customer_id()
        address, payment_method, items = (
            payload.get("shipping_address"), payload.get("payment_method"), payload.get("items")
        )
        if not isinstance(address, str) or not address.strip() or len(address.strip()) > 500:
            raise APIError(400, "A shipping address of 500 characters or fewer is required.")
        if payment_method not in PAYMENT_METHODS:
            raise APIError(400, "Choose a supported demo payment method.")
        if not isinstance(items, list) or not items or len(items) > 50:
            raise APIError(400, "An order must contain between 1 and 50 items.")
        quantities = {}
        for item in items:
            if not isinstance(item, dict):
                raise APIError(400, "Each order item must be an object.")
            product_id, quantity = item.get("product_id"), item.get("quantity")
            if (
                isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0
                or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0
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
                    raise APIError(404, "A product in your cart is no longer available.")
                if product["stock"] < quantity:
                    raise APIError(409, f"Not enough stock for {product['name']}.")
                products.append((product, quantity))
            total_cents = sum(product["price_cents"] * quantity for product, quantity in products)
            customer = connection.execute(
                "SELECT full_name FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            order_number = "ORD-" + secrets.token_hex(4).upper()
            cursor = connection.execute(
                "INSERT INTO orders (order_number, customer_name, total_cents, customer_id, "
                "shipping_address, payment_method, payment_status, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'processing')",
                (order_number, customer["full_name"], total_cents, customer_id, address.strip(),
                 payment_method, "pending" if payment_method == "cash" else "demo"),
            )
            for product, quantity in products:
                connection.execute(
                    "INSERT INTO order_items "
                    "(order_id, product_id, product_name, sku, quantity, unit_price_cents) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (cursor.lastrowid, product["id"], product["name"], product["sku"],
                     quantity, product["price_cents"]),
                )
                connection.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (quantity, product["id"]),
                )
        self._send_json(
            201,
            {"order": {"order_number": order_number, "total": total_cents / 100}},
        )

    def _create_review(self, product_id: int, payload: dict):
        customer_id = self._customer_id()
        rating, comment = payload.get("rating"), payload.get("comment", "")
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise APIError(400, "Rating must be a whole number from 1 to 5.")
        if not isinstance(comment, str) or len(comment.strip()) > 1000:
            raise APIError(400, "Review must be 1,000 characters or fewer.")
        with connect() as connection:
            purchase = connection.execute(
                "SELECT oi.order_id FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                "WHERE oi.product_id = ? AND o.customer_id = ? LIMIT 1",
                (product_id, customer_id),
            ).fetchone()
            if purchase is None:
                raise APIError(403, "Only customers who purchased this product can review it.")
            try:
                connection.execute(
                    "INSERT INTO reviews (product_id, customer_id, order_id, rating, comment) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (product_id, customer_id, purchase["order_id"], rating, comment.strip()),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise APIError(409, "You have already reviewed this product.") from exc
                raise
        self._send_json(201, {"status": "created"})

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
        if path == "/api/customer/profile":
            payload = self._read_json()
            name, phone, address = (
                payload.get("full_name"), payload.get("phone", ""), payload.get("address", "")
            )
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
                raise APIError(400, "Full name is required and must be 120 characters or fewer.")
            if not isinstance(phone, str) or len(phone.strip()) > 40:
                raise APIError(400, "Phone number must be 40 characters or fewer.")
            if not isinstance(address, str) or len(address.strip()) > 500:
                raise APIError(400, "Address must be 500 characters or fewer.")
            with connect() as connection:
                connection.execute(
                    "UPDATE customers SET full_name = ?, phone = ?, address = ? WHERE id = ?",
                    (name.strip(), phone.strip(), address.strip(), self._customer_id()),
                )
            self._send_json(200, {"status": "updated"})
            return
        status_match = re.fullmatch(r"/api/orders/(\d+)/status", path)
        if status_match:
            status = self._read_json().get("status")
            if status not in {"processing", "shipping", "delivered"}:
                raise APIError(400, "Choose a valid order status.")
            with connect() as connection:
                cursor = connection.execute(
                    "UPDATE orders SET status = ? WHERE id = ?",
                    (status, int(status_match.group(1))),
                )
            if cursor.rowcount == 0:
                raise APIError(404, "Order not found.")
            self._send_json(200, {"status": status})
            return
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
                    "brand = :brand, description = :description, image_url = :image_url, "
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
                "SELECT id, name, sku, category, brand, description, image_url, "
                "price_cents, stock "
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
