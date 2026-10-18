# codegen-agent

Give it a task. It plans, writes the files, runs pytest in a throwaway
container, reads the failure, and tries again. It stops when the tests pass
and a second model has reviewed the result, or when the repair budget runs out.

    plan -> write -> lint -> test -> pass? -> review -> approved? -> done
                       ^               |                    |
                       +-- repair <----+--------------------+

A ruff finding routes to repair as well, before any container starts.

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

## Ruff before the container

A file that will not parse does not need a container to say so. The expensive
step in a round is the sandbox: an image check, a fresh container, a tar in, a
pytest start. So each file set is written to a temporary directory and checked
with ruff first, and a finding becomes a repair round that costs no container
at all. The test that counts starts for a run whose first draft does not parse
is in tests/test_lint_gate.py: the count was 2, and it is 1.

The rule selection is the decision that matters. Only invalid-syntax, F821,
F822 and F823 are on, the four that name something Python will not resolve
when it reaches that line. Ruff's defaults also report unused and unsorted
imports, and a repair round spent deleting an unused import pays a model call
for a container start that would have passed.

Two smaller ones. noqa comments are ignored, because a repair round can write
`# noqa: F821` and clear the gate without changing anything Python does. And a
ruff that cannot be run reports clean, so the container still decides; the gate
is only allowed to say early what the suite would have said anyway.

A lint round spends a repair round, which bounds the gate: findings that four
repairs cannot fix go to the container, and the ordinary exhausted exit
applies. The files are written to the host for ruff to read, and that is the
one place a generated filename meets a real filesystem. `Path("/tmp/work") /
"/etc/passwd"` is `/etc/passwd`, so every path is resolved against the work
directory first and one that escapes is reported to the repair round instead
of being written.

## Two models, deliberately

The coder is Claude and the critic is GPT-4o. A model reviewing its own
output is scoring text from the distribution it just sampled, so whatever it
was blind to as a writer it is equally blind to as a reader. A different
family does not fix that. It makes the blind spots less likely to coincide.

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
- /runs returns immediately and runs the work in a background task, so a
  restart loses anything in flight. This wants a real queue.
