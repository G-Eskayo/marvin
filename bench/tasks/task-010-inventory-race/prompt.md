During last week's flash sale, `item_id=42` had 100 units in stock but the service
sold 150 — `quantity` is now `-50` in the database. The bug is intermittent in
development but reproduces reliably under concurrent production load (two checkout
servers processing the same item simultaneously).

`reserve_item` in `inventory.py` is the suspected function. The service processes
10,000+ reservation requests per second. Any fix must not introduce lock contention
or serialise requests through a single bottleneck.

Diagnose the root cause and fix `reserve_item`.
