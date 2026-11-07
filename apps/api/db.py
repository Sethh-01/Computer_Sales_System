import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "apps" / "web"


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def database_path() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "computer_sales.sqlite3"


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(
        database_path(), timeout=10, factory=ClosingConnection
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                brand TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
                stock INTEGER NOT NULL CHECK (stock >= 0),
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL DEFAULT '',
                total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
                customer_id INTEGER REFERENCES customers(id),
                shipping_address TEXT NOT NULL DEFAULT '',
                payment_method TEXT NOT NULL DEFAULT 'cash',
                payment_status TEXT NOT NULL DEFAULT 'paid',
                status TEXT NOT NULL DEFAULT 'delivered',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash BLOB NOT NULL,
                password_salt BLOB NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER REFERENCES products(id),
                product_name TEXT NOT NULL,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0)
            );
            CREATE INDEX IF NOT EXISTS idx_orders_created_at
                ON orders(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_order_items_order_id
                ON order_items(order_id);
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products(id),
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                order_id INTEGER NOT NULL REFERENCES orders(id),
                rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(product_id, customer_id)
            );
            CREATE INDEX IF NOT EXISTS idx_reviews_product_id
                ON reviews(product_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                severity TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
                message TEXT NOT NULL,
                route TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_security_events_created_at
                ON security_events(id DESC);
            """
        )
        migrations = {
            "products": {
                "brand": "TEXT NOT NULL DEFAULT ''",
                "description": "TEXT NOT NULL DEFAULT ''",
                "image_url": "TEXT NOT NULL DEFAULT ''",
            },
            "orders": {
                "customer_id": "INTEGER REFERENCES customers(id)",
                "shipping_address": "TEXT NOT NULL DEFAULT ''",
                "payment_method": "TEXT NOT NULL DEFAULT 'cash'",
                "payment_status": "TEXT NOT NULL DEFAULT 'paid'",
                "status": "TEXT NOT NULL DEFAULT 'delivered'",
            },
        }
        for table, columns in migrations.items():
            existing = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            connection.executemany(
                """
                INSERT INTO products
                    (name, sku, category, brand, description, price_cents, stock)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("Laptop Pro 14", "LAP-014", "Laptop", "TechPoint", "កុំព្យូទ័រយួរដៃសម្រាប់ការងារ និងការសិក្សា", 129900, 8),
                    ("Gaming Desktop R7", "PC-GAM-07", "Desktop", "TechPoint", "កុំព្យូទ័រលើតុសម្រាប់លេងហ្គេម និងការងារធ្ងន់", 189900, 4),
                    ("Mechanical Keyboard", "ACC-KB-01", "Accessory", "KeyPro", "ក្ដារចុចមេកានិច សម្រាប់វាយអក្សរ និងលេងហ្គេម", 8999, 15),
                    ("Wireless Mouse", "ACC-MS-02", "Accessory", "Click", "កណ្ដុរឥតខ្សែ ងាយស្រួលប្រើ", 3999, 3),
                    ("27-inch Monitor", "MON-027", "Monitor", "ViewMax", "អេក្រង់ ២៧ អ៊ីញ សម្រាប់ការងារច្បាស់ល្អ", 27900, 6),
                ],
            )
