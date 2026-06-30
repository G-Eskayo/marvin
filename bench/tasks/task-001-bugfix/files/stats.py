def median(nums):
    nums.sort()              # bug: mutates caller's list
    n = len(nums)
    return nums[n // 2]      # bug: wrong for even-length lists


def mean(nums):
    return sum(nums) / len(nums)
