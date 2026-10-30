#!/usr/bin/env python3
"""
Readiness screening script for Gainzbot.

Implements PAR-Q+ style readiness and age screening before allowing plan generation.
Identifies medical and safety risks that require clearance or physician consultation.
Uses shared input validation with fail-closed behavior.
"""

from dataclasses import dataclass
from typing import Dict, List
from enum import Enum
import json
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

    def to_dict(self) -> Dict:
        return {
            "clearance": self.clearance.value,
            "reasons": self.reasons,
            "blocked": self.blocked,
            "recommendations": self.recommendations
        }


class ReadinessScreen:
    """Screens users for readiness to begin fitness and nutrition programs."""

    MIN_AGE = 13
    ADULT_AGE = 18

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
            age = int(InputValidator.parse_number(age_raw, "age", allow_zero=False, allow_negative=False))
        except (ValidationError, ValueError, TypeError) as e:
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=[f"Invalid age: {e}"],
                blocked=True,
                recommendations=["Please provide a valid age."]
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

    def check_par_q(self, responses: Dict[str, bool]) -> ScreeningResult:
        """Check PAR-Q+ style questions."""
        reasons = []
        recommendations = []
        red_flags = []
        
        for flag in self.PAR_Q_RED_FLAGS:
            if responses.get(flag, False):
                red_flags.append(flag.replace("_", " ").title())
        
        if red_flags:
            reasons.append(
                f"Red flag responses: {', '.join(red_flags)}"
            )
            recommendations.append(
                "Physician clearance required before beginning any exercise program."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        return ScreeningResult(
            clearance=ClearanceLevel.CLEAR,
            reasons=[],
            blocked=False,
            recommendations=[]
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
        all_reasons = []
        all_recommendations = []
        blocked = False
        highest_level = ClearanceLevel.CLEAR
        
        age = intake.get("age", 30)
        parental_consent = intake.get("parental_consent", False)
        age_result = self.check_age(age, parental_consent)
        
        if age_result.clearance.value != ClearanceLevel.CLEAR.value:
            all_reasons.extend(age_result.reasons)
            all_recommendations.extend(age_result.recommendations)
            blocked = blocked or age_result.blocked
            if age_result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
            elif age_result.clearance == ClearanceLevel.CAUTION and highest_level != ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.CAUTION
        
        par_q_responses = intake.get("par_q", {})
        par_q_result = self.check_par_q(par_q_responses)
        
        if par_q_result.clearance.value != ClearanceLevel.CLEAR.value:
            all_reasons.extend(par_q_result.reasons)
            all_recommendations.extend(par_q_result.recommendations)
            blocked = blocked or par_q_result.blocked
            if par_q_result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        
        is_pregnant = intake.get("pregnant", False)
        pregnancy_clearance = intake.get("pregnancy_clearance", False)
        pregnancy_result = self.check_pregnancy(is_pregnant, pregnancy_clearance)
        
        if pregnancy_result.clearance.value != ClearanceLevel.CLEAR.value:
            all_reasons.extend(pregnancy_result.reasons)
            all_recommendations.extend(pregnancy_result.recommendations)
            blocked = blocked or pregnancy_result.blocked
            if pregnancy_result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
            elif pregnancy_result.clearance == ClearanceLevel.CAUTION and highest_level != ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.CAUTION
        
        medical_conditions_raw = intake.get("medical_conditions", [])
        
        medical_conditions = []
        if isinstance(medical_conditions_raw, str):
            medical_conditions = [c.strip() for c in medical_conditions_raw.split(',') if c.strip()]
        elif isinstance(medical_conditions_raw, list):
            medical_conditions = medical_conditions_raw
        
        medical_clearance = intake.get("medical_clearance", False)
        medical_result = self.check_medical_conditions(medical_conditions, medical_clearance)
        
        if medical_result.clearance.value != ClearanceLevel.CLEAR.value:
            all_reasons.extend(medical_result.reasons)
            all_recommendations.extend(medical_result.recommendations)
            blocked = blocked or medical_result.blocked
            if medical_result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
            elif medical_result.clearance == ClearanceLevel.CAUTION and highest_level != ClearanceLevel.NEEDS_DOCTOR_CLEARANCE:
                highest_level = ClearanceLevel.CAUTION
        
        if not all_reasons:
            all_reasons.append("No risk factors identified.")
            all_recommendations.append("Safe to proceed with program design.")
        
        return ScreeningResult(
            clearance=highest_level,
            reasons=all_reasons,
            blocked=blocked,
            recommendations=all_recommendations
        )


def main():
    """Example usage."""
    screener = ReadinessScreen()
    
    example_intake = {
        "age": 32,
        "par_q": {
            "chest_pain_at_rest": False,
            "chest_pain_during_activity": False,
            "loss_of_balance_dizziness": False,
            "loss_of_consciousness": False,
            "bone_joint_problem_worsened_by_activity": False,
        },
        "pregnant": False,
        "medical_conditions": [],
        "medical_clearance": False
    }
    
    result = screener.screen_intake(example_intake)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
