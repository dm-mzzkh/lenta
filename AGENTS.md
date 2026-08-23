# Language

All comments, docstrings, log messages, user-facing strings (CLI output,
error messages, MCP tool descriptions), and documentation must be in English.

Exception: functional data that targets lenta.com's Russian catalog stays in
Russian — search query examples in tests and scripts (e.g. `"молоко"`),
fixture/expected values that mirror real API responses (e.g. `"Мука MAKFA 2кг"`),
and Russian API attribute keys parsed in code (`"Описание"`, `"Бренд"`,
`"белки"`, etc.). The API only understands Russian terms; translating those
breaks them.
