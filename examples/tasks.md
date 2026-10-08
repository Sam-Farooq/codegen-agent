# Tasks used while building this

Kept because the failures are more informative than the successes.

## Passes first time, reliably

- Parse an ISO 8601 duration into seconds, with tests.
- An LRU cache with a max size, with tests for eviction order.

## Needs one or two repairs

- A retry decorator with exponential backoff and jitter. Round one almost
  always sleeps for real and the test takes 30 seconds. The repair injects a
  clock.
- Parse a CSV with inconsistent quoting into typed rows. Round one reaches for
  `str.split(",")`. The edge case in the plan catches it.

## Circles and exhausts the budget

- A thread-safe bounded queue with timeouts. It finds a deadlock, fixes the
  deadlock, reintroduces the race, and loops. Four rounds is not enough, and
  eight did not help either: it alternates between the same two wrong answers.
  This is the clearest argument for a critic that reads the history rather than
  only the current files.
- Anything needing a third-party package. The sandbox has no network and the
  coder prompt says so, but it reaches for `requests` about one time in ten.
