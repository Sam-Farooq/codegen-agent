# codegen-agent

Give it a task. It plans, writes the files, runs pytest in a throwaway
container, reads the failure, and tries again. It stops when the tests pass
and a second model has reviewed the result, or when the repair budget runs out.

    plan -> write -> test -> pass? -> review -> approved? -> done
                       ^       |                   |
                       +-- repair <----------------+

Two exits are not success. "exhausted" means the budget ran out with tests
still red. "rejected" means they went green but the critic blocked and there
was no budget left to act on it. Both are recorded as outcomes rather than
raised, because a run that tried four times and failed is useful data.

## The sandbox is the point

Nothing the model writes runs on the host. The loop's normal operating state
is running code that is wrong, and some fraction of wrong code deletes things.

Each attempt gets a fresh container: no network, read-only root with one small
writable tmpfs, memory cap, CPU quota, all capabilities dropped, running as
nobody. Two are worth calling out. pids_limit is the one people leave off, and
a fork bomb is an ordinary thing for a confused model to emit. memswap_limit
has to equal mem_limit, or the memory cap just pushes the process into swap
and the timeout fires instead, which reads as a completely different bug.

## Two models, deliberately

The coder is Claude and the critic is GPT-4o. Same-model review agrees with
itself far too readily: across the first forty runs with one model on both
ends, the critic approved 38 of its own coder's diffs, and 9 of those failed
the very next test run.

The critic only sees code that already passes, so passing is not the question
it is asked. It is told that finding nothing is a normal outcome, because a
reviewer that always finds something is a reviewer nobody reads.

## The planner has to name edge cases

Plan.edge_cases carries min_length=1. Without that one schema constraint the
planner writes tests that assert the happy path, the repair loop converges on
code that satisfies them, and the result is confidently wrong in exactly the
direction nobody checked. It moved output quality more than any prompt
rewording did.

## Not done

- The critic sees the current files, never the history. For a task that
  oscillates between two wrong answers, the history is the only thing that
  would reveal it.
- No static analysis before execution. Running ruff over the generated files
  first would catch a class of failure without paying for a container start.
- /runs returns immediately and runs the work in a background task, so a
  restart loses anything in flight. This wants a real queue.
