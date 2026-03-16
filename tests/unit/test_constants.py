"""Unit tests for src.constants."""

import json

from src.constants import DEFAULT_TEMPLATE_JSON


class TestDefaultTemplateJson:
    def test_default_template_json_is_valid_json(self):
        parsed = json.loads(DEFAULT_TEMPLATE_JSON)
        assert parsed["name"] == "mytemplate"
        assert parsed["categories"] == ["Perso"]

    def test_default_template_json_keeps_literal_formatting(self):
        assert '  "constants": [' in DEFAULT_TEMPLATE_JSON
        assert '    { "marginLeft": 120 },' in DEFAULT_TEMPLATE_JSON
