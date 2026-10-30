#!/usr/bin/env python3
"""
Shared input validation for Gainzbot guardrails.

Fails closed: invalid or missing required data blocks processing.
Never uses defaults for missing critical fields.
"""

from typing import Any, Dict, List, Optional, Union
from enum import Enum
import math
import unicodedata


class Sex(Enum):
    """Normalized sex values."""
    MALE = "M"
    FEMALE = "F"


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


class InputValidator:
    """Validates and normalizes user input with fail-closed behavior."""

    @staticmethod
    def normalize_unicode(text: str) -> str:
        """
        Normalize Unicode characters to ASCII equivalents.
        
        Converts curly quotes, em dashes, etc. to straight equivalents
        so input from any device matches patterns consistently.
        
        Args:
            text: Raw text input
            
        Returns:
            Normalized text
        """
        replacements = {
            '\u2018': "'",  # Left single quotation mark
            '\u2019': "'",  # Right single quotation mark
            '\u201C': '"',  # Left double quotation mark
            '\u201D': '"',  # Right double quotation mark
            '\u2013': '-',  # En dash
            '\u2014': '-',  # Em dash
        }
        
        for unicode_char, ascii_char in replacements.items():
            text = text.replace(unicode_char, ascii_char)
        
        return text

    @staticmethod
    def parse_boolean(value: Any, field_name: str) -> bool:
        """
        Parse boolean value with strict fail-closed behavior.
        
        Args:
            value: Value to parse
            field_name: Field name for error messages
            
        Returns:
            Parsed boolean
            
        Raises:
            ValidationError: If value cannot be safely parsed as boolean
        """
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            value_normalized = InputValidator.normalize_unicode(value)
            value_lower = value_normalized.lower().strip()
            
            if value_lower in ["true", "yes", "y", "1"]:
                return True
            if value_lower in ["false", "no", "n", "0"]:
                return False
            
            raise ValidationError(
                f"Field '{field_name}' has ambiguous value '{value}'. "
                f"Must be true/false, yes/no, or boolean."
            )
        
        if isinstance(value, (int, float)):
            if value in [0, 1]:
                return bool(value)
            raise ValidationError(
                f"Field '{field_name}' numeric value {value} cannot be converted to boolean. "
                f"Use 0/1, true/false, or yes/no."
            )
        
        raise ValidationError(
            f"Field '{field_name}' has invalid type {type(value).__name__}. "
            f"Must be boolean, 'true'/'false', or 'yes'/'no'."
        )

    @staticmethod
    def parse_number(
        value: Any,
        field_name: str,
        allow_zero: bool = False,
        allow_negative: bool = False
    ) -> float:
        """
        Parse numeric value with strict validation.
        
        Args:
            value: Value to parse
            field_name: Field name for error messages
            allow_zero: Whether to allow zero values
            allow_negative: Whether to allow negative values
            
        Returns:
            Parsed number as float
            
        Raises:
            ValidationError: If value is not a valid finite positive number
        """
        if isinstance(value, bool):
            raise ValidationError(
                f"Field '{field_name}' is a boolean, not a number."
            )
        
        if isinstance(value, str):
            value = value.strip()
            try:
                parsed = float(value)
            except (ValueError, TypeError):
                raise ValidationError(
                    f"Field '{field_name}' value '{value}' is not a valid number."
                )
        elif isinstance(value, (int, float)):
            parsed = float(value)
        else:
            raise ValidationError(
                f"Field '{field_name}' has invalid type {type(value).__name__}. "
                f"Must be a number."
            )
        
        if not math.isfinite(parsed):
            raise ValidationError(
                f"Field '{field_name}' value {parsed} is not finite (NaN or Infinity)."
            )
        
        if not allow_zero and parsed == 0:
            raise ValidationError(
                f"Field '{field_name}' cannot be zero."
            )
        
        if not allow_negative and parsed < 0:
            raise ValidationError(
                f"Field '{field_name}' cannot be negative (got {parsed})."
            )
        
        if not allow_zero and not allow_negative and parsed <= 0:
            raise ValidationError(
                f"Field '{field_name}' must be positive (got {parsed})."
            )
        
        return parsed

    @staticmethod
    def parse_sex(value: Any, field_name: str = "sex") -> Sex:
        """
        Parse and normalize sex field.
        
        Args:
            value: Sex value to parse
            field_name: Field name for error messages
            
        Returns:
            Normalized Sex enum
            
        Raises:
            ValidationError: If value cannot be mapped to M or F
        """
        if isinstance(value, Sex):
            return value
        
        if not isinstance(value, str):
            raise ValidationError(
                f"Field '{field_name}' must be a string (M/F, male/female, man/woman)."
            )
        
        value_normalized = InputValidator.normalize_unicode(value)
        value_lower = value_normalized.lower().strip()
        
        if value_lower in ["m", "male", "man"]:
            return Sex.MALE
        if value_lower in ["f", "female", "woman"]:
            return Sex.FEMALE
        
        raise ValidationError(
            f"Field '{field_name}' value '{value}' is not recognized. "
            f"Must be M/F, male/female, or man/woman."
        )

    @staticmethod
    def require_field(data: Dict, field_name: str) -> Any:
        """
        Require that a field exists in the data.
        
        Args:
            data: Data dictionary
            field_name: Required field name
            
        Returns:
            Field value
            
        Raises:
            ValidationError: If field is missing
        """
        if field_name not in data:
            raise ValidationError(
                f"Required field '{field_name}' is missing."
            )
        
        value = data[field_name]
        
        if value is None:
            raise ValidationError(
                f"Required field '{field_name}' is None."
            )
        
        return value

    @staticmethod
    def validate_user_fields(user: Dict) -> Dict:
        """
        Validate required user fields.
        
        Args:
            user: User data dictionary
            
        Returns:
            Validated user data with normalized values
            
        Raises:
            ValidationError: If any required field is missing or invalid
        """
        validated = {}
        
        sex_raw = InputValidator.require_field(user, "sex")
        validated["sex"] = InputValidator.parse_sex(sex_raw, "sex")
        validated["sex_str"] = validated["sex"].value
        
        weight_raw = InputValidator.require_field(user, "weight_kg")
        validated["weight_kg"] = InputValidator.parse_number(
            weight_raw, "weight_kg", allow_zero=False, allow_negative=False
        )
        
        age_raw = InputValidator.require_field(user, "age")
        validated["age"] = int(InputValidator.parse_number(
            age_raw, "age", allow_zero=False, allow_negative=False
        ))
        
        height_raw = InputValidator.require_field(user, "height_cm")
        validated["height_cm"] = InputValidator.parse_number(
            height_raw, "height_cm", allow_zero=False, allow_negative=False
        )
        
        if "medical_clearance" in user:
            validated["medical_clearance"] = InputValidator.parse_boolean(
                user["medical_clearance"], "medical_clearance"
            )
        else:
            validated["medical_clearance"] = False
        
        return validated

    @staticmethod
    def normalize_field_names(data: Dict, known_aliases: Dict[str, str]) -> Dict:
        """
        Normalize field names using known aliases.
        
        Args:
            data: Input data dictionary
            known_aliases: Mapping of alias -> canonical field name
            
        Returns:
            Data with normalized field names
            
        Raises:
            ValidationError: If multiple aliases for same field are present
        """
        normalized = {}
        field_sources = {}
        
        for key, value in data.items():
            canonical = known_aliases.get(key.lower(), key)
            
            if canonical in field_sources:
                raise ValidationError(
                    f"Ambiguous input: both '{field_sources[canonical]}' and '{key}' "
                    f"map to '{canonical}'."
                )
            
            normalized[canonical] = value
            field_sources[canonical] = key
        
        return normalized

    @staticmethod
    def validate_plan_not_empty(plan: Dict) -> None:
        """
        Validate that plan is not empty.
        
        Args:
            plan: Plan dictionary
            
        Raises:
            ValidationError: If plan is empty
        """
        if not plan:
            raise ValidationError("Plan is empty. Cannot validate an empty plan.")
        
        if "user" not in plan and "nutrition" not in plan and "training" not in plan and "goals" not in plan:
            raise ValidationError(
                "Plan must contain at least one of: user, nutrition, training, or goals."
            )
