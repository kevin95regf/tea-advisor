import unittest

from tcm_constitution.questions import questions_for_sex
from tcm_constitution.scoring import (
    classify_balanced,
    classify_biased,
    score_questionnaire,
    transformed_score,
)


class ScoringTests(unittest.TestCase):
    def test_transformed_score_endpoints(self):
        self.assertEqual(transformed_score(3, 3), 0)
        self.assertEqual(transformed_score(15, 3), 100)

    def test_biased_thresholds(self):
        self.assertEqual(classify_biased(29.999), "否")
        self.assertEqual(classify_biased(30), "倾向是")
        self.assertEqual(classify_biased(39.999), "倾向是")
        self.assertEqual(classify_biased(40), "是")

    def test_balanced_thresholds(self):
        under_30 = {str(i): 29.99 for i in range(8)}
        under_40 = {str(i): 39.99 for i in range(8)}
        self.assertEqual(classify_balanced(60, under_30), "是")
        self.assertEqual(classify_balanced(60, under_40), "基本是")
        self.assertEqual(classify_balanced(59.99, under_30), "否")

    def test_all_low_except_energy_is_balanced(self):
        answers = {q.id: 1 for q in questions_for_sex("female")}
        answers["q01"] = 5
        result = score_questionnaire(answers, "female")
        self.assertEqual(result["scores"]["balanced"]["transformed_score"], 100)
        self.assertEqual(result["scores"]["balanced"]["status"], "是")
        self.assertTrue(
            all(
                result["scores"][key]["status"] == "否"
                for key in result["scores"]
                if key != "balanced"
            )
        )

    def test_shared_answers_are_used_in_multiple_scales(self):
        answers = {q.id: 1 for q in questions_for_sex("male")}
        answers["q02"] = 5
        result = score_questionnaire(answers, "male")
        self.assertEqual(result["scores"]["qi_deficiency"]["raw_score"], 7)
        self.assertEqual(result["scores"]["balanced"]["raw_score"], 12)

    def test_question_and_scale_item_counts(self):
        self.assertEqual(len(questions_for_sex("female")), 26)
        self.assertEqual(len(questions_for_sex("male")), 26)
        answers = {q.id: 1 for q in questions_for_sex("female")}
        result = score_questionnaire(answers, "female")
        counts = {
            key: detail["item_count"] for key, detail in result["scores"].items()
        }
        self.assertEqual(
            counts,
            {
                "balanced": 4,
                "qi_deficiency": 3,
                "yang_deficiency": 3,
                "yin_deficiency": 3,
                "phlegm_dampness": 3,
                "damp_heat": 3,
                "blood_stasis": 3,
                "qi_stagnation": 3,
                "special_diathesis": 4,
            },
        )

    def test_damp_heat_uses_one_sex_specific_item(self):
        female_answers = {q.id: 1 for q in questions_for_sex("female")}
        male_answers = {q.id: 1 for q in questions_for_sex("male")}
        female_result = score_questionnaire(female_answers, "female")
        male_result = score_questionnaire(male_answers, "male")
        self.assertEqual(female_result["scores"]["damp_heat"]["item_count"], 3)
        self.assertEqual(male_result["scores"]["damp_heat"]["item_count"], 3)

    def test_missing_and_invalid_answers_fail(self):
        with self.assertRaisesRegex(ValueError, "缺少答案"):
            score_questionnaire({}, "female")
        answers = {q.id: 1 for q in questions_for_sex("female")}
        answers["q01"] = 6
        with self.assertRaisesRegex(ValueError, "1–5"):
            score_questionnaire(answers, "female")


if __name__ == "__main__":
    unittest.main()
