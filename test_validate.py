#!/usr/bin/env python3
"""Tests for guardrails/validate.py shared input validation."""

import pytest
import math
from guardrails.validate import InputValidator, ValidationError, Sex


class TestUnicodeNormalization:
    """Test Unicode normalization."""
    
    def test_curly_quotes_normalized(self):
        """Curly quotes are normalized to straight quotes."""
        assert InputValidator.normalize_unicode("I can't breathe") == "I can't breathe"
        assert InputValidator.normalize_unicode("I can\u2019t breathe") == "I can't breathe"
    
    def test_curly_double_quotes_normalized(self):
        """Curly double quotes are normalized."""
        assert InputValidator.normalize_unicode('\u201Cquoted\u201D') == '"quoted"'
    
    def test_em_dash_normalized(self):
        """Em dash is normalized to hyphen."""
        assert InputValidator.normalize_unicode('test\u2014dash') == 'test-dash'


class TestBooleanParsing:
    """Test boolean parsing with fail-closed behavior."""
    
    def test_true_boolean_accepted(self):
        """True boolean is accepted."""
        assert InputValidator.parse_boolean(True, "test") is True
    
    def test_false_boolean_accepted(self):
        """False boolean is accepted."""
        assert InputValidator.parse_boolean(False, "test") is False
    
    def test_string_true_accepted(self):
        """String 'true' is accepted."""
        assert InputValidator.parse_boolean("true", "test") is True
        assert InputValidator.parse_boolean("True", "test") is True
        assert InputValidator.parse_boolean("TRUE", "test") is True
    
    def test_string_false_accepted(self):
        """String 'false' is accepted."""
        assert InputValidator.parse_boolean("false", "test") is False
        assert InputValidator.parse_boolean("False", "test") is False
    
    def test_string_yes_accepted(self):
        """String 'yes' is accepted as true."""
        assert InputValidator.parse_boolean("yes", "test") is True
        assert InputValidator.parse_boolean("y", "test") is True
    
    def test_string_no_accepted(self):
        """String 'no' is accepted as false."""
        assert InputValidator.parse_boolean("no", "test") is False
        assert InputValidator.parse_boolean("n", "test") is False
    
    def test_numeric_1_accepted(self):
        """Numeric 1 is accepted as true."""
        assert InputValidator.parse_boolean(1, "test") is True
    
    def test_numeric_0_accepted(self):
        """Numeric 0 is accepted as false."""
        assert InputValidator.parse_boolean(0, "test") is False
    
    def test_string_false_literal_not_true(self):
        """The string 'false' must NOT be truthy."""
        result = InputValidator.parse_boolean("false", "test")
        assert result is False
        assert result is not True
    
    def test_ambiguous_string_rejected(self):
        """Ambiguous strings are rejected."""
        with pytest.raises(ValidationError, match="ambiguous"):
            InputValidator.parse_boolean("maybe", "test")
    
    def test_invalid_number_rejected(self):
        """Invalid numbers are rejected."""
        with pytest.raises(ValidationError):
            InputValidator.parse_boolean(2, "test")
        with pytest.raises(ValidationError):
            InputValidator.parse_boolean(-1, "test")
    
    def test_none_rejected(self):
        """None is rejected."""
        with pytest.raises(ValidationError):
            InputValidator.parse_boolean(None, "test")


class TestNumberParsing:
    """Test number parsing with strict validation."""
    
    def test_positive_int_accepted(self):
        """Positive integer is accepted."""
        assert InputValidator.parse_number(42, "test") == 42.0
    
    def test_positive_float_accepted(self):
        """Positive float is accepted."""
        assert InputValidator.parse_number(42.5, "test") == 42.5
    
    def test_numeric_string_accepted(self):
        """Numeric string is parsed."""
        assert InputValidator.parse_number("1000", "test") == 1000.0
        assert InputValidator.parse_number("123.45", "test") == 123.45
    
    def test_zero_rejected_by_default(self):
        """Zero is rejected by default."""
        with pytest.raises(ValidationError, match="cannot be zero"):
            InputValidator.parse_number(0, "test")
    
    def test_zero_accepted_when_allowed(self):
        """Zero is accepted when explicitly allowed."""
        assert InputValidator.parse_number(0, "test", allow_zero=True) == 0.0
    
    def test_negative_rejected_by_default(self):
        """Negative is rejected by default."""
        with pytest.raises(ValidationError, match="cannot be negative"):
            InputValidator.parse_number(-10, "test")
    
    def test_negative_accepted_when_allowed(self):
        """Negative is accepted when explicitly allowed."""
        assert InputValidator.parse_number(-10, "test", allow_negative=True) == -10.0
    
    def test_nan_rejected(self):
        """NaN is rejected."""
        with pytest.raises(ValidationError, match="not finite"):
            InputValidator.parse_number(float('nan'), "test")
    
    def test_infinity_rejected(self):
        """Infinity is rejected."""
        with pytest.raises(ValidationError, match="not finite"):
            InputValidator.parse_number(float('inf'), "test")
        with pytest.raises(ValidationError, match="not finite"):
            InputValidator.parse_number(float('-inf'), "test")
    
    def test_non_numeric_string_rejected(self):
        """Non-numeric string is rejected."""
        with pytest.raises(ValidationError, match="not a valid number"):
            InputValidator.parse_number("abc", "test")
        with pytest.raises(ValidationError, match="not a valid number"):
            InputValidator.parse_number("", "test")
    
    def test_boolean_rejected(self):
        """Boolean is explicitly rejected."""
        with pytest.raises(ValidationError, match="boolean"):
            InputValidator.parse_number(True, "test")
        with pytest.raises(ValidationError, match="boolean"):
            InputValidator.parse_number(False, "test")


class TestSexParsing:
    """Test sex field parsing and normalization."""
    
    def test_m_accepted(self):
        """'M' is accepted."""
        assert InputValidator.parse_sex("M", "sex") == Sex.MALE
    
    def test_f_accepted(self):
        """'F' is accepted."""
        assert InputValidator.parse_sex("F", "sex") == Sex.FEMALE
    
    def test_male_accepted(self):
        """'male' is accepted."""
        assert InputValidator.parse_sex("male", "sex") == Sex.MALE
        assert InputValidator.parse_sex("Male", "sex") == Sex.MALE
        assert InputValidator.parse_sex("MALE", "sex") == Sex.MALE
    
    def test_female_accepted(self):
        """'female' is accepted."""
        assert InputValidator.parse_sex("female", "sex") == Sex.FEMALE
        assert InputValidator.parse_sex("Female", "sex") == Sex.FEMALE
    
    def test_man_accepted(self):
        """'man' is accepted."""
        assert InputValidator.parse_sex("man", "sex") == Sex.MALE
        assert InputValidator.parse_sex("Man", "sex") == Sex.MALE
    
    def test_woman_accepted(self):
        """'woman' is accepted."""
        assert InputValidator.parse_sex("woman", "sex") == Sex.FEMALE
        assert InputValidator.parse_sex("Woman", "sex") == Sex.FEMALE
    
    def test_invalid_string_rejected(self):
        """Invalid string is rejected."""
        with pytest.raises(ValidationError, match="not recognized"):
            InputValidator.parse_sex("other", "sex")
        with pytest.raises(ValidationError, match="not recognized"):
            InputValidator.parse_sex("X", "sex")
    
    def test_non_string_rejected(self):
        """Non-string is rejected."""
        with pytest.raises(ValidationError, match="must be a string"):
            InputValidator.parse_sex(1, "sex")


class TestRequireField:
    """Test required field validation."""
    
    def test_present_field_returned(self):
        """Present field is returned."""
        data = {"key": "value"}
        assert InputValidator.require_field(data, "key") == "value"
    
    def test_missing_field_rejected(self):
        """Missing field is rejected."""
        data = {}
        with pytest.raises(ValidationError, match="missing"):
            InputValidator.require_field(data, "key")
    
    def test_none_value_rejected(self):
        """None value is rejected."""
        data = {"key": None}
        with pytest.raises(ValidationError, match="is None"):
            InputValidator.require_field(data, "key")


class TestUserFieldsValidation:
    """Test complete user fields validation."""
    
    def test_valid_user_accepted(self):
        """Valid user data is accepted and normalized."""
        user = {
            "sex": "M",
            "weight_kg": 80,
            "age": 30,
            "height_cm": 180
        }
        validated = InputValidator.validate_user_fields(user)
        assert validated["sex"] == Sex.MALE
        assert validated["sex_str"] == "M"
        assert validated["weight_kg"] == 80.0
        assert validated["age"] == 30
        assert validated["height_cm"] == 180.0
        assert validated["medical_clearance"] is False
    
    def test_medical_clearance_true_respected(self):
        """Medical clearance true is respected."""
        user = {
            "sex": "F",
            "weight_kg": 60,
            "age": 25,
            "height_cm": 165,
            "medical_clearance": True
        }
        validated = InputValidator.validate_user_fields(user)
        assert validated["medical_clearance"] is True
    
    def test_string_numbers_parsed(self):
        """String numbers are parsed."""
        user = {
            "sex": "female",
            "weight_kg": "65.5",
            "age": "28",
            "height_cm": "170"
        }
        validated = InputValidator.validate_user_fields(user)
        assert validated["weight_kg"] == 65.5
        assert validated["age"] == 28
        assert validated["height_cm"] == 170.0
    
    def test_missing_sex_rejected(self):
        """Missing sex is rejected."""
        user = {"weight_kg": 80, "age": 30, "height_cm": 180}
        with pytest.raises(ValidationError, match="sex"):
            InputValidator.validate_user_fields(user)
    
    def test_missing_weight_rejected(self):
        """Missing weight is rejected."""
        user = {"sex": "M", "age": 30, "height_cm": 180}
        with pytest.raises(ValidationError, match="weight_kg"):
            InputValidator.validate_user_fields(user)
    
    def test_missing_age_rejected(self):
        """Missing age is rejected."""
        user = {"sex": "M", "weight_kg": 80, "height_cm": 180}
        with pytest.raises(ValidationError, match="age"):
            InputValidator.validate_user_fields(user)
    
    def test_missing_height_rejected(self):
        """Missing height is rejected."""
        user = {"sex": "M", "weight_kg": 80, "age": 30}
        with pytest.raises(ValidationError, match="height_cm"):
            InputValidator.validate_user_fields(user)
    
    def test_zero_weight_rejected(self):
        """Zero weight is rejected."""
        user = {"sex": "M", "weight_kg": 0, "age": 30, "height_cm": 180}
        with pytest.raises(ValidationError, match="weight_kg"):
            InputValidator.validate_user_fields(user)
    
    def test_negative_age_rejected(self):
        """Negative age is rejected."""
        user = {"sex": "M", "weight_kg": 80, "age": -5, "height_cm": 180}
        with pytest.raises(ValidationError, match="age"):
            InputValidator.validate_user_fields(user)


class TestPlanValidation:
    """Test plan-level validation."""
    
    def test_empty_plan_rejected(self):
        """Empty plan is rejected."""
        with pytest.raises(ValidationError, match="empty"):
            InputValidator.validate_plan_not_empty({})
    
    def test_plan_with_user_accepted(self):
        """Plan with user section is accepted."""
        plan = {"user": {"sex": "M"}}
        InputValidator.validate_plan_not_empty(plan)
    
    def test_plan_with_nutrition_accepted(self):
        """Plan with nutrition section is accepted."""
        plan = {"nutrition": {"calories": 2000}}
        InputValidator.validate_plan_not_empty(plan)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
