SortedList is used in a hot path processing tens of thousands of items and is too slow.

Profile the implementation in sorted_list.py and fix every performance bottleneck you find.
After optimising, make sure the implementation is fully correct — all documented behaviour
must hold, including edge cases involving duplicate values.

Do not change the public interface (method names and signatures stay the same).
