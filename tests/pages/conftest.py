"""Shared fixtures for pages/ AppTest-based integration tests."""

import pytest

import src.templates as tpl


@pytest.fixture(autouse=True)
def clear_template_cache():
    """Flush the st.cache_data cache for load_templates_json before every test.

    Page tests run against real tmp_path directories but often reuse the same
    device name (e.g. "D1"). Without this fixture the Streamlit cache retains
    data from a previous test and causes false results.
    """
    tpl.load_templates_json.clear()
    yield
    tpl.load_templates_json.clear()
