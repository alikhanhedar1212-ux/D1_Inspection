import unittest
from recognition import confidence_score
from wake import WakeSession


class RecognitionTests(unittest.TestCase):
    def test_one_weaker_word_in_clear_command(self):
        score = confidence_score([{'conf': .95}, {'conf': .90}, {'conf': .616292}])
        session = WakeSession()
        _, token = session.feed('小爱同学', .9)
        session.reply_finished(token)
        event, command = session.feed('去一号位置', score)
        self.assertEqual((event, command), ('command', {'action': 'go', 'id': 1}))

    def test_uncertain_word_and_missing_scores_rejected(self):
        for words in ([], [{'conf': .99}, {'conf': .3}], [{}]):
            self.assertLess(confidence_score(words), .65)

    def test_negation_not_accepted_with_high_confidence(self):
        session = WakeSession()
        _, token = session.feed('小爱同学', .9)
        session.reply_finished(token)
        self.assertNotEqual(session.feed('不要去一号位置', .99)[0], 'command')
