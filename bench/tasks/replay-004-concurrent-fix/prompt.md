# Fix race condition in inventory update

The inventory system loses updates when multiple threads modify the same item simultaneously.

Add proper locking or atomic operations to ensure all inventory modifications are thread-safe.

Verify: pytest tests/test_inventory.py -q
