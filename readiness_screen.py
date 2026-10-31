#!/usr/bin/env python3
"""
Readiness screening script for Gainzbot.

Implements PAR-Q+ style readiness and age screening before allowing plan generation.
Identifies medical and safety risks that require clearance or physician consultation.
Uses shared input validation with fail-closed behavior.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
from enum import Enum
import difflib
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError


class ClearanceLevel(Enum):
    """Readiness screening clearance levels."""
    CLEAR = "clear"
    CAUTION = "caution"
    NEEDS_DOCTOR_CLEARANCE = "needs_doctor_clearance"


@dataclass
class ScreeningResult:
    """Result of readiness screening."""
    clearance: ClearanceLevel
    reasons: List[str]
    blocked: bool
    recommendations: List[str]
    subject_hash: str = ""

    def to_dict(self) -> Dict:
        return {
            "clearance": self.clearance.value,
            "reasons": self.reasons,
            "blocked": self.blocked,
            "recommendations": self.recommendations,
            "subject_hash": self.subject_hash,
        }


def subject_hash(source) -> str:
    """Stable id for the person this screen belongs to."""
    from record_confirmation import hash_plan

    payload = {}
    if isinstance(source, dict):
        for key in ("sex", "weight_kg", "age", "height_cm"):
            if key not in source or source.get(key) in (None, ""):
                continue
            value = source[key]
            if key == "sex":
                payload[key] = value.strip() if isinstance(value, str) else value
                continue
            try:
                number = InputValidator.parse_number(value, key, allow_zero=True)
            except ValidationError:
                payload[key] = value
                continue
            payload[key] = int(number) if number == int(number) else number
    return hash_plan(payload)


class ReadinessScreen:
    """Screens users for readiness to begin fitness and nutrition programs."""

    MIN_AGE = 13
    ADULT_AGE = 18
    MAX_AGE = 100
    KNOWN_INTAKE_KEYS = {
        "age",
        "sex",
        "weight_kg",
        "height_cm",
        "parental_consent",
        "par_q",
        "pregnant",
        "pregnancy_clearance",
        "medical_conditions",
        "medical_clearance",
    }

    PAR_Q_RED_FLAGS = [
        "chest_pain_at_rest",
        "chest_pain_during_activity",
        "loss_of_balance_dizziness",
        "loss_of_consciousness",
        "bone_joint_problem_worsened_by_activity",
        "currently_taking_medications",
        "doctor_advised_supervised_only",
    ]

    MEDICAL_CONDITIONS_REQUIRING_CLEARANCE = [
        "heart_disease",
        "high_blood_pressure",
        "hypertension",
        "diabetes",
        "type_2_diabetes",
        "type_1_diabetes",
        "asthma",
        "chronic_illness",
    ]
    
    CONDITION_SYNONYMS = {
        "hypertension": "high_blood_pressure",
        "high bp": "high_blood_pressure",
        "type 2 diabetes": "type_2_diabetes",
        "type 1 diabetes": "type_1_diabetes",
        "t2d": "type_2_diabetes",
        "t1d": "type_1_diabetes",
        "heart condition": "heart_disease",
        "cardiac disease": "heart_disease",
        "cardiovascular disease": "heart_disease",
    }

    NO_CONDITION_WORDS = {"none", "n/a", "na", "no", "nope", "nil", "nothing", ""}
    _CONDITION_SPLIT = re.compile(r"\s*(?:,|&|\band\b)\s*", re.IGNORECASE)

    @staticmethod
    def normalize_condition(condition: str) -> str:
        """
        Normalize medical condition text.
        
        Args:
            condition: Raw condition text
            
        Returns:
            Normalized condition key
        """
        condition_clean = InputValidator.normalize_unicode(condition)
        condition_lower = condition_clean.lower().strip()
        
        if condition_lower in ReadinessScreen.CONDITION_SYNONYMS:
            return ReadinessScreen.CONDITION_SYNONYMS[condition_lower]
        
        condition_key = condition_lower.replace(" ", "_").replace("-", "_")
        return condition_key

    def check_age(self, age_raw, has_parental_consent: bool = False) -> ScreeningResult:
        """Check age requirements."""
        reasons = []
        recommendations = []
        
        try:
            age_value = InputValidator.parse_number(
                age_raw, "age", allow_zero=False, allow_negative=False
            )
        except (ValidationError, ValueError, TypeError) as e:
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=[f"Invalid age: {e}"],
                blocked=True,
                recommendations=["Please provide a valid age."]
            )

        if age_value != int(age_value):
            return self._blocked(
                ["Age must be a whole number of years."],
                ["Please provide age in whole years."],
            )
        age = int(age_value)
        if age > self.MAX_AGE:
            return self._blocked(
                [f"Age {age} is over {self.MAX_AGE} and is not a plausible age."],
                ["Please provide a real age."],
            )
        
        if age < self.MIN_AGE:
            reasons.append(
                f"User is under {self.MIN_AGE} years old."
            )
            recommendations.append(
                f"Users must be at least {self.MIN_AGE} years old."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        if age < self.ADULT_AGE and not has_parental_consent:
            reasons.append(
                f"User is {age} years old (under {self.ADULT_AGE}) without parental consent."
            )
            recommendations.append(
                f"Parental or guardian consent required for users under {self.ADULT_AGE}."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        if age < self.ADULT_AGE and has_parental_consent:
            reasons.append(
                f"User is {age} years old (under {self.ADULT_AGE}) but has parental consent."
            )
            recommendations.append(
                "Youth training program with appropriate modifications required."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.CAUTION,
                reasons=reasons,
                blocked=False,
                recommendations=recommendations
            )
        
        return ScreeningResult(
            clearance=ClearanceLevel.CLEAR,
            reasons=[],
            blocked=False,
            recommendations=[]
        )

    def _yes_no(self, data: Dict, key: str, default: bool = False):
        """Parse a yes/no field with the shared parser. Missing uses default."""
        if key not in data:
            return default, None
        try:
            return InputValidator.parse_boolean(data[key], key), None
        except ValidationError as e:
            return None, str(e)

    def _parse_conditions(self, raw) -> Tuple[List[str], str]:
        """Return condition strings, or an error when the shape is unsafe."""
        if isinstance(raw, dict):
            return [], "medical_conditions must be a list or text, not an object."
        if isinstance(raw, str):
            parts = self._CONDITION_SPLIT.split(raw)
        elif isinstance(raw, list):
            parts = []
            for item in raw:
                if not isinstance(item, str):
                    return [], "medical_conditions contains a value that is not text."
                parts.extend(self._CONDITION_SPLIT.split(item))
        else:
            return [], "medical_conditions has an invalid type."

        conditions = []
        for part in parts:
            text = part.strip()
            if text.lower() in self.NO_CONDITION_WORDS:
                continue
            if text:
                conditions.append(text)
        return conditions, ""

    def _unknown_key_message(self, key: str) -> str:
        suggestion = difflib.get_close_matches(
            str(key).lower(), sorted(self.KNOWN_INTAKE_KEYS), n=1, cutoff=0.6
        )
        if suggestion:
            return f"Unknown key: '{key}' (did you mean '{suggestion[0]}'?)"
        return f"Unknown key: '{key}'"

    def _blocked(self, reasons: List[str], recommendations: List[str]) -> ScreeningResult:
        return ScreeningResult(
            clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
            reasons=reasons,
            blocked=True,
            recommendations=recommendations,
        )

    def check_par_q(self, responses: Dict[str, bool], has_clearance: bool = False) -> ScreeningResult:
        """Check PAR-Q+ style questions. Missing or unknown keys block."""
        if not isinstance(responses, dict):
            return self._blocked(
                ["PAR-Q answers must be a complete set of yes/no responses."],
                ["Please answer every PAR-Q question with yes or no."],
            )

        known = set(self.PAR_Q_RED_FLAGS)
        unknown = [key for key in responses if key not in known]
        missing = [flag for flag in self.PAR_Q_RED_FLAGS if flag not in responses]
        parsed = {}
        parse_errors = []
        for key, value in responses.items():
            if key not in known:
                continue
            if isinstance(value, bool):
                parsed[key] = value
                continue
            try:
                parsed[key] = InputValidator.parse_boolean(value, key)
            except ValidationError as error:
                parse_errors.append(str(error))

        red_flags = [
            flag.replace("_", " ").title()
            for flag in self.PAR_Q_RED_FLAGS
            if parsed.get(flag) is True
        ]
        reasons = []
        recommendations = []
        if red_flags and has_clearance and not (unknown or missing or parse_errors):
            return ScreeningResult(
                clearance=ClearanceLevel.CAUTION,
                reasons=[f"Red flag responses with clearance: {', '.join(red_flags)}"],
                blocked=False,
                recommendations=[
                    "Physician clearance is recorded. Modified programming may be required."
                ],
            )
        if red_flags:
            reasons.append(f"Red flag responses: {', '.join(red_flags)}")
            recommendations.append(
                "Physician clearance required before beginning any exercise program."
            )
        reasons.extend(parse_errors)
        if unknown:
            reasons.append(
                "Unknown PAR-Q key(s): "
                + ", ".join(unknown)
                + ". A typo or missing question blocks screening."
            )
        if missing:
            reasons.append("PAR-Q is incomplete. Missing: " + ", ".join(missing) + ".")
        if unknown or missing or parse_errors:
            recommendations.append("Please answer every PAR-Q question with yes or no.")
        if reasons:
            return self._blocked(reasons, recommendations)

        return ScreeningResult(
            clearance=ClearanceLevel.CLEAR,
            reasons=[],
            blocked=False,
            recommendations=[],
        )

    def check_pregnancy(self, is_pregnant: bool, has_clearance: bool = False) -> ScreeningResult:
        """Check pregnancy status and clearance."""
        reasons = []
        recommendations = []
        
        if is_pregnant and not has_clearance:
            reasons.append("User is pregnant without medical clearance.")
            recommendations.append(
                "Physician clearance required for pregnant individuals. "
                "Exercise during pregnancy requires medical supervision."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        if is_pregnant and has_clearance:
            reasons.append("User is pregnant with medical clearance.")
            recommendations.append(
                "Modified programming required for pregnancy. "
                "Avoid supine exercises after first trimester, monitor intensity carefully."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.CAUTION,
                reasons=reasons,
                blocked=False,
                recommendations=recommendations
            )
        
        return ScreeningResult(
            clearance=ClearanceLevel.CLEAR,
            reasons=[],
            blocked=False,
            recommendations=[]
        )

    def check_medical_conditions(
        self,
        conditions: List[str],
        has_clearance: bool = False
    ) -> ScreeningResult:
        """Check for medical conditions requiring clearance."""
        reasons = []
        recommendations = []
        
        if not conditions:
            return ScreeningResult(
                clearance=ClearanceLevel.CLEAR,
                reasons=[],
                blocked=False,
                recommendations=[]
            )
        
        normalized_conditions = []
        unrecognized_conditions = []
        
        for condition in conditions:
            if not condition or not isinstance(condition, str):
                continue
            
            normalized = self.normalize_condition(condition)
            
            if normalized in self.MEDICAL_CONDITIONS_REQUIRING_CLEARANCE:
                normalized_conditions.append(normalized)
            else:
                unrecognized_conditions.append(condition)
        
        if unrecognized_conditions:
            reasons.append(
                f"Unrecognized medical conditions require review: {', '.join(unrecognized_conditions)}"
            )
            recommendations.append(
                "Please provide more details about these conditions for proper screening."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        if not normalized_conditions:
            return ScreeningResult(
                clearance=ClearanceLevel.CLEAR,
                reasons=[],
                blocked=False,
                recommendations=[]
            )
        
        condition_names = [c.replace("_", " ").title() for c in normalized_conditions]
        
        if not has_clearance:
            reasons.append(
                f"Medical conditions without clearance: {', '.join(condition_names)}"
            )
            recommendations.append(
                "Physician clearance required before beginning exercise with these conditions."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        reasons.append(
            f"Medical conditions with clearance: {', '.join(condition_names)}"
        )
        recommendations.append(
            "Modified programming may be required. Monitor symptoms closely."
        )
        return ScreeningResult(
            clearance=ClearanceLevel.CAUTION,
            reasons=reasons,
            blocked=False,
            recommendations=recommendations
        )

    def screen_intake(self, intake: Dict) -> ScreeningResult:
        """
        Screen complete intake form for readiness.
        
        Args:
            intake: Dictionary containing user intake information
            
        Returns:
            ScreeningResult with overall clearance level and recommendations
        """
        if not isinstance(intake, dict):
            return self._blocked(
                ["Intake must be an object."],
                ["Please resubmit the readiness form."],
            )

        all_reasons = []
        all_recommendations = []
        blocked = False
        highest_level = ClearanceLevel.CLEAR

        def absorb(result: ScreeningResult) -> None:
            nonlocal blocked, highest_level
            if result.clearance == ClearanceLevel.CLEAR:
                return
            all_reasons.extend(result.reasons)
            all_recommendations.extend(result.recommendations)
            blocked = blocked or result.blocked
            if result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
            elif (
                result.clearance == ClearanceLevel.CAUTION
                and highest_level != ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
            ):
                highest_level = ClearanceLevel.CAUTION

        for key in intake:
            if key not in self.KNOWN_INTAKE_KEYS:
                absorb(self._blocked(
                    [self._unknown_key_message(key)],
                    ["Remove or correct unrecognized fields before screening."],
                ))

        if "age" not in intake:
            absorb(self._blocked(
                ["Age is required. There is no default age."],
                ["Please provide your age."],
            ))
        else:
            parental_consent, consent_error = self._yes_no(intake, "parental_consent", False)
            if consent_error:
                absorb(self._blocked([consent_error], ["Please answer parental consent with yes or no."]))
            else:
                absorb(self.check_age(intake["age"], parental_consent))

        medical_clearance, medical_error = self._yes_no(intake, "medical_clearance", False)
        if "par_q" not in intake:
            absorb(self._blocked(
                ["A complete PAR-Q is required."],
                ["Please answer every PAR-Q question with yes or no."],
            ))
        else:
            absorb(self.check_par_q(intake["par_q"], has_clearance=bool(medical_clearance)))

        is_pregnant, pregnant_error = self._yes_no(intake, "pregnant", False)
        pregnancy_clearance, pregnancy_error = self._yes_no(intake, "pregnancy_clearance", False)
        if pregnant_error or pregnancy_error:
            absorb(self._blocked(
                [error for error in (pregnant_error, pregnancy_error) if error],
                ["Please answer pregnancy questions with yes or no."],
            ))
        else:
            absorb(self.check_pregnancy(is_pregnant, pregnancy_clearance))

        if "medical_conditions" not in intake:
            conditions, condition_error = [], ""
        else:
            conditions, condition_error = self._parse_conditions(intake["medical_conditions"])
        if medical_error or condition_error:
            absorb(self._blocked(
                [error for error in (medical_error, condition_error) if error],
                ["Please correct the medical history answers."],
            ))
        else:
            absorb(self.check_medical_conditions(conditions, medical_clearance))

        if not all_reasons:
            all_reasons.append("No risk factors identified.")
            all_recommendations.append("Safe to proceed with program design.")

        return ScreeningResult(
            clearance=highest_level,
            reasons=all_reasons,
            blocked=blocked,
            recommendations=all_recommendations,
            subject_hash=subject_hash(intake),
        )


def main():
    """Example usage."""
    screener = ReadinessScreen()
    
    example_intake = {
        "age": 32,
        "par_q": {flag: False for flag in screener.PAR_Q_RED_FLAGS},
        "pregnant": False,
        "medical_conditions": [],
        "medical_clearance": False
    }
    
    result = screener.screen_intake(example_intake)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
