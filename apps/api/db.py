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
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'staff')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_orders_created_at
                ON orders(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_order_items_order_id
                ON order_items(order_id);
            """
        )
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            connection.executemany(
                """
                INSERT INTO products (name, sku, category, price_cents, stock)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("Laptop Pro 14", "LAP-014", "Laptop", 129900, 8),
                    ("Gaming Desktop R7", "PC-GAM-07", "Desktop", 189900, 4),
                    ("Mechanical Keyboard", "ACC-KB-01", "Accessory", 8999, 15),
                    ("Wireless Mouse", "ACC-MS-02", "Accessory", 3999, 3),
                    ("27-inch Monitor", "MON-027", "Monitor", 27900, 6),
                ],
            )
