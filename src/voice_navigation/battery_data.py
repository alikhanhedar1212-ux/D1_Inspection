"""Validate native battery readings and render bounded Mandarin replies."""
import math


def chinese_number(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError('电量百分比超出范围')
    digits = '零一二三四五六七八九'
    if value == 100:
        return '一百'
    if value < 10:
        return digits[value]
    tens, units = divmod(value, 10)
    return (digits[tens] if tens > 1 else '') + '十' + (digits[units] if units else '')


def battery_reply(percent):
    return '当前电量为百分之' + chinese_number(percent)


def validate_sample(sample, elapsed):
    if sample.get('source') != 'battery_state' or sample.get('received_count', 0) < 2:
        raise ValueError('缺少实时电池数据')
    age = sample.get('sample_age_s')
    if (not isinstance(age, (int, float)) or not math.isfinite(age) or not 0 <= age < 2
            or not math.isfinite(elapsed) or not 0 <= elapsed < 10):
        raise ValueError('电池数据过期')
    raw = sample.get('battery')
    if not isinstance(raw, dict):
        raise ValueError('电池数据格式错误')
    # proto3 JSON omits a zero-valued power field. A real voltage is required
    # before treating an omitted power as 0%; an empty message is unavailable.
    voltage = raw.get('volt')
    if not isinstance(voltage, int) or not 1000 <= voltage <= 100000:
        raise ValueError('电池电压字段无效')
    percent = raw.get('power', 0)
    chinese_number(percent)
    return percent
