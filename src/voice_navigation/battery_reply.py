"""Run on AidLux: speak one validated battery percentage, using cached local TTS."""
import argparse
import hashlib
from battery_data import chinese_number
from battery_audio import compose_wavs, NUMBER_RATE_RATIO
import aidlux_native_speech as speech

NUMBER_VOICE = 'cmn+f3'
NUMBER_VOICE_VERSION = 'female_f3_v1'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('value', choices=['unavailable']+[str(i) for i in range(101)])
    args = parser.parse_args()
    if args.value == 'unavailable':
        key, text = 'battery_unavailable', '暂时无法读取电量，请稍后再试'
        speech.PHRASES[key] = text
        speech.speak(key)
    else:
        percent = int(args.value)
        prefix = speech.ROOT/'audio/battery_prefix.wav'
        if not prefix.is_file():
            raise RuntimeError('用户电量开头录音尚未同步')
        number_key = f'battery_number_{NUMBER_VOICE_VERSION}_{percent:03d}'
        number = speech.ROOT/'audio'/(number_key+'.wav')
        if not number.is_file():
            speech.PHRASES[number_key] = '百分之'+chinese_number(percent)
            number = speech.synthesize(number_key, voice=NUMBER_VOICE)
        style = f'number-voice:{NUMBER_VOICE};number-rate:{NUMBER_RATE_RATIO:.6f}'.encode()
        digest = hashlib.sha256(prefix.read_bytes()+number.read_bytes()+style).hexdigest()[:16]
        output = speech.ROOT/'audio'/f'battery_custom_{percent:03d}_{digest}.wav'
        if not output.is_file():
            temporary = output.with_suffix('.pending.wav')
            compose_wavs(prefix, number, temporary)
            temporary.replace(output)
        speech.play(output)


if __name__ == '__main__':
    main()
