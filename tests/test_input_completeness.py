import unittest


try:
    from english_knowledge_tagger.input_completeness import classify_input_completeness
except ImportError:
    classify_input_completeness = None


def packet(question_text: str, *, child: bool = False, audio: bool = False) -> dict[str, object]:
    return {
        "question_text": question_text,
        "is_sub_question": child,
        "contain_audio": audio,
        "whole_image": False,
    }


class InputCompletenessTests(unittest.TestCase):
    def test_direct_stem_with_supporting_fields_is_complete(self):
        self.assertTrue(callable(classify_input_completeness))
        result = classify_input_completeness(
            packet(
                "题目题干：Choose the correct answer.\n"
                "题目选项：A. go B. goes\n"
                "题目答案：B\n"
                "题目解析：主语为第三人称单数。"
            )
        )
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["has_stem"])
        self.assertEqual(result["modality"], "text")

    def test_explicit_analysis_without_child_stem_is_analysis_supported(self):
        result = classify_input_completeness(
            packet(
                "题目大题题干：阅读短文并完成各小题。\n"
                "当前小题选项：A. what B. where\n"
                "当前小题解析：空处引导宾语从句，表示在哪里，故选 where。\n"
                "当前小题答案：B\n",
                child=True,
            )
        )
        self.assertEqual(result["status"], "analysis_supported")
        self.assertTrue(result["has_parent_material"])
        self.assertTrue(result["has_analysis"])

    def test_generic_analysis_without_stem_is_insufficient(self):
        result = classify_input_completeness(
            packet(
                "题目选项：A. Once a day B. Twice a week\n"
                "题目解析：略\n"
                "题目答案：B\n",
                audio=True,
            )
        )
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("解析", result["reason"])

    def test_sibling_analysis_reference_is_ambiguous(self):
        result = classify_input_completeness(
            packet(
                "题目大题题干：完成下列五个情景。\n"
                "当前小题答案：They are flying kites.\n"
                "当前小题解析：同(1)题详解",
                child=True,
                audio=True,
            )
        )
        self.assertEqual(result["status"], "sibling_mapping_ambiguous")

    def test_audio_duration_without_content_is_audio_or_image_missing(self):
        result = classify_input_completeness(
            packet(
                "本题题干中包含音频内容，音频片段时长24秒，\n"
                "题目选项：A. Sure. B. Once a day. C. Not much.\n"
                "题目答案：B",
                audio=True,
            )
        )
        self.assertEqual(result["status"], "audio_or_image_missing")
        self.assertTrue(result["audio"])


if __name__ == "__main__":
    unittest.main()
