"""U1 — AI-Gateway: OpenAI-compatible LLM proxy that agents call instead of the
LLM directly. Forwards to a configurable upstream (default: host llama-swap).

The package `__init__` is intentionally light (no FastAPI import) so the pure
logic submodules (routing, headers, errors_map, models_augment) can be imported
and tested without the web framework. Import the app explicitly:

    from caduceus.aigateway.app import build_aigateway_app
"""
