import pytest_asyncio  # noqa: F401

# pytest-asyncio: enable function-scope async tests
import pytest

def pytest_collection_modifyitems(config, items):
    for item in items:
        if "asyncio" in item.keywords:
            continue
        # Auto-mark async test funcs (just in case)
