from langchain_core.prompts import ChatPromptTemplate

PLANNER = ChatPromptTemplate.from_messages([
    ("system",
     ("Break the task into files. Name every file you will create, name the "
      "test file, and list the edge cases the tests must cover. List at least "
      "one edge case that is not the happy path. Do not write code yet.")),
    ("human", "{task}"),
])

CODER = ChatPromptTemplate.from_messages([
    ("system",
     ("Write every file in the plan, complete and runnable. Standard library "
      "and pytest only; the sandbox has no network so nothing can be "
      "installed. Return each file with its full contents, not a diff.")),
    ("human", "Task:\n{task}\n\nPlan:\n{plan}"),
])

REPAIR = ChatPromptTemplate.from_messages([
    ("system",
     ("The tests failed. Read the output, find the cause, and return the full "
      "contents of only the files that need to change.\n\n"
      "Fix the code, not the test. If you are convinced the test itself is "
      "wrong, say so in one line and change it, but that is the exception.")),
    ("human",
     ("Task:\n{task}\n\nCurrent files:\n{files}\n\n"
      "pytest exit {exit_code}:\n{stdout}\n{stderr}\n\n"
      "Attempt {round} of {max_rounds}.")),
])

CRITIC = ChatPromptTemplate.from_messages([
    ("system",
     ("Review code that already passes its tests. Passing is not the question; "
      "you are looking for what the tests did not check.\n\n"
      "Blocking: wrong behaviour on an input the tests miss, a resource that is "
      "never released, an unhandled error path, a security problem.\n"
      "Nit: naming, structure, style.\n\n"
      "Do not block on style. Returning no blocking items is a normal outcome.")),
    ("human", "Task:\n{task}\n\nFiles:\n{files}\n\nEdge cases the plan named:\n{edge_cases}"),
])

# A lint finding arrives before any suite has run, so the repair round cannot
# be shown an exit code and must not be told the tests failed.
LINT_REPAIR = ChatPromptTemplate.from_messages([
    ("system",
     ("Static analysis found problems that will end the test run before a "
      "single test executes. No suite has run yet.\n\n"
      "Each finding is file:line:column, then the rule, then the message. Fix "
      "the cause at that line and return the full contents of only the files "
      "that need to change.\n\n"
      "Do not suppress a finding with a comment; the checker ignores those and "
      "Python ignores them too. Do not restructure anything the findings do "
      "not name.")),
    ("human",
     ("Task:\n{task}\n\nCurrent files:\n{files}\n\n"
      "ruff reported {count} problems:\n{findings}\n\n"
      "Attempt {round} of {max_rounds}.")),
])
