"""Run on AidLux: its installed eSpeak-NG library, existing USB speaker."""
from project_config import setting
import argparse
import ctypes as C
import json
from pathlib import Path
import subprocess
import sys
import time
import wave
from play_reply import play

PHRASES = {'device_normal': '设备正常', 'device_missing': '设备丢失', 'camera_error': '摄像头异常', 'planning_error': '路径规划异常', 'sign_error': '路标识别异常', 'map_3d_ready': '已切换到三维地图，起始位置和朝向已确认。', 'request_open_door': '请帮我开门', 'confirm_door_open': '是否同意我通过这扇门？请确认门已打开且通道安全，同意请说确认。', 'permit_door_1_enter': '我准备从1号门进入，是否同意通行？请确认门已打开且通道安全，同意请说确认。', 'permit_door_1_exit': '我准备从1号门出去，是否同意通行？请确认门已打开且通道安全，同意请说确认。', 'permit_door_2_enter': '我准备从2号门进入，是否同意通行？请确认门已打开且通道安全，同意请说确认。', 'permit_door_2_exit': '我准备从2号门出去，是否同意通行？请确认门已打开且通道安全，同意请说确认。'}
SINK = setting('speaker')
PHRASES.update(localization_success='已定位', localization_failure='请重新定位')
ROOT = Path(__file__).parent


def synthesize(key, voice='cmn'):
    lib = C.CDLL('libespeak-ng.so.1')
    lib.espeak_Initialize.argtypes = [C.c_int, C.c_int, C.c_char_p, C.c_int]
    lib.espeak_Initialize.restype = C.c_int
    lib.espeak_SetVoiceByName.argtypes = [C.c_char_p]
    lib.espeak_SetVoiceByName.restype = C.c_int
    lib.espeak_Synth.argtypes = [C.c_void_p, C.c_size_t, C.c_uint, C.c_int, C.c_uint, C.c_uint, C.POINTER(C.c_uint), C.c_void_p]
    lib.espeak_Synth.restype = C.c_int
    rate = lib.espeak_Initialize(2, 0, None, 0x8000)  # synchronous retrieval
    if rate <= 0:
        raise RuntimeError('AidLux本地语音引擎初始化失败')
    chunks = []
    callback_type = C.CFUNCTYPE(C.c_int, C.POINTER(C.c_short), C.c_int, C.c_void_p)
    @callback_type
    def callback(samples, count, events):
        if samples and count:
            chunks.append(C.string_at(samples, count * 2))
        return 0
    lib.espeak_SetSynthCallback.argtypes = [callback_type]
    lib.espeak_SetSynthCallback(callback)
    try:
        if lib.espeak_SetVoiceByName(voice.encode('ascii')) != 0:
            raise RuntimeError('本地引擎缺少普通话音色')
        text = PHRASES[key].encode('utf-8') + b'\0'
        buf = C.create_string_buffer(text)
        if lib.espeak_Synth(buf, len(text), 0, 1, 0, 1, None, None) != 0:
            raise RuntimeError('语音合成失败')
        pcm = b''.join(chunks)
        if not pcm:
            raise RuntimeError('合成音频为空')
        output = ROOT / 'audio' / (key + '.wav')
        with wave.open(str(output), 'wb') as wav:
            wav.setparams((1, 2, rate, 0, 'NONE', ''))
            wav.writeframes(pcm)
        print(json.dumps({'event': 'native_tts_generated', 'key': key, 'sample_rate': rate, 'seconds': len(pcm)/(2*rate)}, ensure_ascii=False), flush=True)
        return output
    finally:
        lib.espeak_Terminate()


def speak(key):
    path = ROOT / "audio" / (key + ".wav")
    if not path.exists():
        path = synthesize(key)
    print(json.dumps({'event': 'native_tts_playing', 'text': PHRASES[key]}, ensure_ascii=False), flush=True)
    play(path)
    print(json.dumps({'event': 'native_tts_finished', 'key': key}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phrase', choices=tuple(PHRASES)+('test_sequence',))
    args = parser.parse_args()
    if args.phrase == 'test_sequence':
        subprocess.run([sys.executable, __file__, 'request_open_door'], check=True, timeout=25)
        time.sleep(5)
        subprocess.run([sys.executable, __file__, 'confirm_door_open'], check=True, timeout=25)
    else:
        speak(args.phrase)
