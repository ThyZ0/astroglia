# Security policy

Astroglia runs locally and reads your Claude Code configuration and project files. Please report vulnerabilities privately through GitHub's **Report a vulnerability** (Security tab), not in public issues.

In scope: anything that lets content from an indexed file, a web page or another local process read or change Astroglia's data, execute code, or reach the local UI API; secret leakage into the database; hooks that could block Claude Code.

Design guarantees to test against: the UI binds 127.0.0.1 and requires a per-run token and a localhost `Host` header; stored text is rendered with `textContent`; `remember` refuses secret-looking text; MCP `env` values are never stored; "Show source" only reveals paths Astroglia recorded itself.
