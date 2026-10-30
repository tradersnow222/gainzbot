#!/usr/bin/env python3
"""
Red flag detection script for Gainzbot.

Scans user check-ins and messages for medical and safety red flags that require
immediate plan pause and professional consultation.
"""

from dataclasses import dataclass
from typing import Dict, List, Set
import json
import re
import unicodedata


@dataclass
class RedFlagResult:
    """Result of red flag scanning."""
    pause_plan: bool
    flags_detected: List[str]
    message: str
    recommendations: List[str]

    def to_dict(self) -> Dict:
        return {
            "pause_plan": self.pause_plan,
            "flags_detected": self.flags_detected,
            "message": self.message,
            "recommendations": self.recommendations
        }


class RedFlagChecker:
    """Detects medical and safety red flags in user communications."""

    RED_FLAG_PATTERNS = {
        "chest_pain": [
            r"\b(chest\s+pain|chest\s+pressure|chest\s+tightness|heart\s+pain)\b",
            r"\b(squeezing\s+chest|crushing\s+chest|burning\s+chest)\b",
            r"\b(my\s+)?chest\s+(hurts?|hurt(s|ing)?)\b",
        ],
        "cardiac_symptoms": [
            r"\b(heart\s+(is\s+)?racing|heart\s+(is\s+)?pounding|irregular\s+heartbeat|palpitations)\b",
            r"\b(heart\s+skipping|rapid\s+pulse)\b",
        ],
        "fainting": [
            r"\b(fainted|passed\s+out|blacked\s+out|lost\s+consciousness)\b",
            r"\b(blackout|syncope)\b",
        ],
        "dizziness": [
            r"\b(severe\s+dizziness|extreme\s+dizziness|very\s+dizzy)\b",
            r"\b(vertigo|room\s+spinning)\b",
        ],
        "sharp_joint_pain": [
            r"\b(sharp\s+(knee|hip|shoulder|elbow|wrist|ankle)\s+pain)\b",
            r"\b(stabbing\s+(joint|knee|hip|shoulder)\s+pain)\b",
            r"\b(shooting\s+pain\s+in\s+(knee|hip|shoulder|joint))\b",
        ],
        "injury": [
            r"\b(pull(ed)?|tear|tore|torn|sprain(ed)?)\s+(a\s+|my\s+|the\s+)?(muscle|hamstring|quad|groin|ligament|tendon|rotator\s+cuff|ankle|wrist|knee)\b",
            r"\b(muscle|hamstring|quad|groin|ligament|tendon|rotator\s+cuff|ankle|wrist|knee)\s+(pull|tear|sprain)\b",
            r"\b(injured|strain(ed)?|injury\s+to)\b",
        ],
        "extreme_fatigue": [
            r"\b(extreme\s+fatigue|severe\s+fatigue|completely\s+exhausted)\b",
            r"\b(can't\s+get\s+out\s+of\s+bed|can't\s+function|too\s+tired\s+to\s+move)\b",
            r"\b(chronic\s+fatigue|persistent\s+exhaustion)\b",
        ],
        "disordered_eating": [
            r"\b(binge\s+(eat(ing)?|on\s+food)|purge(d)?|purging)\b",
            r"\b(vomit(ed|ing)?|throwing\s+up)(\s+after\s+(eating|meals))?\b",
            r"\b(haven't\s+eaten\s+in\s+days|skipping\s+all\s+meals|not\s+eating\s+at\s+all)\b",
            r"\b(obsessed\s+with\s+calories|terrified\s+of\s+food|afraid\s+to\s+eat)\b",
            r"\b(exercise\s+to\s+punish|punishing\s+myself)\b",
        ],
        "breathing_difficulty": [
            r"\b(can't\s+breathe|difficulty\s+breathing|shortness\s+of\s+breath)\b",
            r"\b(gasping|wheezing|labored\s+breathing)\b",
        ],
        "abnormal_bleeding": [
            r"\b(coughing\s+blood|blood\s+in\s+urine|blood\s+in\s+stool)\b",
            r"\b(unusual\s+bleeding|abnormal\s+bleeding)\b",
        ],
        "numbness": [
            r"\b(numbness\s+in\s+(arm|leg|face|chest))\b",
            r"\b(tingling\s+in\s+(arm|leg|face)|loss\s+of\s+sensation)\b",
        ],
    }

    SEVERITY_MESSAGES = {
        "cardiac": "Medical emergency. Stop all activity and seek immediate medical attention.",
        "neurological": "Serious concern. Please see a doctor as soon as possible.",
        "fainting": "Stop training immediately. Call emergency services if accompanied by chest pain, trouble breathing, or confusion. Otherwise see a doctor before resuming training.",
        "injury": "Training pause required. Professional evaluation recommended.",
        "psychological": "Please speak with a healthcare professional about these concerns.",
        "general": "Plan paused. Professional consultation recommended before continuing.",
    }

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalize text for consistent pattern matching.
        
        Converts curly quotes and apostrophes to straight equivalents
        to ensure patterns match regardless of input device.
        
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

    def _classify_severity(self, flags: Set[str]) -> str:
        """Classify the severity category based on detected flags."""
        if any(f in flags for f in ["chest_pain", "cardiac_symptoms", "breathing_difficulty"]):
            return "cardiac"
        if "fainting" in flags:
            return "fainting"
        if any(f in flags for f in ["numbness", "abnormal_bleeding"]):
            return "neurological"
        if "injury" in flags or "sharp_joint_pain" in flags:
            return "injury"
        if "disordered_eating" in flags:
            return "psychological"
        return "general"

    def scan_text(self, text: str) -> RedFlagResult:
        """
        Scan text for red flag indicators.
        
        Args:
            text: User message or check-in text to scan
            
        Returns:
            RedFlagResult with pause recommendation and guidance
        """
        text_normalized = self.normalize_text(text)
        text_lower = text_normalized.lower()
        flags_detected = set()
        
        for flag_type, patterns in self.RED_FLAG_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    flags_detected.add(flag_type)
                    break
        
        if not flags_detected:
            return RedFlagResult(
                pause_plan=False,
                flags_detected=[],
                message="No red flags detected. Continue with your plan.",
                recommendations=[]
            )
        
        severity = self._classify_severity(flags_detected)
        message = self.SEVERITY_MESSAGES[severity]
        
        recommendations = self._generate_recommendations(flags_detected, severity)
        
        return RedFlagResult(
            pause_plan=True,
            flags_detected=sorted(list(flags_detected)),
            message=message,
            recommendations=recommendations
        )

    def _generate_recommendations(self, flags: Set[str], severity: str) -> List[str]:
        """Generate specific recommendations based on detected flags."""
        recommendations = []
        
        if severity == "cardiac":
            recommendations.append(
                "If experiencing chest pain, shortness of breath, or heart symptoms: "
                "Call emergency services immediately (911 in US)."
            )
            recommendations.append(
                "Do not attempt any physical activity until cleared by a physician."
            )
        
        if severity == "fainting":
            recommendations.append(
                "Stop training immediately."
            )
            recommendations.append(
                "Call emergency services if fainting was accompanied by chest pain, "
                "trouble breathing, or confusion."
            )
            recommendations.append(
                "Otherwise, see a doctor before resuming training."
            )
        
        if severity == "neurological" and "fainting" not in flags:
            recommendations.append(
                "See a doctor within 24 hours for evaluation."
            )
            recommendations.append(
                "Avoid any strenuous activity until medically cleared."
            )
        
        if "injury" in flags or "sharp_joint_pain" in flags:
            recommendations.append(
                "Rest the affected area and apply ice if needed."
            )
            recommendations.append(
                "Schedule evaluation with a sports medicine professional or physical therapist."
            )
            recommendations.append(
                "Do not train through sharp or acute pain."
            )
        
        if "extreme_fatigue" in flags:
            recommendations.append(
                "Consider blood work to rule out underlying conditions (anemia, thyroid, etc.)."
            )
            recommendations.append(
                "Increase rest days and reassess training volume with your coach."
            )
        
        if "disordered_eating" in flags:
            recommendations.append(
                "Speak with a mental health professional specializing in eating disorders."
            )
            recommendations.append(
                "Contact National Eating Disorders Association (NEDA) helpline: 1-800-931-2237"
            )
            recommendations.append(
                "Pause any calorie restriction or weight loss goals until professionally supported."
            )
        
        recommendations.append(
            "Do not resume training until the issue is addressed and you have clearance."
        )
        
        return recommendations

    def scan_check_in(self, check_in: Dict) -> RedFlagResult:
        """
        Scan a structured check-in for red flags.
        
        Args:
            check_in: Dictionary containing check-in data with fields like
                     'notes', 'how_feeling', 'pain', 'energy', etc.
            
        Returns:
            RedFlagResult with pause recommendation and guidance
        """
        text_fields = []
        
        for field in ["notes", "how_feeling", "pain", "symptoms", "concerns", "message"]:
            if field in check_in and check_in[field]:
                text_fields.append(str(check_in[field]))
        
        combined_text = " ".join(text_fields)
        
        return self.scan_text(combined_text)


def main():
    """Example usage."""
    checker = RedFlagChecker()
    
    examples = [
        "Had a great workout today, feeling strong!",
        "Experiencing chest pain during my run today.",
        "Sharp knee pain during squats, had to stop.",
        "I purged after dinner because I ate too much.",
    ]
    
    for example in examples:
        print(f"\nText: {example}")
        result = checker.scan_text(example)
        print(json.dumps(result.to_dict(), indent=2))
        print("-" * 80)


if __name__ == "__main__":
    main()
