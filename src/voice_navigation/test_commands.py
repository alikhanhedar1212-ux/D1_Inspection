import unittest
from commands import parse


class CommandsTest(unittest.TestCase):
    def test_numbers(self):
        for i, word in enumerate('一二三四五六', 1):
            for text in (f'去{i}号位置', f'机器狗，去{word}号点。'):
                self.assertEqual(parse(text), {'action': 'go', 'id': i})

    def test_places(self):
        for text, ident in [('去门口', 1), ('去洗手间门口', 2),
                            ('请到展示厅起点', 4), ('前往放映厅', 3),
                            ('去展示区中心', 5), ('去窗边', 6)]:
            self.assertEqual(parse(text), {'action': 'go', 'id': ident})

    def test_reject_ambiguous_or_negated(self):
        for text in ['不要去门口', '别去1号位置', '去门口然后去厕所',
                     '去1号或2号', '去7号', '听说他去门口了',
                     '如果有人去门口', '不停地去门口']:
            self.assertIsNone(parse(text), text)

    def test_stairs_aliases(self):
        from command_grammar import phrases
        for text in ('下楼', '去楼梯', '下楼梯', '机器狗，去楼梯。'):
            self.assertEqual(parse(text), {'action': 'stairs_approach'})
        self.assertIn('去 楼梯', phrases())
        self.assertIn('下 楼梯', phrases())
        for text in ('不要去楼梯', '别下楼梯', '下楼梯然后回来', '如果去楼梯'):
            self.assertIsNone(parse(text))

    def test_stop(self):
        for text in ['停止', '机器狗停下', '取消导航']:
            self.assertEqual(parse(text), {'action': 'stop'})

    def test_return_home(self):
        for text in ('回来', '回到初始位置', '机器狗，回到初始位置。', '回 到 初始 位置'):
            self.assertEqual(parse(text), {'action': 'return_home'})
        for text in ('不要回来', '别回到初始位置', '回来然后去一号',
                     '回来或去正门', '如果可以回来', '回到初始位置正门'):
            self.assertIsNone(parse(text), text)

    def test_resume(self):
        for text in ('继续', '继续走', '继续导航', '机器狗继续走吧'):
            self.assertEqual(parse(text), {'action': 'resume'})
        self.assertIsNone(parse('不要继续走'))

    def test_postures(self):
        for text in ('站立', '机器狗站起来', '起立'):
            self.assertEqual(parse(text), {'action': 'stand'})
        for text in ('趴下', '卧倒', '狗狗趴下来'):
            self.assertEqual(parse(text), {'action': 'lie_down'})
        for text in ('不要趴下', '别站起来', '站立然后去正门'):
            self.assertIsNone(parse(text))

    def test_greeting_keyword(self):
        for text in ('打招呼', '招呼', '打个招呼', '给大家打个招呼'):
            self.assertEqual(parse(text), {'action': 'greet'})
        for text in ('不要打招呼', '别打招呼', '如果有人打招呼', '打招呼然后去1号'):
            self.assertIsNone(parse(text))

    def test_bare_keywords_and_ambiguous_keywords(self):
        for text in ('1号', '一号', '正门', '门口', '一号位置'):
            self.assertEqual(parse(text), {'action': 'go', 'id': 1})
        for text in ('1号2号', '正门洗手间', '不要正门', '7号'):
            self.assertIsNone(parse(text))


if __name__ == '__main__':
    unittest.main()
