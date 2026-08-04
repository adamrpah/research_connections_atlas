import unittest

import pandas as pd

from label_and_propagate_topics import topic_metadata


class AutomaticTopicLabelTests(unittest.TestCase):
    def test_supports_arbitrary_topic_ids_and_counts(self):
        topics = pd.DataFrame([
            {"topic_id": 4, "top_terms": "urban; resilience; cities; policy"},
            {"topic_id": 17, "top_terms": "medicaid; health insurance; coverage; data"},
        ])
        labels = topic_metadata(topics)
        self.assertEqual(set(labels), {4, 17})
        self.assertEqual(labels[4][0], "Urban • Resilience • Cities")
        self.assertIn("MEDICAID", labels[17][0])

    def test_empty_terms_receive_a_fallback_label(self):
        labels = topic_metadata(pd.DataFrame([{"topic_id": 9, "top_terms": ""}]))
        self.assertEqual(labels[9][0], "Topic 9")


if __name__ == "__main__":
    unittest.main()
