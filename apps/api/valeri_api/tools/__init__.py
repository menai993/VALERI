"""The safe tool catalog (M9): how the model touches data — and the only way.

Every tool is typed (Pydantic in/out), RBAC-checked, audited (app.tool_call_log),
and gets its data exclusively from SQL / the semantic layer. No tool ever returns
a number the model computed (CLAUDE.md "How the model touches data").
"""
