"""A sorted list that maintains elements in ascending order with O(log n) operations.

All public methods should be O(log n) or better.
"""


class SortedList:

    def __init__(self):
        self._data = []

    def add(self, value):
        """Insert value maintaining sorted order."""
        # slow: O(n) linear scan + insert
        for i, item in enumerate(self._data):
            if value <= item:
                self._data.insert(i, value)
                return
        self._data.append(value)

    def find(self, value) -> bool:
        """Return True if value is present."""
        # slow: O(n) linear scan instead of binary search
        for item in self._data:
            if item == value:
                return True
        return False

    def discard(self, value):
        """Remove the first occurrence of value. Does nothing if value is absent."""
        # bug: removes ALL occurrences, not just the first
        self._data = [x for x in self._data if x != value]

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def to_list(self):
        return list(self._data)
