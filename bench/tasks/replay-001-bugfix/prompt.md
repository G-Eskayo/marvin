# Fix off-by-one error in median calculation

Fix the median() function to correctly handle both odd and even-length lists.

The bug: median([1,2,3,4]) returns the wrong value due to incorrect list slicing.

Run tests to verify: pytest tests/ -q
