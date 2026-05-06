# Gemini Refinements: Review of wirestudio

## Architectural Improvements
* **Async IO for the Backend API:** Currently, `wirestudio/api/app.py` has synchronous endpoints. While `fastapi` allows sync handlers, moving to `async def` and utilizing an async HTTP client (like `httpx.AsyncClient`) for fleet communication and agent streaming would improve scalability and throughput under load.
* **Separation of Concerns:** The backend API handles routing, error handling, and some business logic directly inside `app.py` (e.g., calling `render_yaml`, `generate_skidl`, filtering components, checking permissions/env vars). Moving this logic out to service functions or dependency injection would make the codebase more maintainable and testable.
* **State Management:** Currently file-backed at `designs/` and `sessions/`. The `START.md` mentions multi-writer state backends for replication as future work. Transitioning from local JSON/JSONL files to an abstract Data Access Layer (DAL) backed by SQLite (via SQLAlchemy or SQLModel) or another relational DB would pave the way for this.

## Code and Inefficiencies
* **Refining Agent Streaming Logic:** `stream_turn_events` in `wirestudio/agent/agent.py` handles Claude API interactions, state management, SSE formatting, and tool execution all in one function. Refactoring into smaller, decoupled generators would improve readability and testability.
* **Model Duplication/Overlap:** `wirestudio.api.schemas` explicitly mentions it's separate from `wirestudio.model` to allow independent evolution, but there's a lot of manual mapping overhead (e.g., `_board_summary`, `_component_summary` in `app.py`). Using `model_validate` or standardizing generic serializers could reduce boilerplate.
* **Improve Error Handling:** In the FastAPI app, exceptions like `FileNotFoundError`, `ValueError`, and `ValidationError` are frequently caught and re-raised as `HTTPException` inside each route. A centralized exception handler (`@app.exception_handler`) for these domain-specific errors would clean up the route definitions considerably.

## Documentation Improvements
* **Setup/Developer Guide:** `README.md` and `START.md` are quite comprehensive, but extracting a dedicated developer onboarding guide (e.g., `docs/DEVELOPMENT.md`) could reduce the noise in `README.md`, making it more focused on users and features.
* **Document the API Schemas:** Use Pydantic's `Field(description="...")` more extensively so that the generated `/docs` (Swagger UI) provides detailed descriptions for every attribute without requiring users to read the Python source code.
* **Consistent TODO Tracking:** Currently, TODOs are scattered as code comments (`# TODO:`, `# TODO(0.x):`). Moving these to a proper issue tracker or keeping them organized in a central project board/markdown file would prevent them from getting lost.

## Potential Security Gaps
* **CORS Policy:** `CORSMiddleware` in `app.py` allows all headers (`allow_headers=["*"]`) and explicitly allows local UI addresses. While fine for local dev, it lacks a configurable list of allowed origins via environment variables for production deployments.
* **Missing Rate Limiting:** The API lacks rate limiting, especially on `/agent/turn` and `/agent/stream`. This could lead to Anthropic API key exhaustion and financial costs if exposed publicly. Rate limiting and potentially authentication should be added if hosted outside of a strictly local/trusted environment.
* **Secret Handling in CI/Docker:** Make sure secrets like `ANTHROPIC_API_KEY` are strictly passed as environment variables and never accidentally logged (e.g., logging exceptions that might contain raw API requests/responses). The `docker run` commands and Kubernetes manifests correctly use ENV vars and Secrets, but application-level logging should be verified.

## General Cleanup
* **Replace Prints with Logging:** Ensure standard Python `logging` (or structlog) is used everywhere instead of direct `print` statements or basic string dumps, especially during error handling or agent interactions.
* **Test Coverage for Edge Cases:** Expand tests for `wirestudio/agent/agent.py` to cover more failure modes, such as when Anthropic API rate limits or connection errors occur.

## Proposed Development Plan (Bite-Size PRs)

### 1. Refactor Error Handling & Validation Boilerplate
- **Goal:** Clean up `wirestudio/api/app.py`.
- **Action:** Introduce global exception handlers (e.g., `@app.exception_handler(FileNotFoundError)`) to remove repetitive `try/except` boilerplate from route handlers. Update routes to raise domain exceptions and let the handler map them to 404/422 HTTP responses.

### 2. Implement Async API & Fleet Client
- **Goal:** Improve API throughput and scalability.
- **Action:** Migrate `app.py` endpoints to `async def`. Rewrite `FleetClient` in `wirestudio/fleet/client.py` to use `httpx.AsyncClient` instead of the synchronous `requests` or `httpx` client.

### 3. API Rate Limiting & Configurable CORS
- **Goal:** Security hardening for public/production use.
- **Action:** Add a rate-limiting middleware (e.g., using `slowapi`) to protect the `/agent` endpoints. Move CORS origins to an environment variable (e.g., `WIRESTUDIO_ALLOWED_ORIGINS`) to replace hardcoded localhost origins.

### 4. Database Abstraction for State Management
- **Goal:** Pave the way for multi-writer support (as per `START.md`).
- **Action:** Define an abstract interface for `SessionStore` and `DesignStore`. Create a SQLite implementation as an alternative to the current JSON/JSONL file-backed stores.

### 5. Agent Streaming Refactoring
- **Goal:** Improve code maintainability in `wirestudio/agent/agent.py`.
- **Action:** Break down `stream_turn_events` into distinct, smaller functions (e.g., one for managing the Claude API stream, one for executing tools, one for persisting state).
