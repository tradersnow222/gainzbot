#!/usr/bin/env python3
"""
Readiness screening script for Gainzbot.

Implements PAR-Q+ style readiness and age screening before allowing plan generation.
Identifies medical and safety risks that require clearance or physician consultation.
Uses shared input validation with fail-closed behavior.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from enum import Enum
import difflib
import hmac
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
    par_q: Dict = field(default_factory=dict)
    clearance_date: str = ""
    doctor_cleared: bool = False
    age: object = None
    issuer_seal: str = ""

    def to_dict(self) -> Dict:
        return {
            "clearance": self.clearance.value,
            "reasons": self.reasons,
            "blocked": self.blocked,
            "recommendations": self.recommendations,
            "subject_hash": self.subject_hash,
            "par_q": dict(self.par_q or {}),
            "clearance_date": self.clearance_date,
            "doctor_cleared": self.doctor_cleared,
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


def _screening_payload(result: ScreeningResult) -> str:
    clearance = result.clearance.value if isinstance(result.clearance, ClearanceLevel) else result.clearance
    body = {
        "blocked": result.blocked,
        "clearance": clearance,
        "clearance_date": result.clearance_date or "",
        "age": result.age if isinstance(result.age, int) else None,
        "doctor_cleared": result.doctor_cleared is True,
        "par_q": dict(result.par_q or {}),
        "reasons": list(result.reasons or []),
        "recommendations": list(result.recommendations or []),
        "subject_hash": result.subject_hash or "",
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _screening_seal(result: ScreeningResult) -> str:
    from seal_secret import seal_hex

    return seal_hex(b"readiness", _screening_payload(result))


def screening_seal_matches(result) -> bool:
    """True only when readiness_screen set the marker on this exact result."""
    if not isinstance(result, ScreeningResult):
        return False
    seal = result.issuer_seal if isinstance(result.issuer_seal, str) else ""
    if not seal:
        return False
    expected = _screening_seal(result)
    if len(seal) != len(expected):
        return False
    return hmac.compare_digest(seal, expected)


def passing_readiness(result) -> bool:
    """True only for an issued clear or caution result that is not blocked.

    Anyone under 18 does not pass, even when the result says clear.
    """
    if not screening_seal_matches(result):
        return False
    if isinstance(getattr(result, "age", None), int) and result.age < 18:
        return False
    if result.blocked is not False:
        return False
    clearance = result.clearance.value if hasattr(result.clearance, "value") else result.clearance
    if not isinstance(clearance, str):
        return False
    return clearance.strip().lower() in {"clear", "caution"}


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
        "clearance_date",
    }

    _DOCTOR_WORD = re.compile(r"\b(?:doctors?|physicians?|dr)\b", re.IGNORECASE)
    _CLEAR_WORD = re.compile(r"\b(?:cleared|clearance|clears)\b", re.IGNORECASE)
    _DENY_WORD = re.compile(
        r"\b(?:not|never|no|without|hasn't|hasnt|haven't|havent|didn't|didnt|won't|wont|"
        r"unless|until|except|provided|assuming|although|though|however)\b"
        r"|\bonly if\b|\bas long as\b",
        re.IGNORECASE,
    )
    _DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
    _YEAR = re.compile(r"\b(\d{4})\b")
    _PLAN_FOLLOWS = "The plan follows the doctor's clearance."

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
            return self._result(
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
            return self._result(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations,
                age=age,
            )
        
        if age < self.ADULT_AGE:
            return self._result(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=["There is no training plan for anyone under 18."],
                blocked=True,
                recommendations=["There is no training plan for anyone under 18."],
                age=age,
            )
        
        return self._result(
            clearance=ClearanceLevel.CLEAR,
            reasons=[],
            blocked=False,
            recommendations=[],
            age=age,
        )

    def _yes_no(self, data: Dict, key: str, default: bool = False):
        """Parse a yes/no field with the shared parser. Missing uses default."""
        if key not in data:
            return default, None
        try:
            return InputValidator.parse_boolean(data[key], key), None
        except ValidationError as e:
            return None, str(e)

    def _interpret_clearance(self, value):
        """A yes, or a sentence that a doctor cleared them. A denial is no.

        A clear-word plus a year is a dated clearance attempt even without
        the word doctor. Deny words still deny.
        """
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            text = InputValidator.normalize_unicode(value).strip()
            has_clear = self._CLEAR_WORD.search(text) is not None
            has_doctor = self._DOCTOR_WORD.search(text) is not None
            has_year = self._YEAR.search(text) is not None
            if (has_doctor and has_clear) or (has_clear and has_year):
                return self._DENY_WORD.search(text) is None, None
        try:
            return InputValidator.parse_boolean(value, "medical_clearance"), None
        except ValidationError as error:
            return None, str(error)

    def _year_date(self, intake):
        """YYYY-01-01 when the clearance sentence names a year."""
        raw = intake.get("medical_clearance")
        if not isinstance(raw, str):
            return None
        text = InputValidator.normalize_unicode(raw)
        match = self._YEAR.search(text)
        if not match:
            return None
        year = int(match.group(1))
        if year < 1900 or year > 2100:
            return None
        return f"{year:04d}-01-01"

    def _check_clearance_date(self, text):
        try:
            cleared_on = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None, "clearance_date must be YYYY-MM-DD."
        today = datetime.now(timezone.utc).date()
        if cleared_on > today:
            return None, "clearance_date cannot be in the future."
        try:
            anniversary = cleared_on.replace(year=cleared_on.year + 1)
        except ValueError:
            anniversary = cleared_on.replace(year=cleared_on.year + 1, day=28)
        if today >= anniversary:
            return None, "That clearance is more than 12 months old. Ask again."
        return text, None

    def _parse_medical_clearance(self, intake: Dict):
        if "medical_clearance" not in intake:
            return False, None
        return self._interpret_clearance(intake.get("medical_clearance"))

    def _read_clearance_date(self, intake: Dict, cleared: bool):
        """The date they gave. A year in the sentence is that year, not today."""
        if "clearance_date" not in intake:
            implied = self._year_date(intake) if cleared else None
            if implied:
                return self._check_clearance_date(implied)
            if cleared:
                return datetime.now(timezone.utc).date().isoformat(), None
            return "", None
        raw = intake.get("clearance_date")
        text = raw.strip() if isinstance(raw, str) else ""
        if self._DATE.fullmatch(text):
            return self._check_clearance_date(text)
        return None, "clearance_date must be YYYY-MM-DD."

    def _plain_par_q(self, parsed: Dict) -> str:
        parts = []
        for flag in self.PAR_Q_RED_FLAGS:
            if flag not in parsed:
                continue
            answer = "yes" if parsed[flag] else "no"
            parts.append(f"{flag.replace('_', ' ')}: {answer}")
        return "; ".join(parts)

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

    def _result(self, *args, **kwargs) -> ScreeningResult:
        kwargs.pop("issuer_seal", None)
        result = ScreeningResult(*args, **kwargs)
        result.issuer_seal = _screening_seal(result)
        return result

    def _blocked(self, reasons: List[str], recommendations: List[str], **extra) -> ScreeningResult:
        return self._result(
            clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
            reasons=reasons,
            blocked=True,
            recommendations=recommendations,
            **extra,
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
        record = dict(parsed)
        reasons = []
        recommendations = []
        if red_flags and has_clearance and not (unknown or missing or parse_errors):
            return self._result(
                clearance=ClearanceLevel.CAUTION,
                reasons=[f"PAR-Q answers on record: {self._plain_par_q(record)}."],
                blocked=False,
                recommendations=[
                    "Physician clearance is recorded. Modified programming may be required."
                ],
                par_q=record,
                doctor_cleared=True,
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
            return self._blocked(reasons, recommendations, par_q=record)

        return self._result(
            clearance=ClearanceLevel.CLEAR,
            reasons=[],
            blocked=False,
            recommendations=[],
            par_q=record,
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
            return self._result(
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
            return self._result(
                clearance=ClearanceLevel.CAUTION,
                reasons=reasons,
                blocked=False,
                recommendations=recommendations
            )
        
        return self._result(
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
            return self._result(
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
            return self._result(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        if not normalized_conditions:
            return self._result(
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
            return self._result(
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
        return self._result(
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

        parsed_age = None
        if "age" not in intake:
            absorb(self._blocked(
                ["Age is required. There is no default age."],
                ["Please provide your age."],
            ))
        else:
            try:
                number = InputValidator.parse_number(
                    intake["age"], "age", allow_zero=False, allow_negative=False
                )
            except (ValidationError, ValueError, TypeError):
                number = None
            if (
                isinstance(number, (int, float))
                and not isinstance(number, bool)
                and number == int(number)
            ):
                parsed_age = int(number)
            parental_consent, consent_error = self._yes_no(intake, "parental_consent", False)
            if consent_error:
                absorb(self._blocked([consent_error], ["Please answer parental consent with yes or no."]))
            else:
                absorb(self.check_age(intake["age"], parental_consent))

        medical_clearance, medical_error = self._parse_medical_clearance(intake)
        doctor_cleared = medical_clearance is True
        clearance_date, date_error = self._read_clearance_date(intake, doctor_cleared)
        if date_error:
            doctor_cleared = False
            absorb(self._blocked(
                [date_error],
                ["Please give the clearance date as YYYY-MM-DD."],
            ))
            clearance_date = ""
        stored_par_q = {}
        if "par_q" not in intake:
            absorb(self._blocked(
                ["A complete PAR-Q is required."],
                ["Please answer every PAR-Q question with yes or no."],
            ))
        else:
            par_result = self.check_par_q(intake["par_q"], has_clearance=doctor_cleared)
            stored_par_q = dict(par_result.par_q or {})
            absorb(par_result)

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
            absorb(self.check_medical_conditions(conditions, doctor_cleared))

        if doctor_cleared and stored_par_q:
            plain = f"PAR-Q answers on record: {self._plain_par_q(stored_par_q)}."
            if plain not in all_reasons:
                all_reasons.append(plain)

        if not all_reasons:
            all_reasons.append("No risk factors identified.")
            all_recommendations.append("Safe to proceed with program design.")

        if doctor_cleared and not blocked and self._PLAN_FOLLOWS not in all_recommendations:
            all_recommendations.append(self._PLAN_FOLLOWS)

        return self._result(
            clearance=highest_level,
            reasons=all_reasons,
            blocked=blocked,
            recommendations=all_recommendations,
            subject_hash=subject_hash(intake),
            par_q=stored_par_q,
            clearance_date=clearance_date or "",
            doctor_cleared=doctor_cleared,
            age=parsed_age,
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
