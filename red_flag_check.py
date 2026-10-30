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
from guardrails.validate import InputValidator, ValidationError


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

    # One required question per entry. Aliases are true synonyms of that
    # single item. A sub-item never completes a different item.
    CHECKLIST_GROUPS = (
        ("chest_pain", (
            "chest_pain", "chest_pressure", "chest_pain_or_pressure",
        )),
        ("breathing_difficulty", (
            "trouble_breathing", "shortness_of_breath",
            "difficulty_breathing", "cant_breathe",
        )),
        ("fainting", (
            "fainting", "fainting_or_near_fainting", "fainted", "near_fainting",
            "passed_out", "syncope", "collapse", "collapsed",
        )),
        ("stroke_signs", ("stroke_signs", "stroke")),
        ("face_droop", ("face_droop", "facial_droop")),
        ("abnormal_bleeding", (
            "coughing_or_vomiting_blood", "coughing_blood", "vomiting_blood",
            "blood_in_cough", "blood_in_vomit",
        )),
        ("blue_lips", ("blue_lips", "cyanosis")),
        ("self_harm_thoughts", (
            "self_harm_thoughts", "suicidal_thoughts", "not_wanting_to_live",
            "want_to_die", "thoughts_of_self_harm",
        )),
        ("self_harm", ("self_harm", "selfharm")),
        ("disordered_eating", (
            "disordered_eating", "starving_to_cut_weight", "laxatives",
        )),
        ("purging", ("purging", "deliberate_vomiting")),
        ("rhabdomyolysis", (
            "dark_urine", "dark_brown_urine", "cola_colored_urine",
            "cola_urine", "brown_urine",
        )),
        ("injury", ("sudden_pop", "pop")),
        ("tendon_snap", ("tendon_snap", "snap")),
        ("heat_illness", (
            "heat_illness", "heat_stroke", "stopped_sweating",
            "confusion_and_stopped_sweating",
        )),
        ("palpitations", (
            "palpitations", "palpitations_with_dizziness",
            "skipped_or_racing_heartbeat",
        )),
        ("referred_pain", ("referred_pain", "cardiac_referred_pain")),
        ("blood_clot", ("blood_clot", "painful_swollen_calf")),
        ("head_injury", ("head_injury", "head_injury_with_confusion")),
    )
    ITEM_LABELS = {
        "chest_pain": "chest pain or pressure",
        "breathing_difficulty": "trouble breathing",
        "fainting": "fainting or near-fainting",
        "stroke_signs": "stroke signs",
        "face_droop": "face droop",
        "abnormal_bleeding": "coughing or vomiting blood",
        "blue_lips": "blue lips",
        "self_harm_thoughts": "thoughts of self-harm",
        "self_harm": "self-harm",
        "disordered_eating": "disordered eating",
        "purging": "purging",
        "rhabdomyolysis": "dark brown or cola urine",
        "injury": "sudden pop",
        "tendon_snap": "tendon snap",
        "heat_illness": "heat illness",
        "palpitations": "palpitations or a skipped or racing heartbeat with dizziness",
        "referred_pain": "jaw, arm, shoulder, neck, or back pain with sweating, or chest pain at rest",
        "blood_clot": "a hot, red, swollen, or painful calf or leg",
        "head_injury": "head injury with confusion, memory loss, vomiting, or worsening headache",
    }
    CHECKLIST_CONTAINERS = (
        "symptom_checklist", "checklist", "symptom_check",
        "red_flag_checklist", "safety_checklist",
    )
    KNOWN_FIELDS = {
        "notes", "how_feeling", "pain", "symptoms", "concerns", "message",
    }

    _NEGATION = {
        "no", "not", "never", "without", "nope",
        "don't", "dont", "didn't", "didnt", "doesn't", "doesnt",
        "isn't", "isnt", "wasn't", "wasnt", "weren't", "werent",
        "haven't", "havent", "hasn't", "hasnt", "hadn't", "hadnt",
    }
    _CLAUSE_BOUNDARY = re.compile(
        r"[,.!?;]|\s+-\s+|\b(?:but|however|though|and|yet)\b"
    )
    _BENIGN = ("in a good way", "felt amazing", "feeling amazing", "lol", "lmao", "haha", "pr sprint")

    _CHEST = re.compile(r"\bchest\b")
    _CHEST_MARK = re.compile(
        r"\b(?:pressure|tight\w*|crush\w*|sitting|elephant|pain|hurts?|squeez\w*|heavy)\b"
    )
    _HEART = re.compile(r"\bhearts?\b|\bheartbeat\b")
    _HEART_MARK = re.compile(
        r"\b(?:racing|pounding|flutter\w*|attacks?|palpitat\w*|skipp\w*|stopped)\b"
    )
    _BREATH = re.compile(r"\b(?:breath(?!er)\w*|wheez\w*|gasping|gasp)\b")
    _FAINT = re.compile(
        r"\b(?:faint\w*|syncope|passed\s+out|black(?:ed)?\s+out|blackout|"
        r"dizz\w*|vertigo|collaps(?:e|ed|es|ing))\b"
    )
    _PALP = re.compile(r"\bpalpitat\w*\b")
    _SKIPPED_BEAT = re.compile(
        r"\b(?:skipp\w*\s+(?:a\s+)?beats?|beats?\s+skipp\w*)\b"
    )
    _LIGHTHEADED = re.compile(r"\b(?:dizz\w*|light[-\s]?headed)\b")
    _REFERRED_PART = re.compile(r"\b(?:jaw|arm|shoulder|neck|back)\b")
    _PAIN_WORD = re.compile(r"\b(?:pain|hurts?|aching|ache)\b")
    _SWEAT = re.compile(r"\bsweat(?:y|ing|s)?\b")
    _AT_REST = re.compile(
        r"\b(?:at\s+rest|(?:while|when)\s+(?:i'm\s+)?resting)\b"
    )
    _TRAVEL = re.compile(
        r"\b(?:travel\w*|flights?|flew|flying|plane|drove|driving|road\s+trip)\b"
    )
    _SORE = re.compile(r"\bsore\b")
    _LIMB = re.compile(r"\b(?:calf|calves|leg|thigh)\b")
    _CLOT_MARK = re.compile(
        r"\b(?:hot|red|swollen|swelling|swelled|painful|tender|hurts?|pain)\b"
    )
    _NUMB = re.compile(r"\bnumb\w*\b")
    _STROKE = re.compile(r"\b(?:slur(?:red|ring)|droop\w*|one-sided|one\s+sided)\b")
    _BLOOD = re.compile(r"\bblood\b")
    _BLOOD_WITH = re.compile(r"\b(?:cough\w*|vomit\w*|puk\w*)\b")
    _BLUE = re.compile(r"\bblue\b")
    _LIPS = re.compile(r"\blips?\b")
    _CRISIS_VERB = re.compile(r"\b(?:die|dying|dies|kill\w*|alive)\b")
    _SPEAKER = re.compile(r"\b(?:myself|i)\b")
    _HARM_VERB = re.compile(r"\b(?:cut|hurts?|hurting|harm\w*)\b")
    _MYSELF = re.compile(r"\bmyself\b")
    _CRISIS_STEM = re.compile(
        r"\b(?:suicid\w*|self[-\s]?harm|disappear|end\s+my\s+life)\b|\bhate\s+my\s+body\b"
    )
    _DONT_WANT_LIVE = re.compile(
        r"\b(?:do not|don't|dont|not|never|no longer)\s+"
        r"(?:want(?:ing)?|wanna)\s+(?:to\s+)?(?:live|be\s+alive|stay\s+alive)\b"
    )
    _PURGE = re.compile(r"\bpurg\w*\b")
    _VOMIT = re.compile(r"\b(?:vomit\w*|puk\w*|throw(?:ing)?\s+up|threw\s+up)\b")
    _VOMIT_WITH = re.compile(
        r"\b(?:meals?|food|eat\w*|dinner|gains?|weight|calories?|purpose|myself|deliberately|intentionally|forced|fingers)\b"
    )
    _SICK_MYSELF = re.compile(r"\bmyself\s+sick\b|\bsick\b")
    _PILL = re.compile(
        r"\b(?:laxative\w*|diuretic\w*|diet\s+pills?|water\s+pills?|fat\s+burners?)\b"
    )
    _PILL_WITH = re.compile(r"\b(?:weight|lose|losing|cut|drops?|dropped|purg\w*|weigh-?in)\b")
    _STARVE = re.compile(r"\bstarv\w*\b")
    _STARVE_WITH = re.compile(r"\b(?:weight|myself|weigh-?in)\b")
    _RESTRICT = re.compile(
        r"\bhaven't\s+eaten\b|\bnot\s+eating\b|\bterrified\s+of\s+food\b|"
        r"\bafraid\s+to\s+eat\b|\bwater\s+cut\w*\b|\bpunish\w*\s+myself\b|"
        r"\b(?:barely|hardly|scarcely)\s+(?:eaten|ate|eating|eat)\b|"
        r"\b(?:barely|hardly)\s+(?:any\s+)?(?:food|calories)\b"
    )
    _CANT_LOAD = re.compile(
        r"\b(?:can't|cannot|couldn't|can\s+not|could\s+not)\s+"
        r"(?:walk\b|put\s+(?:any\s+)?weight\b)"
    )
    _POP_OR_SNAP = re.compile(r"\b(?:pop(?:ped)?|snap(?:ped)?)\b")
    _HEADACHE = re.compile(r"\bheadaches?\b")
    _WORSE = re.compile(r"\b(?:worse|worsening)\b")
    _POPPED = re.compile(r"\bpopped\b")
    _POP = re.compile(r"\bpop\b")
    _SNAP = re.compile(r"\bsnap(?:ped)?\b|\btendon\b")
    _JOINT = re.compile(
        r"\b(?:ankle|knee|wrist|shoulder|elbow|hip|hamstring|ligament|tendon|foot)\b"
    )
    _TORE = re.compile(r"\b(?:tore|torn|sprain\w*)\b")
    _PULLED = re.compile(r"\bpulled\b")
    _PULLED_WHAT = re.compile(r"\b(?:muscle|hamstring|groin|quad|calf|ligament)\b")
    _ROLL = re.compile(r"(?<!foam[ -])(?<![a-z-])(?:rolled|twisted|tweaked)\b")
    _SWELL = re.compile(r"\b(?:swollen|swelling|swelled)\b")
    _SHARP = re.compile(r"\bsharp\b")
    _FATIGUE = re.compile(
        r"\b(?:extreme|severe)\s+fatigue\b|\bcan't\s+get\s+out\s+of\s+bed\b"
    )
    _CONCUSS = re.compile(r"\bconcuss\w*\b")
    _HEAD = re.compile(r"\bhead\b")
    _NEURO = re.compile(
        r"\b(?:confus\w*|memory|stars|dazed|concuss\w*|"
        r"can't\s+remember|cannot\s+remember|don't\s+remember|do\s+not\s+remember)\b"
    )
    _CARDIAC_WORD = re.compile(r"\b(?:cardiac|myocardial)\b")
    _FAST = re.compile(r"\bfast(?:ing)?\b")
    _FINGERS = re.compile(r"\bfingers?\b")
    _THROAT = re.compile(r"\bthroat\b")
    _RHABDO = re.compile(r"\brhabdo\w*\b")
    _URINE = re.compile(r"\b(?:urine|pee|piss)\b")
    _URINE_COLOR = re.compile(r"\b(?:brown|dark|cola|tea|coke)\b")
    _HEAT = re.compile(r"\b(?:heat\w*|sweat\w*)\b")
    _STOPPED_SWEAT = re.compile(r"\b(?:stopped|stop|quit|not|no)\s+sweat\w*\b")
    _POP_NOISE = re.compile(r"\b(?:balloon|song|soda)\b")

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
        if "self_harm" in flags or "self_harm_thoughts" in flags:
            return "crisis"
        if any(f in flags for f in (
            "chest_pain", "cardiac_symptoms", "breathing_difficulty",
            "numbness", "rhabdomyolysis", "blue_lips", "stroke_signs",
            "heat_illness", "face_droop", "palpitations", "referred_pain",
            "blood_clot",
        )):
            return "cardiac"
        if "fainting" in flags:
            return "fainting"
        if "abnormal_bleeding" in flags or "head_injury" in flags:
            return "neurological"
        if "injury" in flags or "sharp_joint_pain" in flags or "tendon_snap" in flags:
            return "injury"
        if any(f in flags for f in ("disordered_eating", "very_low_intake", "purging")):
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

    def _clause_bounds(self, text: str, index: int):
        start = 0
        for match in self._CLAUSE_BOUNDARY.finditer(text):
            if match.start() >= index:
                return start, match.start()
            start = match.end()
        return start, len(text)

    def _paired(self, text: str, left: re.Pattern, right: re.Pattern) -> bool:
        """Both stems are present and not negated inside one clause."""
        for match in self._active(text, left):
            begin, end = self._clause_bounds(text, match.start())
            for other in self._active(text, right):
                if begin <= other.start() < end:
                    return True
        return False

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

    def _sentence_bounds(self, text: str, index: int):
        start = 0
        for mark in re.finditer(r"[.!?]", text):
            if mark.start() >= index:
                return start, mark.start()
            start = mark.end()
        return start, len(text)

    def _in_same_sentence(self, text: str, *patterns: re.Pattern) -> bool:
        """Every pattern has a non-negated hit inside one sentence."""
        if not patterns:
            return False
        for match in self._active(text, patterns[0]):
            begin, end = self._sentence_bounds(text, match.start())
            if all(
                any(begin <= other.start() < end for other in self._active(text, pattern))
                for pattern in patterns[1:]
            ):
                return True
        return False

    def _is_benign(self, text: str, end: int) -> bool:
        window = text[end:end + 90]
        return any(marker in window for marker in self._BENIGN)

    def _noise_clause(self, text: str, index: int) -> bool:
        begin, end = self._clause_bounds(text, index)
        return self._POP_NOISE.search(text[begin:end]) is not None

    def _has_very_low_intake(self, text: str) -> bool:
        for match in re.finditer(r"\b(\d{1,4})\s*(?:kcal|calories|cals)\b", text):
            amount = int(match.group(1))
            if amount >= 1000:
                continue
            window = text[max(0, match.start() - 40):match.end()]
            if re.search(r"\b(?:only|just|ate|eaten|eating)\b", window) and not self._is_negated(text, match.start()):
                return True
        return False

    def _detect_flags(self, text: str) -> Set[str]:
        """Stem backstop. A single symptom word is enough when the group needs one."""
        flags = set()
        if self._chest_hit(text):
            flags.add("chest_pain")
        if self._heart_hit(text) or self._active(text, self._CARDIAC_WORD):
            flags.add("cardiac_symptoms")
        if self._palpitation_hit(text):
            flags.add("palpitations")
        if self._referred_hit(text):
            flags.add("referred_pain")
        if self._clot_hit(text):
            flags.add("blood_clot")
        if self._breath_hit(text):
            flags.add("breathing_difficulty")
        if self._active(text, self._FAINT):
            flags.add("fainting")
        if self._active(text, self._NUMB):
            flags.add("numbness")
        if self._active(text, self._STROKE):
            flags.add("stroke_signs")
        if self._paired(text, self._BLOOD, self._BLOOD_WITH):
            flags.add("abnormal_bleeding")
        if self._paired(text, self._BLUE, self._LIPS):
            flags.add("blue_lips")
        if self._self_harm_hit(text):
            flags.add("self_harm")
        if self._eating_hit(text) or self._has_very_low_intake(text):
            flags.add("disordered_eating")
        if self._active(text, self._RHABDO) or self._paired(text, self._URINE, self._URINE_COLOR):
            flags.add("rhabdomyolysis")
        flags.update(self._injury_flags(text))
        if (
            self._active(text, self._CONCUSS)
            or self._same_sentence(text, self._HEAD, self._NEURO)
            or self._same_sentence(text, self._HEAD, self._VOMIT)
            or self._in_same_sentence(text, self._HEAD, self._HEADACHE, self._WORSE)
        ):
            flags.add("head_injury")
        if self._active(text, self._STOPPED_SWEAT) or self._same_sentence(text, self._HEAT, self._NEURO):
            flags.add("heat_illness")
        if self._active(text, self._FATIGUE):
            flags.add("extreme_fatigue")
        return flags

    def _chest_hit(self, text: str) -> bool:
        for chest in self._active(text, self._CHEST):
            if re.match(r"\s+day\b", text[chest.end():chest.end() + 6]):
                continue
            begin, end = self._clause_bounds(text, chest.start())
            for mark in self._active(text, self._CHEST_MARK):
                if begin <= mark.start() < end:
                    return True
        return False

    def _heart_hit(self, text: str) -> bool:
        for heart in self._active(text, self._HEART):
            begin, end = self._clause_bounds(text, heart.start())
            for mark in self._active(text, self._HEART_MARK):
                if not (begin <= mark.start() < end):
                    continue
                word = mark.group(0)
                if word in {"racing", "pounding"} and self._is_benign(text, mark.end()):
                    continue
                if word == "stopped" and re.match(
                    r"\s+(?:racing|pounding)\b", text[mark.end():mark.end() + 12]
                ):
                    continue
                return True
        return False

    def _breath_hit(self, text: str) -> bool:
        for match in self._active(text, self._BREATH):
            if match.group(0) in {"gasping", "gasp"} and self._is_benign(text, match.end()):
                continue
            return True
        return False

    def _crisis_idiom(self, text: str, match: re.Match) -> bool:
        """Gym talk such as 'kill for a burger' or 'dying on that last set'."""
        word = match.group(0)
        after = text[match.end():match.end() + 12]
        if word.startswith("kill") and re.match(r"\s+for\b", after):
            return True
        if word == "die" and re.match(r"\s+for\b", after):
            return True
        if word == "dying" and re.match(r"\s+(?:on|for)\b", after):
            return True
        return False

    def _self_harm_hit(self, text: str) -> bool:
        if self._active(text, self._CRISIS_STEM) or self._active(text, self._DONT_WANT_LIVE):
            return True
        for match in self._active(text, self._CRISIS_VERB):
            if self._crisis_idiom(text, match):
                continue
            begin, end = self._clause_bounds(text, match.start())
            if any(begin <= other.start() < end for other in self._active(text, self._SPEAKER)):
                return True
        return self._paired(text, self._HARM_VERB, self._MYSELF)

    def _palpitation_hit(self, text: str) -> bool:
        if self._active(text, self._PALP):
            return True
        return self._in_same_sentence(text, self._SKIPPED_BEAT, self._LIGHTHEADED)

    def _referred_hit(self, text: str) -> bool:
        if self._in_same_sentence(text, self._REFERRED_PART, self._PAIN_WORD, self._SWEAT):
            return True
        return self._in_same_sentence(text, self._CHEST, self._PAIN_WORD, self._AT_REST)

    def _clot_hit(self, text: str) -> bool:
        for limb in self._active(text, self._LIMB):
            if limb.group(0).startswith("leg") and re.match(
                r"\s+day\b", text[limb.end():limb.end() + 6]
            ):
                continue
            begin, end = self._sentence_bounds(text, limb.start())
            for mark in self._active(text, self._CLOT_MARK):
                if not (begin <= mark.start() < end):
                    continue
                if mark.group(0) == "hot" and re.match(
                    r"\s+yoga\b", text[mark.end():mark.end() + 8]
                ):
                    continue
                return True
            if any(begin <= trip.start() < end for trip in self._active(text, self._TRAVEL)):
                if any(begin <= sore.start() < end for sore in self._active(text, self._SORE)):
                    return True
        return False

    def _eating_hit(self, text: str) -> bool:
        if self._active(text, self._PURGE) or self._active(text, self._RESTRICT):
            return True
        if self._paired(text, self._VOMIT, self._VOMIT_WITH):
            return True
        if self._paired(text, self._PILL, self._PILL_WITH):
            return True
        if self._paired(text, self._STARVE, self._STARVE_WITH):
            return True
        if self._paired(text, self._FAST, self._STARVE_WITH):
            return True
        if self._paired(text, self._FINGERS, self._THROAT):
            return True
        return self._paired(text, self._MYSELF, re.compile(r"\bsick\b"))

    def _injury_flags(self, text: str) -> Set[str]:
        flags = set()
        for match in self._active(text, self._POPPED):
            if not self._noise_clause(text, match.start()):
                flags.add("injury")
        for match in self._active(text, self._POP):
            if self._noise_clause(text, match.start()):
                continue
            begin, end = self._clause_bounds(text, match.start())
            if any(begin <= joint.start() < end for joint in self._active(text, self._JOINT)):
                flags.add("injury")
        tore = False
        for match in self._active(text, self._TORE):
            if re.match(r"\s+through\b", text[match.end():match.end() + 12]):
                continue
            tore = True
        if tore or self._active(text, self._SNAP):
            flags.add("injury")
        if self._load_bearing_injury(text):
            flags.add("injury")
        if self._paired(text, self._PULLED, self._PULLED_WHAT):
            flags.add("injury")
        for match in self._active(text, self._ROLL):
            if re.match(r"\s+out\b", text[match.end():match.end() + 6]):
                continue
            begin, end = self._clause_bounds(text, match.start())
            if any(begin <= joint.start() < end for joint in self._active(text, self._JOINT)):
                flags.add("injury")
        if self._paired(text, self._SWELL, self._JOINT):
            flags.add("injury")
        if self._paired(text, self._SHARP, self._JOINT):
            flags.add("sharp_joint_pain")
        return flags

    def _load_bearing_injury(self, text: str) -> bool:
        """Can't walk or bear weight counts only together with a pop or snap."""
        if not self._active(text, self._CANT_LOAD):
            return False
        for match in self._active(text, self._POP_OR_SNAP):
            if self._noise_clause(text, match.start()):
                continue
            begin, end = self._sentence_bounds(text, match.start())
            if any(begin <= other.start() < end for other in self._active(text, self._CANT_LOAD)):
                return True
        return False

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

    def _text_clear(self) -> RedFlagResult:
        """A text backstop with nothing to flag. It is not clearance to continue."""
        return RedFlagResult(
            pause_plan=False,
            flags_detected=[],
            message=(
                "No red flags in this text. "
                "A complete symptom checklist is still required."
            ),
            recommendations=[],
        )

    def scan_text(self, text: str) -> RedFlagResult:
        """
        Backstop scan of free text.

        This is not the check-in gate. A clear result does not continue the plan.
        Malformed text pauses and asks.
        """
        if not isinstance(text, str):
            return self._ask("I couldn't read that message. Can you tell me how you're feeling?")

        cleaned = InputValidator.clean_text(text)
        if not cleaned.strip():
            return self._text_clear()

        flags_detected = self._detect_flags(cleaned)
        if not flags_detected:
            return self._text_clear()

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

        if severity == "crisis" or "self_harm" in flags or "self_harm_thoughts" in flags:
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
        
        if "injury" in flags or "sharp_joint_pain" in flags or "tendon_snap" in flags:
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
                "A head impact with confusion, memory loss, vomiting, "
                "a worsening headache, or concussion signs "
                "needs a doctor before any further training."
            )
        
        if any(name in flags for name in ("disordered_eating", "very_low_intake", "purging")):
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

    def _normalize_key(self, key) -> str:
        text = InputValidator.normalize_unicode(str(key)).lower().strip()
        text = text.replace("&", " and ")
        return re.sub(r"[^a-z0-9]+", "_", text).strip("_")

    def _alias_map(self) -> Dict[str, str]:
        mapping = {}
        for flag, aliases in self.CHECKLIST_GROUPS:
            for alias in aliases:
                mapping[alias] = flag
        return mapping

    def _coerce_answers(self, raw):
        if isinstance(raw, dict):
            return raw, None
        if isinstance(raw, list):
            coerced = {}
            for item in raw:
                if not isinstance(item, dict):
                    return None, "Each checklist entry has to be a yes or no."
                name = None
                for key in ("question", "item", "symptom", "name", "key", "id"):
                    if key in item:
                        name = item[key]
                        break
                value = None
                for key in ("answer", "value", "response", "yes_no"):
                    if key in item:
                        value = item[key]
                        break
                if name is None or value is None:
                    return None, "Each checklist entry needs a symptom and a yes or no."
                coerced[str(name)] = value
            return coerced, None
        return None, "The symptom checklist has to be yes or no answers."

    def _find_checklist(self, check_in: Dict):
        aliases = self._alias_map()
        for key, value in check_in.items():
            norm = self._normalize_key(key)
            if norm in self.CHECKLIST_CONTAINERS or (
                norm == "symptoms" and isinstance(value, (dict, list))
            ):
                return self._coerce_answers(value)
        flat = {
            key: value
            for key, value in check_in.items()
            if self._normalize_key(key) in aliases
        }
        if flat:
            return flat, None
        return None, "missing"

    def _score_checklist(self, answers: Dict):
        aliases = self._alias_map()
        grouped = {flag: [] for flag, _aliases in self.CHECKLIST_GROUPS}
        errors = []
        unknown = []
        for key, value in answers.items():
            flag = aliases.get(self._normalize_key(key))
            if flag is None:
                unknown.append(str(key))
                continue
            try:
                grouped[flag].append(InputValidator.parse_boolean(value, str(key)))
            except ValidationError as error:
                errors.append(str(error))
        if unknown:
            errors.append(
                "Unknown checklist item: " + ", ".join(unknown) + "."
            )
        missing = [
            self.ITEM_LABELS.get(flag, flag.replace("_", " "))
            for flag, values in grouped.items()
            if not values
        ]
        yes_flags = {flag for flag, values in grouped.items() if any(values)}
        if errors or missing:
            parts = list(errors)
            if missing:
                parts.append(
                    "The symptom checklist is incomplete. Still need: "
                    + ", ".join(missing)
                    + "."
                )
            return yes_flags, " ".join(parts)
        return yes_flags, None

    def _from_flags(self, flags: Set[str]) -> RedFlagResult:
        if not flags:
            return self._clear()
        severity = self._classify_severity(flags)
        return RedFlagResult(
            pause_plan=True,
            flags_detected=sorted(flags),
            message=self.SEVERITY_MESSAGES[severity],
            recommendations=self._generate_recommendations(flags, severity),
        )

    def scan_check_in(self, check_in: Dict) -> RedFlagResult:
        """
        Every check-in needs a yes/no symptom checklist.

        A missing, incomplete, or malformed checklist pauses and asks.
        Any yes is a red flag. Free text is still scanned as a backstop.
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

        aliases = self._alias_map()
        unknown_fields = []
        text_parts = []
        for key, value in check_in.items():
            norm = self._normalize_key(key)
            known = (
                norm in self.KNOWN_FIELDS
                or norm in self.CHECKLIST_CONTAINERS
                or norm in aliases
            )
            if not known:
                unknown_fields.append(str(key))
            checklist_value = norm in self.CHECKLIST_CONTAINERS or (
                norm == "symptoms" and isinstance(value, (dict, list))
            )
            if checklist_value or norm in aliases:
                continue
            text_parts.append(self._flatten(value))

        scanned = self.scan_text(" ".join(text_parts)) if any(part.strip() for part in text_parts) else self._clear()
        answers, find_error = self._find_checklist(check_in)
        questions = []
        checklist_flags = set()
        if find_error == "missing":
            questions.append(
                "The symptom checklist is missing. Please answer yes or no for each symptom."
            )
        elif find_error:
            questions.append(find_error)
        else:
            checklist_flags, score_error = self._score_checklist(answers)
            if score_error:
                questions.append(score_error)
        if unknown_fields:
            names = ", ".join(unknown_fields)
            questions.append(f"I don't recognize '{names}'. Can you tell me what you mean?")

        flags = {flag for flag in scanned.flags_detected if flag != "needs_clarification"}
        flags.update(checklist_flags)
        result = self._from_flags(flags)
        if questions:
            return self._with_question(result, " ".join(questions))
        return result

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
