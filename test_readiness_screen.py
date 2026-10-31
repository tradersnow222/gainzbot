#!/usr/bin/env python3
"""Tests for readiness_screen.py screening guardrails."""

from datetime import datetime, timedelta, timezone

import pytest
from readiness_screen import ReadinessScreen, ClearanceLevel, passing_readiness


def complete_par_q(**overrides):
    """Every PAR-Q question answered, defaults to no."""
    answers = {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS}
    answers.update(overrides)
    return answers


class TestAgeCheck:
    """Test age requirement checks."""
    
    def test_adult_clear(self):
        """Adults over 18 get clear status."""
        screener = ReadinessScreen()
        result = screener.check_age(25)
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked
    
    def test_minor_without_consent_blocked(self):
        """Minors without parental consent are blocked."""
        screener = ReadinessScreen()
        result = screener.check_age(16, has_parental_consent=False)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert "under 18" in result.reasons[0]
    
    def test_minor_with_consent_caution(self):
        """Minors with parental consent get caution status."""
        screener = ReadinessScreen()
        result = screener.check_age(16, has_parental_consent=True)
        assert result.clearance == ClearanceLevel.CAUTION
        assert not result.blocked
        assert "parental consent" in result.reasons[0]


class TestPARQ:
    """Test PAR-Q+ style screening."""
    
    def test_all_clear_responses(self):
        """All 'no' responses get clear status."""
        screener = ReadinessScreen()
        result = screener.check_par_q(complete_par_q())
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked
    
    def test_chest_pain_at_rest_blocked(self):
        """Chest pain at rest requires clearance."""
        screener = ReadinessScreen()
        responses = {
            "chest_pain_at_rest": True,
            "chest_pain_during_activity": False,
            "loss_of_balance_dizziness": False,
            "loss_of_consciousness": False,
            "bone_joint_problem_worsened_by_activity": False,
        }
        result = screener.check_par_q(responses)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert "Chest Pain At Rest" in result.reasons[0]
    
    def test_loss_of_consciousness_blocked(self):
        """Loss of consciousness requires clearance."""
        screener = ReadinessScreen()
        responses = {
            "chest_pain_at_rest": False,
            "chest_pain_during_activity": False,
            "loss_of_balance_dizziness": False,
            "loss_of_consciousness": True,
            "bone_joint_problem_worsened_by_activity": False,
        }
        result = screener.check_par_q(responses)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
    
    def test_multiple_red_flags(self):
        """Multiple red flags all captured in reasons."""
        screener = ReadinessScreen()
        responses = {
            "chest_pain_at_rest": True,
            "chest_pain_during_activity": True,
            "loss_of_balance_dizziness": False,
            "loss_of_consciousness": False,
            "bone_joint_problem_worsened_by_activity": False,
        }
        result = screener.check_par_q(responses)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert "Chest Pain At Rest" in result.reasons[0]
        assert "Chest Pain During Activity" in result.reasons[0]


class TestPregnancy:
    """Test pregnancy screening."""
    
    def test_not_pregnant_clear(self):
        """Non-pregnant users get clear status."""
        screener = ReadinessScreen()
        result = screener.check_pregnancy(is_pregnant=False)
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked
    
    def test_pregnant_without_clearance_blocked(self):
        """Pregnant without clearance is blocked."""
        screener = ReadinessScreen()
        result = screener.check_pregnancy(is_pregnant=True, has_clearance=False)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert "pregnant" in result.reasons[0].lower()
    
    def test_pregnant_with_clearance_caution(self):
        """Pregnant with clearance gets caution status."""
        screener = ReadinessScreen()
        result = screener.check_pregnancy(is_pregnant=True, has_clearance=True)
        assert result.clearance == ClearanceLevel.CAUTION
        assert not result.blocked
        assert "clearance" in result.reasons[0].lower()
        assert "Modified programming" in result.recommendations[0]


class TestMedicalConditions:
    """Test medical condition screening."""
    
    def test_no_conditions_clear(self):
        """No medical conditions get clear status."""
        screener = ReadinessScreen()
        result = screener.check_medical_conditions([], has_clearance=False)
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked
    
    def test_heart_disease_without_clearance_blocked(self):
        """Heart disease without clearance is blocked."""
        screener = ReadinessScreen()
        result = screener.check_medical_conditions(
            ["heart_disease"],
            has_clearance=False
        )
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert "Heart Disease" in result.reasons[0]
    
    def test_diabetes_without_clearance_blocked(self):
        """Diabetes without clearance is blocked."""
        screener = ReadinessScreen()
        result = screener.check_medical_conditions(
            ["diabetes"],
            has_clearance=False
        )
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
    
    def test_high_blood_pressure_with_clearance_caution(self):
        """High BP with clearance gets caution status."""
        screener = ReadinessScreen()
        result = screener.check_medical_conditions(
            ["high_blood_pressure"],
            has_clearance=True
        )
        assert result.clearance == ClearanceLevel.CAUTION
        assert not result.blocked
        assert "High Blood Pressure" in result.reasons[0]
    
    def test_multiple_conditions_without_clearance(self):
        """Multiple conditions all captured."""
        screener = ReadinessScreen()
        result = screener.check_medical_conditions(
            ["heart_disease", "diabetes"],
            has_clearance=False
        )
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert "Heart Disease" in result.reasons[0]
        assert "Diabetes" in result.reasons[0]
    
    def test_unrelated_condition_blocks_for_review(self):
        """Unrecognized conditions block for review."""
        screener = ReadinessScreen()
        result = screener.check_medical_conditions(
            ["seasonal_allergies"],
            has_clearance=False
        )
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert "unrecognized" in result.reasons[0].lower()


class TestCompleteIntake:
    """Test complete intake screening."""
    
    def test_clean_intake_clear(self):
        """Clean intake with no risk factors."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": complete_par_q(),
            "pregnant": False,
            "medical_conditions": [],
            "medical_clearance": False
        }
        result = screener.screen_intake(intake)
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked
        assert "No risk factors" in result.reasons[0]
    
    def test_par_q_flag_blocks(self):
        """PAR-Q red flag blocks intake."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": {
                "chest_pain_at_rest": True,
                "chest_pain_during_activity": False,
                "loss_of_balance_dizziness": False,
                "loss_of_consciousness": False,
                "bone_joint_problem_worsened_by_activity": False,
            },
            "pregnant": False,
            "medical_conditions": [],
        }
        result = screener.screen_intake(intake)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
    
    def test_multiple_issues_highest_level(self):
        """Multiple issues return highest clearance level."""
        screener = ReadinessScreen()
        intake = {
            "age": 16,
            "parental_consent": True,
            "par_q": complete_par_q(),
            "pregnant": False,
            "medical_conditions": ["diabetes"],
            "medical_clearance": False
        }
        result = screener.screen_intake(intake)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
        assert len(result.reasons) >= 2
    
    def test_caution_level_not_blocked(self):
        """Caution level allows program but with recommendations."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": complete_par_q(),
            "pregnant": True,
            "pregnancy_clearance": True,
            "medical_conditions": [],
        }
        result = screener.screen_intake(intake)
        assert result.clearance == ClearanceLevel.CAUTION
        assert not result.blocked
        assert len(result.recommendations) > 0
    
    def test_minimal_intake_defaults(self):
        """Minimal intake with defaults doesn't crash."""
        screener = ReadinessScreen()
        intake = {}
        result = screener.screen_intake(intake)
        assert result is not None
        assert result.blocked
        assert isinstance(result.clearance, ClearanceLevel)


class TestMessyInput:
    """Test handling of messy and invalid input."""
    
    def test_string_age_parsed(self):
        """String age is parsed."""
        screener = ReadinessScreen()
        intake = {
            "age": "25",
            "par_q": complete_par_q(),
            "medical_conditions": []
        }
        result = screener.screen_intake(intake)
        assert result.clearance == ClearanceLevel.CLEAR
    
    def test_invalid_age_rejected(self):
        """Invalid age string is rejected."""
        screener = ReadinessScreen()
        intake = {
            "age": "abc",
            "par_q": {},
            "medical_conditions": []
        }
        result = screener.screen_intake(intake)
        assert result.blocked
        assert "age" in result.reasons[0].lower()
    
    def test_negative_age_rejected(self):
        """Negative age is rejected."""
        screener = ReadinessScreen()
        intake = {
            "age": -5,
            "par_q": {},
            "medical_conditions": []
        }
        result = screener.screen_intake(intake)
        assert result.blocked
    
    def test_age_under_13_blocked(self):
        """Age under 13 is blocked."""
        screener = ReadinessScreen()
        intake = {
            "age": 12,
            "parental_consent": True,
            "par_q": {},
            "medical_conditions": []
        }
        result = screener.screen_intake(intake)
        assert result.blocked
        assert "13" in result.reasons[0]
    
    def test_age_13_to_17_requires_consent(self):
        """Ages 13-17 require parental consent."""
        screener = ReadinessScreen()
        intake = {
            "age": 15,
            "parental_consent": False,
            "par_q": {},
            "medical_conditions": []
        }
        result = screener.screen_intake(intake)
        assert result.blocked
        assert "parental" in result.reasons[0].lower()
    
    def test_age_15_with_consent_caution(self):
        """Age 15 with consent gets caution."""
        screener = ReadinessScreen()
        intake = {
            "age": 15,
            "parental_consent": True,
            "par_q": complete_par_q(),
            "medical_conditions": []
        }
        result = screener.screen_intake(intake)
        assert result.clearance == ClearanceLevel.CAUTION
        assert not result.blocked
    
    def test_comma_separated_conditions(self):
        """Comma-separated conditions string is parsed."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": complete_par_q(),
            "medical_conditions": "heart_disease, diabetes",
            "medical_clearance": False
        }
        result = screener.screen_intake(intake)
        assert result.blocked
        assert "heart" in result.reasons[0].lower() or "diabetes" in result.reasons[0].lower()


class TestConditionNormalization:
    """Test medical condition normalization."""
    
    def test_hypertension_normalized(self):
        """'Hypertension' is normalized to 'high_blood_pressure'."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": {},
            "medical_conditions": ["hypertension"],
            "medical_clearance": False
        }
        result = screener.screen_intake(intake)
        assert result.blocked
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
    
    def test_type_2_diabetes_normalized(self):
        """'Type 2 diabetes' is normalized."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": {},
            "medical_conditions": ["Type 2 diabetes"],
            "medical_clearance": False
        }
        result = screener.screen_intake(intake)
        assert result.blocked
    
    def test_title_case_condition(self):
        """Title case condition is handled."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": {},
            "medical_conditions": ["Heart Disease"],
            "medical_clearance": False
        }
        result = screener.screen_intake(intake)
        assert result.blocked
    
    def test_unrecognized_condition_blocks(self):
        """Unrecognized condition blocks until review."""
        screener = ReadinessScreen()
        intake = {
            "age": 30,
            "par_q": complete_par_q(),
            "medical_conditions": ["unknown_illness"],
            "medical_clearance": False
        }
        result = screener.screen_intake(intake)
        assert result.blocked
        assert "unrecognized" in result.reasons[0].lower()


class TestNewPARQQuestions:
    """Test new PAR-Q+ questions."""
    
    def test_medications_flag_blocks(self):
        """Currently taking medications flag blocks."""
        screener = ReadinessScreen()
        responses = {
            "chest_pain_at_rest": False,
            "chest_pain_during_activity": False,
            "loss_of_balance_dizziness": False,
            "loss_of_consciousness": False,
            "bone_joint_problem_worsened_by_activity": False,
            "currently_taking_medications": True,
        }
        result = screener.check_par_q(responses)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked
    
    def test_doctor_supervised_only_blocks(self):
        """Doctor advised supervised only blocks."""
        screener = ReadinessScreen()
        responses = {
            "chest_pain_at_rest": False,
            "chest_pain_during_activity": False,
            "loss_of_balance_dizziness": False,
            "loss_of_consciousness": False,
            "bone_joint_problem_worsened_by_activity": False,
            "doctor_advised_supervised_only": True,
        }
        result = screener.check_par_q(responses)
        assert result.clearance == ClearanceLevel.NEEDS_DOCTOR_CLEARANCE
        assert result.blocked


class TestReviewerProbes:
    """Reviewer probes for readiness_screen. Each case asserts block or pass."""

    def setup_method(self):
        self.screen = ReadinessScreen()

    def _reasons(self, intake):
        result = self.screen.screen_intake(intake)
        return result, " ".join(result.reasons).lower()

    def test_empty_intake_blocks(self):
        result, _ = self._reasons({})
        assert result.blocked
        assert "no risk factors" not in " ".join(result.reasons).lower()

    def test_missing_age_and_par_q_blocks(self):
        result, text = self._reasons({"pregnant": False})
        assert result.blocked
        assert "age" in text

    def test_age_15_without_consent_blocks(self):
        result, text = self._reasons({"age": 15})
        assert result.blocked
        assert "without parental consent" in text

    def test_age_9_with_consent_blocks(self):
        result, text = self._reasons({"age": 9, "parental_consent": True})
        assert result.blocked
        assert "13" in text

    def test_age_15_consent_no_string_blocks(self):
        result, text = self._reasons({"age": 15, "parental_consent": "no"})
        assert result.blocked
        assert "without parental consent" in text
        assert "has parental consent" not in text

    def test_age_string_16_without_consent_blocks(self):
        result, text = self._reasons({"age": "16"})
        assert result.blocked
        assert "without parental consent" in text

    def test_age_none_blocks(self):
        result, text = self._reasons({"age": None})
        assert result.blocked
        assert "age" in text

    @pytest.mark.parametrize(
        "condition,marker",
        [
            ("Heart Disease", "heart disease"),
            ("high blood pressure", "high blood pressure"),
            ("hypertension", "high blood pressure"),
            ("type 2 diabetes", "type 2 diabetes"),
            ("Type 1 Diabetes", "type 1 diabetes"),
            ("heart_disease ", "heart disease"),
            ("takes blood pressure medication", "unrecognized"),
            ("Hypertension\u2019s fine now", "unrecognized"),
            ("afib", "unrecognized"),
            ("COPD", "unrecognized"),
            ("epilepsy", "unrecognized"),
        ],
    )
    def test_real_conditions_block(self, condition, marker):
        result, text = self._reasons({"age": 40, "medical_conditions": [condition]})
        assert result.blocked
        assert marker in text

    @pytest.mark.parametrize("condition", ["none", "N/A", "no", ""])
    def test_no_condition_words_are_not_conditions(self, condition):
        result, text = self._reasons({"age": 40, "medical_conditions": [condition]})
        assert result.blocked
        assert "unrecognized" not in text
        assert "par-q" in text

    def test_condition_string_diabetes_blocks(self):
        result, text = self._reasons({"age": 40, "medical_conditions": "diabetes"})
        assert result.blocked
        assert "diabetes" in text

    def test_condition_string_comma_blocks(self):
        result, text = self._reasons({"age": 40, "medical_conditions": "asthma, diabetes"})
        assert result.blocked
        assert "asthma" in text and "diabetes" in text

    def test_condition_string_and_blocks(self):
        result, text = self._reasons({"age": 40, "medical_conditions": "asthma and diabetes"})
        assert result.blocked
        assert "asthma" in text and "diabetes" in text

    def test_condition_dict_blocks(self):
        result, text = self._reasons({"age": 40, "medical_conditions": {"heart_disease": True}})
        assert result.blocked
        assert "no risk factors" not in text

    def test_condition_list_with_non_text_blocks(self):
        result, text = self._reasons({"age": 40, "medical_conditions": [None, 5]})
        assert result.blocked
        assert "no risk factors" not in text

    def test_par_q_typo_blocks(self):
        result, text = self._reasons({"age": 40, "par_q": {"chest_pain": True}})
        assert result.blocked
        assert "unknown" in text
        assert "chest_pain" in text

    def test_par_q_no_string_is_not_a_yes(self):
        result, text = self._reasons({"age": 40, "par_q": {"chest_pain_at_rest": "no"}})
        assert result.blocked
        assert "red flag" not in text

    def test_par_q_yes_string_blocks(self):
        result, text = self._reasons({"age": 40, "par_q": {"chest_pain_at_rest": "yes"}})
        assert result.blocked
        assert "red flag" in text

    def test_par_q_list_blocks_without_crashing(self):
        result, text = self._reasons({"age": 40, "par_q": ["chest_pain_at_rest"]})
        assert result.blocked
        assert "no risk factors" not in text

    def test_par_q_empty_dict_blocks(self):
        result, text = self._reasons({"age": 40, "par_q": {}})
        assert result.blocked
        assert "incomplete" in text or "par-q" in text

    def test_pregnant_no_string_is_not_pregnant(self):
        result, text = self._reasons({"age": 30, "pregnant": "no"})
        assert result.blocked
        assert "pregnant" not in text

    def test_pregnancy_clearance_false_string_blocks(self):
        result, text = self._reasons(
            {"age": 30, "pregnant": "yes", "pregnancy_clearance": "false"}
        )
        assert result.blocked
        assert "without medical clearance" in text

    def test_medical_clearance_false_string_blocks(self):
        result, text = self._reasons(
            {
                "age": 40,
                "medical_conditions": ["heart_disease"],
                "medical_clearance": "false",
            }
        )
        assert result.blocked
        assert "without clearance" in text

    def test_pregnancy_ignores_medical_clearance_only(self):
        result, text = self._reasons(
            {"age": 30, "pregnant": True, "medical_clearance": True}
        )
        assert result.blocked
        assert "without medical clearance" in text

    def test_full_clean_adult_passes(self):
        result = self.screen.screen_intake(
            {
                "age": 32,
                "par_q": {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS},
                "pregnant": False,
                "medical_conditions": [],
                "medical_clearance": False,
            }
        )
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked


class TestP2bProbes:
    """Follow-up probes. Each case must block or pass as specified."""

    def setup_method(self):
        self.screen = ReadinessScreen()
        self.pq = {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS}

    def _screen(self, intake):
        result = self.screen.screen_intake(intake)
        return result, " ".join(result.reasons)

    def test_full_par_q_no_strings_clear(self):
        result, _ = self._screen(
            {"age": 30, "par_q": {k: "no" for k in ReadinessScreen.PAR_Q_RED_FLAGS}}
        )
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked

    def test_full_par_q_curly_no_clear(self):
        result, _ = self._screen(
            {"age": 30, "par_q": {k: "\u201cNo\u201d" for k in ReadinessScreen.PAR_Q_RED_FLAGS}}
        )
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked

    def test_one_yes_blocks(self):
        result, text = self._screen(
            {"age": 30, "par_q": {**self.pq, "chest_pain_at_rest": "Yes "}}
        )
        assert result.blocked
        assert "chest pain at rest" in text.lower()

    def test_maybe_blocks(self):
        result, _ = self._screen(
            {"age": 30, "par_q": {**self.pq, "loss_of_consciousness": "maybe"}}
        )
        assert result.blocked

    def test_none_answer_blocks(self):
        result, _ = self._screen(
            {"age": 30, "par_q": {**self.pq, "loss_of_consciousness": None}}
        )
        assert result.blocked

    def test_numeric_two_blocks(self):
        result, _ = self._screen(
            {"age": 30, "par_q": {**self.pq, "loss_of_consciousness": 2}}
        )
        assert result.blocked

    def test_condition_none_with_full_par_q_clear(self):
        result, _ = self._screen(
            {"age": 30, "par_q": self.pq, "medical_conditions": ["none"]}
        )
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked

    def test_condition_na_with_full_par_q_clear(self):
        result, _ = self._screen(
            {"age": 30, "par_q": self.pq, "medical_conditions": "N/A"}
        )
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked

    def test_none_plus_diabetes_blocks(self):
        result, text = self._screen(
            {"age": 30, "par_q": self.pq, "medical_conditions": "none, diabetes"}
        )
        assert result.blocked
        assert "diabetes" in text.lower()

    def test_clearance_false_string_blocks(self):
        result, _ = self._screen(
            {
                "age": 40,
                "par_q": self.pq,
                "medical_conditions": ["heart disease"],
                "medical_clearance": "false",
            }
        )
        assert result.blocked

    def test_clearance_true_string_is_caution(self):
        result, _ = self._screen(
            {
                "age": 40,
                "par_q": self.pq,
                "medical_conditions": ["heart disease"],
                "medical_clearance": "true",
            }
        )
        assert result.clearance == ClearanceLevel.CAUTION
        assert not result.blocked

    def test_pregnant_no_clear(self):
        result, _ = self._screen({"age": 30, "par_q": self.pq, "pregnant": "no"})
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked

    def test_pregnant_maybe_blocks(self):
        result, _ = self._screen({"age": 30, "par_q": self.pq, "pregnant": "maybe"})
        assert result.blocked

    def test_pregnant_yes_clearance_false_blocks(self):
        result, _ = self._screen(
            {
                "age": 30,
                "par_q": self.pq,
                "pregnant": "yes",
                "pregnancy_clearance": "false",
            }
        )
        assert result.blocked

    def test_age_15_consent_no_blocks(self):
        result, _ = self._screen(
            {"age": 15, "par_q": self.pq, "parental_consent": "no"}
        )
        assert result.blocked

    def test_age_15_consent_yes_caution(self):
        result, _ = self._screen(
            {"age": 15, "par_q": self.pq, "parental_consent": "yes"}
        )
        assert result.clearance == ClearanceLevel.CAUTION
        assert not result.blocked

    def test_age_200_blocks(self):
        result, text = self._screen({"age": 200, "par_q": self.pq})
        assert result.blocked
        assert "plausible" in text.lower()

    def test_age_100_with_full_par_q_clear(self):
        result, _ = self._screen({"age": 100, "par_q": self.pq})
        assert result.clearance == ClearanceLevel.CLEAR
        assert not result.blocked

    def test_age_17_9_blocks_even_with_consent(self):
        result, _ = self._screen(
            {"age": 17.9, "par_q": self.pq, "parental_consent": "yes"}
        )
        assert result.blocked

    def test_misspelled_pregnant_blocks_with_hint(self):
        result, text = self._screen({"age": 30, "par_q": self.pq, "pregnent": True})
        assert result.blocked
        assert "did you mean 'pregnant'" in text.lower()

    def test_misspelled_conditions_blocks_with_hint(self):
        result, text = self._screen(
            {"age": 30, "par_q": self.pq, "conditions": ["heart disease"]}
        )
        assert result.blocked
        assert "did you mean 'medical_conditions'" in text.lower()
        assert result.clearance != ClearanceLevel.CLEAR

    def test_unknown_key_without_close_match_still_blocks(self):
        result, text = self._screen({"age": 30, "par_q": self.pq, "hobby": "lifting"})
        assert result.blocked
        assert "unknown key" in text.lower()

    def test_intake_list_blocks(self):
        result, text = self._screen([1])
        assert result.blocked
        assert "object" in text.lower()

    def test_intake_none_blocks(self):
        result, _ = self._screen(None)
        assert result.blocked


class TestDoctorClearance:
    """A doctor's clearance passes a PAR-Q yes. Acute proof is not required."""

    def setup_method(self):
        self.screen = ReadinessScreen()
        self.pq = {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS}

    def _chest(self, **extra):
        intake = {
            "age": 34,
            "par_q": {**self.pq, "chest_pain_at_rest": True, "chest_pain_during_activity": "yes"},
        }
        intake.update(extra)
        return self.screen.screen_intake(intake)

    def test_a_spoken_clearance_passes_chest_pain_and_keeps_the_answers(self):
        result = self._chest(
            medical_clearance="my doctor cleared me for exercise",
            clearance_date="2026-10-01",
        )
        assert result.blocked is False
        assert result.clearance == ClearanceLevel.CAUTION
        assert passing_readiness(result)
        assert result.doctor_cleared is True
        assert result.clearance_date == "2026-10-01"
        assert result.par_q["chest_pain_at_rest"] is True
        assert result.par_q["chest_pain_during_activity"] is True
        assert result.par_q["loss_of_consciousness"] is False
        text = " ".join(result.reasons).lower()
        assert "chest pain at rest: yes" in text
        assert "chest pain during activity: yes" in text
        assert "loss of consciousness: no" in text
        follows = [
            rec for rec in result.recommendations
            if rec == "The plan follows the doctor's clearance."
        ]
        assert follows == ["The plan follows the doctor's clearance."]
        blob = " ".join(result.reasons + result.recommendations).lower()
        assert "proof" not in blob
        assert "document" not in blob
        assert "doctor's note" not in blob
        changed = result
        changed.par_q = dict(result.par_q)
        changed.par_q["chest_pain_at_rest"] = False
        assert passing_readiness(changed) is False

    def test_a_boolean_clearance_records_today_when_no_date_is_given(self):
        result = self._chest(medical_clearance=True)
        assert passing_readiness(result)
        assert result.clearance_date == datetime.now(timezone.utc).date().isoformat()
        assert result.recommendations.count("The plan follows the doctor's clearance.") == 1

    def test_chest_pain_without_clearance_still_blocks(self):
        result = self._chest(medical_clearance=False)
        assert result.blocked
        assert result.doctor_cleared is False
        assert passing_readiness(result) is False
        assert "The plan follows the doctor's clearance." not in result.recommendations

    def test_a_denied_clearance_does_not_pass(self):
        result = self._chest(medical_clearance="the doctor has not cleared me")
        assert result.blocked
        assert result.doctor_cleared is False
        assert "chest pain at rest" in " ".join(result.reasons).lower()

    def test_a_conditional_or_garbled_clearance_does_not_count(self):
        today = datetime.now(timezone.utc).date()
        for words in (
            "my doctor cleared me unless I get chest pain",
            "cleared unless chest pain",
            "doctor clear",
            "my doctor cleared me only if the pain stays away",
            "my doctor cleared me as long as I feel fine",
            "the doctor clears me until the pain returns",
        ):
            result = self._chest(medical_clearance=words)
            assert result.blocked, words
            assert result.doctor_cleared is False
            assert passing_readiness(result) is False
        future = self._chest(
            medical_clearance="my doctor cleared me for exercise",
            clearance_date=(today + timedelta(days=1)).isoformat(),
        )
        assert future.blocked
        assert future.doctor_cleared is False
        assert "clearance_date cannot be in the future." in future.reasons
        expired_on = today.replace(year=today.year - 1) - timedelta(days=1)
        expired = self._chest(
            medical_clearance="my doctor cleared me for exercise",
            clearance_date=expired_on.isoformat(),
        )
        assert expired.blocked
        assert expired.doctor_cleared is False
        assert "That clearance is more than 12 months old. Ask again." in expired.reasons

    def test_pregnancy_still_needs_its_own_clearance(self):
        result = self.screen.screen_intake({
            "age": 30,
            "par_q": self.pq,
            "pregnant": True,
            "medical_clearance": "my doctor cleared me for exercise",
        })
        assert result.blocked
        assert "without medical clearance" in " ".join(result.reasons).lower()
        assert "The plan follows the doctor's clearance." not in result.recommendations


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
