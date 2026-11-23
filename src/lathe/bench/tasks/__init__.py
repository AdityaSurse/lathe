"""30 coding and tool-calling benchmark tasks for the Lathe mini-bench evaluation harness."""

from __future__ import annotations

from lathe.bench.models import BenchTask

ALL_BENCH_TASKS: list[BenchTask] = [
    # --- Python Tasks (1-20) ---
    BenchTask(
        id="py_fib",
        name="Fibonacci Number",
        language="python",
        entry_point="fibonacci",
        prompt=(
            "Write a Python function `fibonacci(n: int) -> int` that returns the n-th "
            "Fibonacci number (where F(0)=0, F(1)=1)."
        ),
        test_code="""
assert fibonacci(0) == 0
assert fibonacci(1) == 1
assert fibonacci(7) == 13
assert fibonacci(10) == 55
""",
    ),
    BenchTask(
        id="py_palindrome",
        name="Valid Palindrome",
        language="python",
        entry_point="is_palindrome",
        prompt=(
            "Write a Python function `is_palindrome(s: str) -> bool` returning True if "
            "s is a palindrome, ignoring non-alphanumeric characters and case."
        ),
        test_code="""
assert is_palindrome("A man, a plan, a canal: Panama") is True
assert is_palindrome("race a car") is False
assert is_palindrome(" ") is True
assert is_palindrome("0P") is False
""",
    ),
    BenchTask(
        id="py_two_sum",
        name="Two Sum",
        language="python",
        entry_point="two_sum",
        prompt=(
            "Write a Python function `two_sum(nums: list[int], target: int) -> "
            "list[int]` returning indices of the two numbers that add up to target."
        ),
        test_code="""
res1 = two_sum([2, 7, 11, 15], 9)
assert sorted(res1) == [0, 1]
res2 = two_sum([3, 2, 4], 6)
assert sorted(res2) == [1, 2]
res3 = two_sum([3, 3], 6)
assert sorted(res3) == [0, 1]
""",
    ),
    BenchTask(
        id="py_merge_intervals",
        name="Merge Intervals",
        language="python",
        entry_point="merge_intervals",
        prompt=(
            "Write a Python function `merge_intervals(intervals: list[list[int]]) -> "
            "list[list[int]]` that merges all overlapping intervals."
        ),
        test_code="""
assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
assert merge_intervals([[1,4],[4,5]]) == [[1,5]]
assert merge_intervals([]) == []
""",
    ),
    BenchTask(
        id="py_valid_parentheses",
        name="Valid Parentheses",
        language="python",
        entry_point="is_valid_parentheses",
        prompt=(
            "Write a Python function `is_valid_parentheses(s: str) -> bool` that "
            "determines if brackets '()', '{}', '[]' are closed in correct order."
        ),
        test_code="""
assert is_valid_parentheses("()") is True
assert is_valid_parentheses("()[]{}") is True
assert is_valid_parentheses("(]") is False
assert is_valid_parentheses("([)]") is False
assert is_valid_parentheses("{[]}") is True
""",
    ),
    BenchTask(
        id="py_binary_search",
        name="Binary Search",
        language="python",
        entry_point="binary_search",
        prompt=(
            "Write a Python function `binary_search(nums: list[int], target: int) -> "
            "int` returning the index of target in sorted nums, or -1."
        ),
        test_code="""
assert binary_search([-1,0,3,5,9,12], 9) == 4
assert binary_search([-1,0,3,5,9,12], 2) == -1
assert binary_search([5], 5) == 0
assert binary_search([], 5) == -1
""",
    ),
    BenchTask(
        id="py_flatten_list",
        name="Flatten Nested List",
        language="python",
        entry_point="flatten_list",
        prompt=(
            "Write a Python function `flatten_list(nested: list) -> list` that flattens "
            "an arbitrarily nested list of items into a flat list."
        ),
        test_code="""
assert flatten_list([1, [2, [3, 4], 5], 6]) == [1, 2, 3, 4, 5, 6]
assert flatten_list([[], [[], 1]]) == [1]
assert flatten_list([]) == []
""",
    ),
    BenchTask(
        id="py_top_k",
        name="Top K Frequent Elements",
        language="python",
        entry_point="top_k_frequent",
        prompt=(
            "Write a Python function `top_k_frequent(nums: list[int], k: int) -> "
            "list[int]` returning the k most frequent elements."
        ),
        test_code="""
res = top_k_frequent([1,1,1,2,2,3], 2)
assert set(res) == {1, 2}
assert top_k_frequent([1], 1) == [1]
""",
    ),
    BenchTask(
        id="py_longest_common_prefix",
        name="Longest Common Prefix",
        language="python",
        entry_point="longest_common_prefix",
        prompt=(
            "Write a Python function `longest_common_prefix(strs: list[str]) -> str` "
            "finding the longest common prefix among a list of strings."
        ),
        test_code="""
assert longest_common_prefix(["flower","flow","flight"]) == "fl"
assert longest_common_prefix(["dog","racecar","car"]) == ""
assert longest_common_prefix([]) == ""
assert longest_common_prefix(["interspecies","interstellar","interstate"]) == "inters"
""",
    ),
    BenchTask(
        id="py_roman_to_int",
        name="Roman to Integer",
        language="python",
        entry_point="roman_to_int",
        prompt=(
            "Write a Python function `roman_to_int(s: str) -> int` converting a Roman "
            "numeral string (I, V, X, L, C, D, M) to an integer."
        ),
        test_code="""
assert roman_to_int("III") == 3
assert roman_to_int("LVIII") == 58
assert roman_to_int("MCMXCIV") == 1994
""",
    ),
    BenchTask(
        id="py_evaluate_rpn",
        name="Evaluate Reverse Polish Notation",
        language="python",
        entry_point="eval_rpn",
        prompt=(
            "Write a Python function `eval_rpn(tokens: list[str]) -> int` evaluating an "
            "arithmetic expression in Reverse Polish Notation (+, -, *, /)."
        ),
        test_code="""
assert eval_rpn(["2", "1", "+", "3", "*"]) == 9
assert eval_rpn(["4", "13", "5", "/", "+"]) == 6
""",
    ),
    BenchTask(
        id="py_count_vowels",
        name="Count Vowels",
        language="python",
        entry_point="count_vowels",
        prompt=(
            "Write a Python function `count_vowels(s: str) -> int` counting vowels (a, "
            "e, i, o, u case-insensitive) in a string."
        ),
        test_code="""
assert count_vowels("Hello World") == 3
assert count_vowels("AEIOU") == 5
assert count_vowels("rhythm") == 0
assert count_vowels("") == 0
""",
    ),
    BenchTask(
        id="py_matrix_transpose",
        name="Matrix Transpose",
        language="python",
        entry_point="transpose",
        prompt=(
            "Write a Python function `transpose(matrix: list[list[int]]) -> "
            "list[list[int]]` returning the transposed matrix."
        ),
        test_code="""
assert transpose([[1,2,3],[4,5,6]]) == [[1,4],[2,5],[3,6]]
assert transpose([[1,2],[3,4]]) == [[1,3],[2,4]]
assert transpose([]) == []
""",
    ),
    BenchTask(
        id="py_missing_number",
        name="Missing Number",
        language="python",
        entry_point="missing_number",
        prompt=(
            "Write a Python function `missing_number(nums: list[int]) -> int` returning "
            "the only number in range [0, n] missing from nums."
        ),
        test_code="""
assert missing_number([3,0,1]) == 2
assert missing_number([0,1]) == 2
assert missing_number([9,6,4,2,3,5,7,0,1]) == 8
""",
    ),
    BenchTask(
        id="py_anagrams",
        name="Group Anagrams",
        language="python",
        entry_point="group_anagrams",
        prompt=(
            "Write a Python function `group_anagrams(words: list[str]) -> "
            "list[list[str]]` grouping anagrams together."
        ),
        test_code="""
res = group_anagrams(["eat","tea","tan","ate","nat","bat"])
normalized = sorted([sorted(g) for g in res])
expected = sorted([sorted(["bat"]), sorted(["nat","tan"]), sorted(["ate","eat","tea"])])
assert normalized == expected
""",
    ),
    BenchTask(
        id="py_max_subarray",
        name="Maximum Subarray",
        language="python",
        entry_point="max_subarray",
        prompt=(
            "Write a Python function `max_subarray(nums: list[int]) -> int` finding the "
            "contiguous subarray with the largest sum."
        ),
        test_code="""
assert max_subarray([-2,1,-3,4,-1,2,1,-5,4]) == 6
assert max_subarray([1]) == 1
assert max_subarray([5,4,-1,7,8]) == 23
""",
    ),
    BenchTask(
        id="py_compress_string",
        name="String Compression",
        language="python",
        entry_point="compress_string",
        prompt=(
            "Write a Python function `compress_string(s: str) -> str` performing basic "
            "string compression using counts of repeated characters (e.g. 'aabcccccaaa' "
            "-> 'a2b1c5a3'). Return original if compressed is not shorter."
        ),
        test_code="""
assert compress_string("aabcccccaaa") == "a2b1c5a3"
assert compress_string("abcd") == "abcd"
assert compress_string("") == ""
""",
    ),
    BenchTask(
        id="py_word_frequency",
        name="Word Frequency Counter",
        language="python",
        entry_point="word_frequencies",
        prompt=(
            "Write a Python function `word_frequencies(text: str) -> dict[str, int]` "
            "mapping lowercase alphanumeric words to their frequency."
        ),
        test_code="""
res = word_frequencies("The cat, the dog, and the cat.")
assert res == {"the": 3, "cat": 2, "dog": 1, "and": 1}
assert word_frequencies("") == {}
""",
    ),
    BenchTask(
        id="py_is_prime",
        name="Primality Test",
        language="python",
        entry_point="is_prime",
        prompt=(
            "Write a Python function `is_prime(n: int) -> bool` returning True if "
            "integer n is a prime number, False otherwise."
        ),
        test_code="""
assert is_prime(1) is False
assert is_prime(2) is True
assert is_prime(17) is True
assert is_prime(25) is False
assert is_prime(-7) is False
""",
    ),
    BenchTask(
        id="py_pascals_triangle",
        name="Pascal's Triangle",
        language="python",
        entry_point="generate_pascals_triangle",
        prompt=(
            "Write a Python function `generate_pascals_triangle(num_rows: int) -> "
            "list[list[int]]` generating the first num_rows of Pascal's triangle."
        ),
        test_code="""
assert generate_pascals_triangle(1) == [[1]]
assert generate_pascals_triangle(5) == [[1],[1,1],[1,2,1],[1,3,3,1],[1,4,6,4,1]]
assert generate_pascals_triangle(0) == []
""",
    ),
    # --- C Tasks (21-27) ---
    BenchTask(
        id="c_reverse_str",
        name="C String Reversal",
        language="c",
        entry_point="reverse_string",
        prompt=(
            "Write a C function `void reverse_string(char *s)` that reverses a "
            "null-terminated string in place."
        ),
        test_code="""
#include <stdio.h>
#include <string.h>
#include <assert.h>

void reverse_string(char *s);

int main() {
    char s1[] = "hello";
    reverse_string(s1);
    assert(strcmp(s1, "olleh") == 0);

    char s2[] = "";
    reverse_string(s2);
    assert(strcmp(s2, "") == 0);

    char s3[] = "a";
    reverse_string(s3);
    assert(strcmp(s3, "a") == 0);

    return 0;
}
""",
    ),
    BenchTask(
        id="c_sum_array",
        name="C Array Sum",
        language="c",
        entry_point="sum_array",
        prompt=(
            "Write a C function `int sum_array(const int *arr, int n)` that computes "
            "the sum of an array of n integers."
        ),
        test_code="""
#include <assert.h>

int sum_array(const int *arr, int n);

int main() {
    int a1[] = {1, 2, 3, 4, 5};
    assert(sum_array(a1, 5) == 15);

    int a2[] = {-10, 10, -5, 5};
    assert(sum_array(a2, 4) == 0);

    assert(sum_array(NULL, 0) == 0);
    return 0;
}
""",
    ),
    BenchTask(
        id="c_find_max",
        name="C Array Maximum",
        language="c",
        entry_point="find_max",
        prompt=(
            "Write a C function `int find_max(const int *arr, int n)` returning the "
            "maximum value in an array of n integers (assume n > 0)."
        ),
        test_code="""
#include <assert.h>

int find_max(const int *arr, int n);

int main() {
    int a1[] = {3, 1, 9, 2, 8};
    assert(find_max(a1, 5) == 9);

    int a2[] = {-5, -10, -2, -8};
    assert(find_max(a2, 4) == -2);

    int a3[] = {42};
    assert(find_max(a3, 1) == 42);
    return 0;
}
""",
    ),
    BenchTask(
        id="c_is_prime",
        name="C Primality Check",
        language="c",
        entry_point="c_is_prime",
        prompt=(
            "Write a C function `int c_is_prime(int n)` returning 1 if integer n is "
            "prime, 0 otherwise."
        ),
        test_code="""
#include <assert.h>

int c_is_prime(int n);

int main() {
    assert(c_is_prime(1) == 0);
    assert(c_is_prime(2) == 1);
    assert(c_is_prime(17) == 1);
    assert(c_is_prime(25) == 0);
    assert(c_is_prime(-3) == 0);
    return 0;
}
""",
    ),
    BenchTask(
        id="c_factorial",
        name="C Factorial",
        language="c",
        entry_point="factorial",
        prompt="Write a C function `long long factorial(int n)` computing n! for n >= 0.",
        test_code="""
#include <assert.h>

long long factorial(int n);

int main() {
    assert(factorial(0) == 1LL);
    assert(factorial(1) == 1LL);
    assert(factorial(5) == 120LL);
    assert(factorial(10) == 3628800LL);
    return 0;
}
""",
    ),
    BenchTask(
        id="c_count_char",
        name="C Character Count",
        language="c",
        entry_point="count_char",
        prompt=(
            "Write a C function `int count_char(const char *str, char c)` counting "
            "occurrences of character c in string str."
        ),
        test_code="""
#include <assert.h>

int count_char(const char *str, char c);

int main() {
    assert(count_char("banana", 'a') == 3);
    assert(count_char("banana", 'z') == 0);
    assert(count_char("", 'a') == 0);
    return 0;
}
""",
    ),
    BenchTask(
        id="c_gcd",
        name="C Greatest Common Divisor",
        language="c",
        entry_point="gcd",
        prompt=(
            "Write a C function `int gcd(int a, int b)` calculating the greatest common "
            "divisor using the Euclidean algorithm."
        ),
        test_code="""
#include <assert.h>

int gcd(int a, int b);

int main() {
    assert(gcd(48, 18) == 6);
    assert(gcd(101, 10) == 1);
    assert(gcd(20, 100) == 20);
    return 0;
}
""",
    ),
    # --- Tool Calling / Structured Output Tasks (28-30) ---
    BenchTask(
        id="tool_weather",
        name="Weather Tool Call",
        language="tool",
        entry_point="get_weather",
        prompt=(
            "You have access to a tool named `get_weather`. Call it with arguments: "
            "city='Tokyo', units='celsius'. Emit standard <tool_call> JSON."
        ),
        test_code="",
        is_tool_task=True,
        expected_tool="get_weather",
        expected_args={"city": "Tokyo", "units": "celsius"},
    ),
    BenchTask(
        id="tool_read_file",
        name="Read File Tool Call",
        language="tool",
        entry_point="read_file",
        prompt=(
            "Call the tool `read_file` with arguments: path='src/main.py', "
            "start_line=10, end_line=20. Return the <tool_call> block."
        ),
        test_code="",
        is_tool_task=True,
        expected_tool="read_file",
        expected_args={"path": "src/main.py", "start_line": 10, "end_line": 20},
    ),
    BenchTask(
        id="tool_calculator",
        name="Calculator Tool Call",
        language="tool",
        entry_point="calculator",
        prompt=(
            "Call the tool `calculator` with arguments: expression='(45 * 12) + 34'. "
            "Return the <tool_call> block."
        ),
        test_code="",
        is_tool_task=True,
        expected_tool="calculator",
        expected_args={"expression": "(45 * 12) + 34"},
    ),
]
