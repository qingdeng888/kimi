"""测试 JSON 修复功能"""

import pytest
from app.api.toolcall import _repair_json


class TestJSONRepair:
    """测试 JSON 修复机制"""

    def test_repair_valid_json(self):
        """有效的 JSON 应该直接返回"""
        text = '{"city": "Beijing", "unit": "celsius"}'
        result = _repair_json(text)
        assert result == text

    def test_repair_single_quotes(self):
        """修复单引号 JSON"""
        text = "{'city': 'Beijing', 'unit': 'celsius'}"
        result = _repair_json(text)
        assert '"city"' in result
        assert '"Beijing"' in result
        assert '"celsius"' in result
        # 验证是有效的 JSON
        import json
        parsed = json.loads(result)
        assert parsed["city"] == "Beijing"
        assert parsed["unit"] == "celsius"

    def test_repair_trailing_comma_object(self):
        """修复对象中的尾部逗号"""
        text = '{"city": "Beijing", "unit": "celsius",}'
        result = _repair_json(text)
        assert result == '{"city": "Beijing", "unit": "celsius"}'

    def test_repair_trailing_comma_array(self):
        """修复数组中的尾部逗号"""
        text = '["item1", "item2",]'
        result = _repair_json(text)
        assert result == '["item1", "item2"]'

    def test_repair_combined(self):
        """修复单引号和尾部逗号组合"""
        text = "{'city': 'Beijing', 'days': 3,}"
        result = _repair_json(text)
        import json
        parsed = json.loads(result)
        assert parsed["city"] == "Beijing"
        assert parsed["days"] == 3

    def test_repair_empty_string(self):
        """空字符串应该返回空"""
        assert _repair_json("") == ""
        assert _repair_json("   ") == ""

    def test_repair_invalid_json(self):
        """无法修复的 JSON 返回空字符串"""
        text = "{invalid json without quotes}"
        result = _repair_json(text)
        assert result == ""

    def test_repair_nested_object(self):
        """修复嵌套对象"""
        text = "{'user': {'name': 'Alice', 'age': 30,}, 'active': true,}"
        result = _repair_json(text)
        import json
        parsed = json.loads(result)
        assert parsed["user"]["name"] == "Alice"
        assert parsed["user"]["age"] == 30
        assert parsed["active"] is True
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
