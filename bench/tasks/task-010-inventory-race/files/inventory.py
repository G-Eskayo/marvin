"""Inventory reservation system for a high-throughput e-commerce checkout service."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "inventory.db"


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def setup_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            item_id   INTEGER PRIMARY KEY,
            quantity  INTEGER NOT NULL
        )
    """)
    conn.commit()


def reserve_item(conn: sqlite3.Connection, item_id: int, quantity: int) -> bool:
    """Reserve `quantity` units of item_id. Returns True if the reservation succeeded."""
    # read current stock
    row = conn.execute(
        "SELECT quantity FROM inventory WHERE item_id = ?", (item_id,)
    ).fetchone()

    if row is None or row[0] < quantity:
        return False

    # stock confirmed — safe to decrement
    conn.execute(
        "UPDATE inventory SET quantity = quantity - ? WHERE item_id = ?",
        (quantity, item_id),
    )
    conn.commit()
    return True


def release_item(conn: sqlite3.Connection, item_id: int, quantity: int) -> None:
    """Return `quantity` units to inventory (e.g. on order cancellation)."""
    conn.execute(
        "UPDATE inventory SET quantity = quantity + ? WHERE item_id = ?",
        (quantity, item_id),
    )
    conn.commit()


def get_stock(conn: sqlite3.Connection, item_id: int) -> int | None:
    row = conn.execute(
        "SELECT quantity FROM inventory WHERE item_id = ?", (item_id,)
    ).fetchone()
    return row[0] if row else None
