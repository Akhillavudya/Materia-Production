"""Data-access layer.

Repositories own all SQLAlchemy query construction so that routes and services
never embed raw `select(...)` statements. Each function takes an `AsyncSession`
and is responsible only for persistence — never for HTTP concerns.
"""
