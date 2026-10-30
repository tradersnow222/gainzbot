#!/usr/bin/env python3
"""Tests for readiness_screen.py screening guardrails."""

import pytest
from readiness_screen import ReadinessScreen, ClearanceLevel


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
