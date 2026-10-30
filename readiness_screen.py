#!/usr/bin/env python3
"""
Readiness screening script for Gainzbot.

Implements PAR-Q+ style readiness and age screening before allowing plan generation.
Identifies medical and safety risks that require clearance or physician consultation.
"""

from dataclasses import dataclass
from typing import Dict, List
from enum import Enum
import json


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

    MIN_AGE = 18

    PAR_Q_RED_FLAGS = [
        "chest_pain_at_rest",
        "chest_pain_during_activity",
        "loss_of_balance_dizziness",
        "loss_of_consciousness",
        "bone_joint_problem_worsened_by_activity",
    ]

    MEDICAL_CONDITIONS_REQUIRING_CLEARANCE = [
        "heart_disease",
        "high_blood_pressure",
        "diabetes",
        "asthma",
        "chronic_illness",
    ]

    def check_age(self, age: int, has_parental_consent: bool = False) -> ScreeningResult:
        """Check age requirements."""
        reasons = []
        recommendations = []
        
        if age < self.MIN_AGE and not has_parental_consent:
            reasons.append(
                f"User is under {self.MIN_AGE} years old without parental consent."
            )
            recommendations.append(
                "Parental or guardian consent required for users under 18."
            )
            return ScreeningResult(
                clearance=ClearanceLevel.NEEDS_DOCTOR_CLEARANCE,
                reasons=reasons,
                blocked=True,
                recommendations=recommendations
            )
        
        if age < self.MIN_AGE and has_parental_consent:
            reasons.append(
                f"User is under {self.MIN_AGE} but has parental consent."
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
        
        flagged_conditions = [
            c for c in conditions 
            if c in self.MEDICAL_CONDITIONS_REQUIRING_CLEARANCE
        ]
        
        if not flagged_conditions:
            return ScreeningResult(
                clearance=ClearanceLevel.CLEAR,
                reasons=[],
                blocked=False,
                recommendations=[]
            )
        
        condition_names = [c.replace("_", " ").title() for c in flagged_conditions]
        
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
        
        medical_conditions = intake.get("medical_conditions", [])
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
