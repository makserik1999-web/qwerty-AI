# Project Memory — Anyq refactoring rules

These are the standing rules for the ongoing refactoring of the Anyq
Python project (a LangGraph-like agent that generates Manim animations
via LLM). Work is done in parts. These rules apply to the whole process.
**If you have no explicit task yet, DO NOT change or write any code.**

## Rules

1. **REFACTOR WITHOUT BEHAVIOR CHANGE.** Code must work exactly the same.
   No improvements, optimizations, or fixes other than those explicitly
   listed in the task.

2. **DO NOT RENAME** existing functions, variables, state keys, or
   environment variables. External imports depend on them.

3. **DON'T TOUCH anything outside the current task.** Files and functions
   not named in the task stay as they are.

4. **KEEP COMMENTS VERBATIM.** They describe real bugs that took time to
   find (keepalive, Cyrillic in Tex, 503 from Gemini).

5. If you notice a bug or oddity — **WRITE ABOUT IT AT THE END OF THE
   ANSWER, but DO NOT FIX it.** A silently-fixed bug breaks our
   measurements.

6. **No new dependencies.** Python 3.11, keep async signatures.

7. **Return the FULL contents** of every created/modified file — not diffs,
   not snippets with "// rest unchanged".

8. At the end of the answer list: which files you created, what you moved
   from where, and what you could not move and why.

## Related project info

- Project root: `C:\Users\ASUS\Desktop\rspc\qwerty-AI`
- Agent code: `agent/` (incl. `science_manim_graph_agent.py`, `agent_ws_client.py`)
- Backend: `backend/` (FastAPI), Frontend: `frontend/` (React/Vite)
