# CLAUDE.md - Project Guidelines & Constraints

## 1. Git Workflow & Commit Conventions
* **Strict Attribution Rule:** Never add `Co-Authored-By: Claude` or any form of AI attribution to commit messages. 
* **Execution Flow:** Do not assume git commands. Present the exact git commands you intend to run to the user, and wait for explicit confirmation or user-provided commands before executing any commit or push.
* **Secret & Leak Prevention:** Never stage or commit `.env` files, configuration keys, or local `storage/` directories. Double-check for accidental nested `.git` folders before pushing to remote repositories.

## 2. LLM Provider Infrastructure
* **Default Stack:** Always default to free LLM providers. Use **Gemini** as the primary provider.
* **Resilience Fallback:** Implement and respect a **Gemini → Ollama** fallback pipeline to gracefully handle rate limits ($429$ errors) and infrastructure interruptions.
* **API Restrictions:** Do not use the native Anthropic/Claude API for tool-calling or feature implementations unless explicitly requested by the user.

## 3. Engineering & Refactoring Standards
* **Incremental Restructuring:** When executing sweeping architectural changes (e.g., consolidating modules or refactoring services), break the work down into smaller, independently verifiable steps to prevent loose ends.
* **Post-Change Verification:** Always verify imports, run local tests, and check critical flows (e.g., timezone-aware vs. naive datetime consistency, file storage paths, database connections) after editing files.
* **Clean Code:** Actively identify and remove dead or deprecated code blocks during refactors to keep the codebase tight and maintainable.

## 4. Explanation & Reporting Style
* **Dual Focus:** Treat every session as both a software delivery and a learning session. 
* **Per-File Change Notes:** After creating or editing ANY file, give a 2-line note **in the chat reply** (NOT as comments inside the code file) — line 1: *what* changed, line 2: *why / what it does* — so the user learns from every edit. Keep code comments matching the surrounding file's existing style/density.
* **Beginner-Friendly Summaries:** Whenever running machine learning experiments, analyzing metrics, or delivering complex feature blocks, pair the technical output with a plain-language, beginner-friendly explanation.
* **Signal Analysis:** Explicitly highlight data insights, performance trends, and signals for overfitting or underfitting in training/evaluation results.