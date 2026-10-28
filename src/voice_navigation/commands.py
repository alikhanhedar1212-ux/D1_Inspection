"""Strict Chinese destination parsing, independent of ROS and microphone."""
import re

ALIASES = {
    1: ('正门', '门口', '大门', '大门口'),
    2: ('洗手间门口', '洗手间', '卫生间门口', '卫生间', '厕所门口', '厕所'),
    3: ('放映厅', '放映厅门口'),
    4: ('展示厅起点', '展示区起点', '展厅起点'),
    5: ('展示区中心', '展示厅中心', '展厅中心'),
    6: ('窗户', '窗边', '窗户旁边'),
}
DIGITS = dict(zip('一二三四五六', range(1, 7)))
DIGITS.update({str(i): i for i in range(1, 7)})
DIGITS['两'] = 2


def normalize(text):
    return re.sub(r'[\s，。！？,.!?、]', '', text)


def parse(text):
    text = normalize(text)
    text = re.sub(r'^(?:机器狗|小狗|狗狗)', '', text)
    if text in ('停', '停止', '停下', '停下来', '停止导航', '取消导航', '取消任务', '别走了'):
        return {'action': 'stop'}
    if text in ('开始巡检', '开始巡逻'):
        return {'action': 'patrol_start'}
    if text in ('还剩多少电', '还有多少电', '剩余多少电', '剩余电量', '查询电量',
                '查看电量', '电池电量', '现在电量多少', '当前电量', '电量多少', '多少电'):
        return {'action': 'battery_query'}
    if text in ('定位当前位置', '重新定位当前位置', '重新定位', '请定位当前位置', '请重新定位'):
        return {'action': 'relocalize'}
    if text in ('继续', '继续走', '继续走吧', '继续导航', '继续前进'):
        return {'action': 'resume'}
    if text in ('下楼', '去楼梯', '下楼梯', '去下楼', '去楼梯前', '到楼梯前', '去下楼固定点'):
        return {'action': 'stairs_approach'}
    passage = re.fullmatch(r'(进|出)([一二12])号门', text)
    if passage:
        return {'action':'door_passage', 'door':DIGITS[passage.group(2)],
                'direction':'enter' if passage.group(1)=='进' else 'exit'}
    if text == '确认':
        return {'action': 'confirm_door'}
    if text in ('回来', '回到初始位置', '回初始位置'):
        return {'action': 'return_home'}
    if text in ('站立', '站起来', '站起', '起立'):
        return {'action': 'stand'}
    if text in ('趴下', '卧倒', '趴下来'):
        return {'action': 'lie_down'}
    if ('招呼' in text and not re.search(r'不要|别|取消|不|如果|然后|或者|或是', text)
            and not re.search(r'[一二三四五六1-6]号', text)):
        return {'action': 'greet'}
    # Reject negation and multi-step/conditional sentences by accepting only
    # complete, single-destination commands.
    match = re.fullmatch(r'(?:请)?(?:去|到|前往|走到|导航到|带我去)(.+?)(?:吧)?', text)
    destination = match.group(1) if match else text
    number = re.fullmatch(r'([一二三四五六两1-6])号(?:位置|点|地点|点位)?', destination)
    if number:
        return {'action': 'go', 'id': DIGITS[number.group(1)]}
    for ident, aliases in ALIASES.items():
        if destination in aliases:
            return {'action': 'go', 'id': ident}
    return None
