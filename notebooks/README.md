# Notebooks — the literate contract

Every notebook here is **literate**: it reads top to bottom as one narrative —
a data story with a beginning (what question this notebook holds open), a
middle (each visual introduced, shown, and read), and an end (what would change
the reading, and when). A reader who never opens a cell's code should still
follow the whole argument.

The rules, enforced by review rather than tooling:

1. **Prose before every visual.** Each chart or table is preceded by a markdown
   cell answering four things: *what question is this asking? how is it
   computed? how do I read it? what would change my mind?*
2. **No orphan code.** A code cell a reader hits without narrative context is a
   defect. Helper cells live at the bottom or are folded into the cell that
   uses them.
3. **Gates render as prose.** A closed gate shows the standing message — "not
   yet: N of M" — in the narrative voice, never a blank or an error. "Not yet"
   is part of the story.
4. **Fabricated data announces itself** loudly at the top of any view showing
   it, every time.
5. **The graph is the only source.** Real-data cells read through
   `flow_analysis.graph.loaders` (or read-only Cypher); fixture cells fold from
   a redirected throwaway store, exactly as the surfaces do.
6. **One notebook, one story.** `flow.py` is the practice narrative (and the
   one permitted dashboard-mirror). `graph.py` is the guide to the graph
   itself. A new story means a new notebook, opened with what it holds open.

Delivery: the agent ensures the server
(`uv run marimo edit notebooks/ -p 2719 --headless --mcp`, backgrounded) and
hands direct links — `http://localhost:2719/?file=flow.py`.
