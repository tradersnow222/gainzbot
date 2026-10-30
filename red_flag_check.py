#!/usr/bin/env python3
"""
Red flag detection script for Gainzbot.

Scans user check-ins and messages for medical and safety red flags that require
immediate plan pause and professional consultation.
"""

from dataclasses import dataclass
from typing import Dict, List, Set
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator


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

    # (pattern, suppress when the phrase is clearly benign)
    RED_FLAG_PATTERNS = {
        "chest_pain": [
            (r"\b(?:chest\s+pain|chest\s+pressure|chest\s+tightness|heart\s+pain)\b", False),
            (r"\b(?:squeezing\s+chest|crushing\s+chest|burning\s+chest)\b", False),
            (r"\b(?:my\s+)?chest\s+(?:hurts?|hurt(?:s|ing)?|feels?\s+tight|felt\s+tight|is\s+tight)\b", False),
            (r"\bpain\s+in\s+(?:my\s+)?chest\b", False),
            (r"\btight(?:ness)?\s+in\s+(?:my\s+)?chest\b", False),
        ],
        "cardiac_symptoms": [
            (r"\bheart\s+(?:is\s+)?(?:racing|pounding)\b", True),
            (r"\b(?:irregular\s+heartbeat|palpitations|heart\s+skipping|rapid\s+pulse)\b", False),
            (r"\bheart\s+(?:is\s+)?flutter\w*\b", False),
            (r"\bheart\s+attacks?\b", False),
            (r"\bcardiac\s+(?:arrest|event|episode)\b", False),
            (r"\bmyocardial(?:\s+infarction)?\b", False),
            (r"\bheart\s+stopped\b(?!\s+(?:racing|pounding))", False),
        ],
        "fainting": [
            (r"\b(?:fainted|passed\s+out|blacked\s+out|lost\s+consciousness)\b", False),
            (r"\b(?:blackout|syncope)\b", False),
        ],
        "dizziness": [
            (r"\b(?:severe\s+dizziness|extreme\s+dizziness|very\s+dizzy)\b", False),
            (r"\b(?:vertigo|room\s+spinning)\b", False),
        ],
        "sharp_joint_pain": [
            (r"\bsharp\s+(?:knee|hip|shoulder|elbow|wrist|ankle)\s+pain\b", False),
            (r"\bstabbing\s+(?:joint|knee|hip|shoulder)\s+pain\b", False),
            (r"\bshooting\s+pain\s+in\s+(?:knee|hip|shoulder|joint)\b", False),
        ],
        "injury": [
            (
                r"\b(?:pull(?:ed)?|tear|tore|torn|sprain(?:ed)?|strain(?:ed)?)\s+"
                r"(?:(?:a|my|the)\s+)?(?:something|muscle|hamstring|quad|groin|ligament|"
                r"tendon|rotator\s+cuff|ankle|wrist|knee|shoulder|hip|elbow|back|calf|arm)\b",
                False,
            ),
            (r"\b(?:knee|ankle|shoulder|hip|wrist|elbow)\s+popped\b", False),
            (r"\binjury to\b", False),
            (
                r"(?<!foam[ -])(?<![a-z-])(?:rolled|twisted|tweaked)\s+"
                r"(?:(?:my|the|an|a)\s+)?(?:left\s+|right\s+)?"
                r"(?:ankle|knee|wrist|shoulder|elbow|hip|foot)\b",
                False,
            ),
            (
                r"\b(?:heard|felt)\s+(?:a\s+)?pop\s+(?:in\s+)?(?:my\s+)?"
                r"(?:left\s+|right\s+)?(?:ankle|knee|wrist|shoulder|elbow|hip|back|calf|foot)\b",
                False,
            ),
            (
                r"\b(?:ankle|knee|wrist|shoulder|elbow|hip|foot|leg|arm)\s+"
                r"(?:is|was|got|feels?|looks?)\s+"
                r"(?:really\s+|so\s+|very\s+|all\s+|pretty\s+)?(?:swollen|swelled)\b",
                False,
            ),
            (
                r"\b(?:swollen|swelling)\s+(?:in\s+)?(?:my\s+)?"
                r"(?:left\s+|right\s+)?(?:ankle|knee|wrist|shoulder|elbow|hip|foot)\b",
                False,
            ),
            (
                r"\b(?:ankle|knee|wrist|shoulder|elbow|hip|foot)\s+"
                r"(?:rolled|swelled)\b",
                False,
            ),
            (
                r"\bpopped\s+(?:my\s+)?(?:left\s+|right\s+)?"
                r"(?:ankle|knee|wrist|shoulder|elbow|hip)\b",
                False,
            ),
        ],
        "extreme_fatigue": [
            (r"\b(?:extreme\s+fatigue|severe\s+fatigue|completely\s+exhausted)\b", False),
            (r"\b(?:can't\s+get\s+out\s+of\s+bed|can't\s+function|too\s+tired\s+to\s+move)\b", False),
            (r"\b(?:chronic\s+fatigue|persistent\s+exhaustion)\b", False),
        ],
        "disordered_eating": [
            (r"\b(?:binge\s+(?:eat(?:ing)?|on\s+food)|purg(?:e|ed|ing))\b", False),
            (r"\b(?:mak(?:e|ing)|made)\s+(?:myself\s+)?(?:throw up|vomit|puke)\b", False),
            (
                r"\b(?:throw(?:ing)? up|threw up|vomit(?:ed|ing)?)\s+after\s+"
                r"(?:eating|meals?|dinner|food|a meal)\b",
                False,
            ),
            (r"\b(?:haven't\s+eaten\s+in\s+days|skipping\s+all\s+meals|not\s+eating\s+at\s+all)\b", False),
            (r"\b(?:obsessed\s+with\s+calories|terrified\s+of\s+food|afraid\s+to\s+eat)\b", False),
            (r"\b(?:exercise\s+to\s+punish|punishing\s+myself)\b", False),
            (r"\bfingers?\s+down\s+(?:my\s+)?throat\b", False),
            (r"\b(?:mak(?:e|ing)|made)\s+myself\s+sick\b", False),
            (
                r"\b(?:throw(?:ing)? up|threw up|vomit(?:ing|ed)?)\s+"
                r"(?:everything|whatever)\s+i\s+eat\b",
                False,
            ),
            (
                r"\b(?:forc(?:e|ed|ing))\s+(?:myself\s+)?to\s+(?:throw up|vomit|puke)\b",
                False,
            ),
            (
                r"\b(?:throw(?:ing)? up|threw up|vomit(?:ed|ing)?|puk(?:e|ed|ing)|"
                r"purg(?:e|ed|ing))\s+on purpose\b",
                False,
            ),
            (
                r"\b(?:on purpose|deliberately|intentionally)\s+"
                r"(?:throw(?:ing)? up|threw up|vomit(?:ed|ing)?|purg\w*)\b",
                False,
            ),
        ],
        "breathing_difficulty": [
            (
                r"\b(?:can't\s+breathe|cannot\s+breathe|difficulty\s+breathing|"
                r"shortness\s+of\s+breath|short\s+of\s+breath|out\s+of\s+breath)\b",
                False,
            ),
            (r"\b(?:wheezing|labored\s+breathing)\b", False),
            (r"\bgasping\b", True),
        ],
        "abnormal_bleeding": [
            (r"\b(?:coughing\s+blood|blood\s+in\s+urine|blood\s+in\s+stool)\b", False),
            (r"\b(?:unusual\s+bleeding|abnormal\s+bleeding)\b", False),
        ],
        "numbness": [
            (r"\b(?:went|goes|going|feel(?:s|ing)?|felt)\s+numb\b", False),
            (
                r"\b(?:arm|leg|hand|face|foot|finger|fingers|toe|toes|jaw)\b"
                r"(?:\s+\w+){0,3}\s+(?:is|was|feels?|went|goes|going|felt)\s+numb\b",
                False,
            ),
            (r"\bnumb\s+(?:arm|leg|hand|face|foot|fingers?|toes?|jaw)\b", False),
            (r"\bnumbness\b", False),
            (r"\btingling\s+in\s+(?:my\s+)?(?:arm|leg|face|hand|chest)\b", False),
            (r"\bloss\s+of\s+sensation\b", False),
        ],
        "self_harm": [
            (r"\b(?:want\s+to\s+disappear|kill\s+myself|end\s+my\s+life|self[-\s]?harm|suicidal)\b", False),
            (r"\bhate\s+my\s+body\b", False),
        ],
    }

    KNOWN_FIELDS = {"notes", "how_feeling", "pain", "symptoms", "concerns", "message"}
    _NEGATION = {
        "no", "not", "never", "without", "nope",
        "don't", "dont", "didn't", "didnt", "doesn't", "doesnt",
        "isn't", "isnt", "wasn't", "wasnt", "weren't", "werent",
        "haven't", "havent", "hasn't", "hasnt", "hadn't", "hadnt",
    }
    _CLAUSE_BOUNDARY = re.compile(
        r"[,.!?;]|\s+-\s+|\b(?:but|however|though|and|yet)\b"
    )
    _RESTRICTION = re.compile(
        r"\bstarv(?:e|ing|ed)\s+myself\b"
        r"|\bstarv(?:e|ing|ed)\s+(?:myself\s+)?to\s+(?:make|cut|drop)\s+(?:the\s+)?weight\b"
        r"|\bstarv(?:e|ing)\s+(?:myself\s+)?for\s+(?:a\s+|the\s+)?weigh-?in\b"
        r"|\b(?:fasting|not eating|eating nothing|skipping meals|"
        r"haven't been eating|have not been eating)\s+"
        r"(?:so\s+(?:i\s+can|that)\s+|in\s+order\s+to\s+|to\s+)?"
        r"(?:make|cut|drop)\s+(?:the\s+)?weight\b"
        r"|\b(?:fasting|not eating|starving)\s+(?:for|before)\s+"
        r"(?:a\s+|the\s+)?weigh-?in\b"
        r"|\bwater\s+cut(?:ting)?\b"
        r"|\b(?:stopped|stop)\s+eating\s+(?:entirely\s+)?(?:to\s+)?"
        r"(?:cut|make|drop)\s+weight\b"
    )
    _SUBSTANCE = re.compile(
        r"\b(?:laxatives?|diuretics?|diet\s+pills?|water\s+pills?|fat\s+burners?)\b"
    )
    _MISUSE = re.compile(
        r"\b(?:lose|losing|make|cut|drop|dropped)\s+(?:the\s+)?weight\b"
        r"|\bweigh-?in\b"
        r"|\bempty(?:ing)?\s+out\b"
        r"|\b(?:abus\w*|misus\w*|purg\w*)\b"
    )
    _DOSE = re.compile(
        r"\b(?:handful|a\s+bunch|too\s+many|a\s+ton)\s+of\s+"
        r"(?:laxatives?|diuretics?|diet\s+pills?|water\s+pills?|fat\s+burners?)\b"
    )
    _CONCUSSION = re.compile(r"\bconcuss(?:ed|ion|ions)?\b")
    _HEAD_IMPACT = re.compile(
        r"\b(?:hit|bumped|banged|smacked|knocked|whacked)\s+(?:my\s+)?head\b"
        r"|\bblow\s+to\s+(?:the\s+|my\s+)?head\b"
        r"|\bhead\s+(?:injury|trauma|impact|hit|slammed)\b"
        r"|\b(?:hit|blow|shot)\s+to\s+(?:the\s+|my\s+)?head\b"
    )
    _NEURO = re.compile(
        r"\b(?:confused|confusion|memory\s+loss|saw\s+stars|dazed|double\s+vision|slurred)\b"
        r"|\b(?:can't|cannot|don't|do not)\s+remember\b"
        r"|\b(?:can't|cannot)\s+recall\b"
        r"|\bforget(?:ting)?\s+what\s+happened\b"
    )
    _RHABDO = re.compile(r"\brhabdomyolysis\b|\brhabdo\b")
    _URINE = re.compile(
        r"\b(?:cola|coke|tea|coffee)[-\s]?(?:colored|coloured)\s+(?:urine|pee)\b"
        r"|\b(?:dark\s+brown|brown|dark|black|"
        r"tea[-\s]?(?:colored|coloured)|cola[-\s]?(?:colored|coloured))\s+"
        r"(?:urine|pee)\b"
        r"|\b(?:urine|pee)\s+(?:is|was|looks?|looking|turned|went)\s+"
        r"(?:the\s+(?:color|colour)\s+of\s+|like\s+)?"
        r"(?:dark\s+brown|brown|dark|black|cola|coke|tea|coffee)"
        r"(?:[-\s]?(?:colored|coloured))?\b"
    )
    _MUSCLE_PAIN = re.compile(
        r"\b(?:severe|extreme|unbearable|excruciating)\s+muscle\s+"
        r"(?:pain|ache|soreness)\b"
        r"|\bmuscles?\s+(?:hurt|ache|aching)\s+(?:so\s+)?bad(?:ly)?\b"
        r"|\bmuscles?\s+(?:are|were)\s+killing\s+me\b"
        r"|\b(?:severe|extreme|unbearable)\s+(?:pain|soreness)\s+in\s+"
        r"(?:my\s+)?muscles\b"
        r"|\b(?:really|so)\s+bad\s+muscle\s+pain\b"
        r"|\bmuscle\s+pain\s+(?:is\s+)?(?:severe|unbearable|extreme)\b"
    )
    _BENIGN = ("in a good way", "felt amazing", "feeling amazing", "lol", "lmao", "haha")

    SEVERITY_MESSAGES = {
        "crisis": (
            "Please pause. If you're in crisis, in the US call or text 988, "
            "or contact local emergency services."
        ),
        "cardiac": "Medical emergency. Stop all activity and seek immediate medical attention.",
        "neurological": "Serious concern. Please see a doctor as soon as possible.",
        "fainting": "Stop training immediately. Call emergency services if accompanied by chest pain, trouble breathing, or confusion. Otherwise see a doctor before resuming training.",
        "injury": "Training pause required. Professional evaluation recommended.",
        "psychological": "Please speak with a healthcare professional about these concerns.",
        "general": "Plan paused. Professional consultation recommended before continuing.",
    }

    def _classify_severity(self, flags: Set[str]) -> str:
        """Classify the severity category based on detected flags."""
        if "self_harm" in flags:
            return "crisis"
        if any(f in flags for f in (
            "chest_pain", "cardiac_symptoms", "breathing_difficulty",
            "numbness", "rhabdomyolysis",
        )):
            return "cardiac"
        if "fainting" in flags:
            return "fainting"
        if "abnormal_bleeding" in flags or "head_injury" in flags:
            return "neurological"
        if "injury" in flags or "sharp_joint_pain" in flags:
            return "injury"
        if "disordered_eating" in flags or "very_low_intake" in flags:
            return "psychological"
        return "general"

    def _is_negated(self, text: str, start: int) -> bool:
        """Negation applies only inside the current clause.

        It stops at a comma, at but/however/though/and/yet, and at the
        end of a sentence. A negation in an earlier clause does not
        cover a later symptom.
        """
        prefix = text[:start]
        cut = 0
        for match in self._CLAUSE_BOUNDARY.finditer(prefix):
            cut = match.end()
        words = re.findall(r"[a-z']+", prefix[cut:])
        return any(word in self._NEGATION for word in words)

    def _active(self, text: str, pattern: re.Pattern) -> List[re.Match]:
        return [
            match for match in pattern.finditer(text)
            if not self._is_negated(text, match.start())
        ]

    def _same_sentence(self, text: str, left: re.Pattern, right: re.Pattern) -> bool:
        def span(index: int):
            start = 0
            for mark in re.finditer(r"[.!?]", text):
                if mark.start() >= index:
                    return start, mark.start()
                start = mark.end()
            return start, len(text)

        for match in self._active(text, left):
            begin, end = span(match.start())
            for other in self._active(text, right):
                if begin <= other.start() < end:
                    return True
        return False

    def _extra_flags(self, text: str) -> Set[str]:
        flags = set()
        if self._active(text, self._RESTRICTION) or self._active(text, self._DOSE):
            flags.add("disordered_eating")
        elif self._same_sentence(text, self._SUBSTANCE, self._MISUSE):
            flags.add("disordered_eating")
        if self._active(text, self._CONCUSSION) or self._same_sentence(
            text, self._HEAD_IMPACT, self._NEURO
        ):
            flags.add("head_injury")
        if self._active(text, self._RHABDO) or self._same_sentence(
            text, self._URINE, self._MUSCLE_PAIN
        ):
            flags.add("rhabdomyolysis")
        return flags

    def _is_benign(self, text: str, end: int) -> bool:
        window = text[end:end + 90]
        return any(marker in window for marker in self._BENIGN)

    def _has_very_low_intake(self, text: str) -> bool:
        for match in re.finditer(r"\b(\d{1,4})\s*(?:kcal|calories|cals)\b", text):
            amount = int(match.group(1))
            if amount >= 1000:
                continue
            window = text[max(0, match.start() - 40):match.end()]
            if re.search(r"\b(?:only|just|ate|eaten|eating)\b", window):
                return True
        return False

    def _detect_flags(self, text: str) -> Set[str]:
        flags = set()
        for flag, specs in self.RED_FLAG_PATTERNS.items():
            for pattern, suppress_benign in specs:
                matched = False
                for match in re.finditer(pattern, text):
                    if self._is_negated(text, match.start()):
                        continue
                    if suppress_benign and self._is_benign(text, match.end()):
                        continue
                    matched = True
                    break
                if matched:
                    flags.add(flag)
                    break
        if self._has_very_low_intake(text):
            flags.add("very_low_intake")
        flags.update(self._extra_flags(text))
        return flags

    def _ask(self, detail: str) -> RedFlagResult:
        if "?" not in detail:
            detail = detail.rstrip(".") + "?"
        return RedFlagResult(
            pause_plan=True,
            flags_detected=["needs_clarification"],
            message=f"I'm pausing so I can ask you directly. {detail}",
            recommendations=["Please reply and describe how you're feeling in your own words."],
        )

    def _with_question(self, scanned: RedFlagResult, question: str) -> RedFlagResult:
        real_flags = [flag for flag in scanned.flags_detected if flag != "needs_clarification"]
        if "?" not in question:
            question = question.rstrip(".") + "?"
        if scanned.pause_plan and real_flags:
            message = f"{scanned.message} {question}"
            recommendations = list(scanned.recommendations)
        else:
            message = question
            recommendations = []
        recommendations.append("Please reply and describe how you're feeling in your own words.")
        real_flags.append("needs_clarification")
        return RedFlagResult(
            pause_plan=True,
            flags_detected=sorted(set(real_flags)),
            message=message,
            recommendations=recommendations,
        )

    def _clear(self) -> RedFlagResult:
        return RedFlagResult(
            pause_plan=False,
            flags_detected=[],
            message="No red flags detected. Continue with your plan.",
            recommendations=[],
        )

    def scan_text(self, text: str) -> RedFlagResult:
        """
        Scan text for red flag indicators.

        Malformed text pauses and asks. It never reports a clean result.
        """
        if not isinstance(text, str):
            return self._ask("I couldn't read that message. Can you tell me how you're feeling?")

        cleaned = InputValidator.clean_text(text)
        if not cleaned.strip():
            return self._clear()

        flags_detected = self._detect_flags(cleaned)
        if not flags_detected:
            return self._clear()

        severity = self._classify_severity(flags_detected)
        return RedFlagResult(
            pause_plan=True,
            flags_detected=sorted(flags_detected),
            message=self.SEVERITY_MESSAGES[severity],
            recommendations=self._generate_recommendations(flags_detected, severity),
        )

    def _generate_recommendations(self, flags: Set[str], severity: str) -> List[str]:
        """Generate specific recommendations based on detected flags."""
        recommendations = []

        if severity == "crisis" or "self_harm" in flags:
            recommendations.append(
                "In the US, call or text 988, or contact local emergency services."
            )
        
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

        if "rhabdomyolysis" in flags:
            recommendations.append(
                "Dark urine with severe muscle pain can be rhabdomyolysis. "
                "Seek emergency care and do not keep training."
            )

        if "head_injury" in flags:
            recommendations.append(
                "A head impact with confusion, memory loss, or concussion signs "
                "needs a doctor before any further training."
            )
        
        if "disordered_eating" in flags or "very_low_intake" in flags:
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
        if not isinstance(check_in, dict):
            if isinstance(check_in, str):
                return self._with_question(
                    self.scan_text(check_in),
                    "This check-in isn't in a form I can use. Can you tell me how you're feeling?",
                )
            return self._ask(
                "That check-in isn't something I can read. Can you tell me how you're feeling?"
            )

        unknown = [
            str(key) for key in check_in if str(key).lower() not in self.KNOWN_FIELDS
        ]
        scanned = self.scan_text(
            " ".join(self._flatten(value) for value in check_in.values())
        )
        if unknown:
            names = ", ".join(unknown)
            return self._with_question(
                scanned,
                f"I don't recognize '{names}'. Can you tell me what you mean?",
            )
        return scanned

    def _flatten(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return " ".join(self._flatten(item) for item in value)
        if isinstance(value, dict):
            return " ".join(self._flatten(item) for item in value.values())
        return str(value)


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
