"""Awake vocabulary, including explicit negations and unknown-word rejection."""
from commands import ALIASES
from wake import WAKE_GRAMMAR


def phrases(model=None):
    destinations = [name for aliases in ALIASES.values() for name in aliases]
    destinations += [f'{n} 号 {suffix}'.strip() for n in '一二三四五六'
                     for suffix in ('', '位置', '点')]
    actions = ['开始 巡检', '开始 巡逻', '站立', '站 起来', '站起', '起立', '趴 下', '卧倒', '趴 下来',
               '停止', '停下', '停止 导航', '取消 导航', '继续', '继续 走', '继续 导航',
               '打 招呼', '招呼', '打 个 招呼', '打 一下 招呼', '给 大家 打 个 招呼',
               '下楼', '去 楼梯', '下 楼梯', '去 楼梯 前', '到 楼梯 前', '去 下楼 固定 点', '确认',
               '不 确认', '没有 开门', '还 没 开门', '确认 是否 已 开门',
               '回来', '回到 初始 位置', '回 初始 位置',
               '定位 当前 位置', '重新 定位 当前 位置', '重新 定位',
               '请 定位 当前 位置', '请 重新 定位',
               '还 剩 多少 电', '还有 多少 电', '剩余 多少 电', '剩余 电量',
               '查询 电量', '查看 电量', '电池 电量', '现在 电量 多少',
               '当前 电量', '电量 多少', '多少 电']
    actions += [f'{v} {i} 号 门' for v in ('进','出') for i in ('一','二')]
    words = destinations + ['去 ' + d for d in destinations] + actions
    # Never silently strip negation because it is missing from the vocabulary.
    words += [prefix + ' ' + word for prefix in ('不要', '别') for word in words[:]]
    words += WAKE_GRAMMAR + ['[unk]']
    if model is None:
        return words
    def split(word):
        if model.vosk_model_find_word(word) >= 0:
            return [word]
        for length in range(len(word)-1, 0, -1):
            head = word[:length]
            if model.vosk_model_find_word(head) >= 0:
                tail = split(word[length:])
                if tail is not None:
                    return [head] + tail
        return None
    segmented = []
    for phrase in words:
        tokens = [split(word) for word in phrase.split()]
        if all(token is not None for token in tokens):
            segmented.append(' '.join(word for token in tokens for word in token))
    return list(dict.fromkeys(segmented))
