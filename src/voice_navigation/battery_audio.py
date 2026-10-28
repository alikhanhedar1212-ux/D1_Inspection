"""Join the user's unchanged prefix PCM with a separately generated number."""
import audioop
import wave

NUMBER_RATE_RATIO = 1.12


def compose_wavs(prefix, number, output):
    with wave.open(str(prefix), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError('电量开头音频需要单声道16位PCM')
        rate = wav.getframerate()
        first = wav.readframes(wav.getnframes())
    with wave.open(str(number), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError('电量数字音频需要单声道16位PCM')
        # Raise only the synthesized number by about two semitones and make
        # its delivery 12% quicker. The user's prefix samples stay untouched.
        number_rate = round(wav.getframerate()*NUMBER_RATE_RATIO)
        rest = wav.readframes(wav.getnframes())
    if not first or not rest:
        raise ValueError('电量播报音频为空')
    if number_rate != rate:
        rest, _ = audioop.ratecv(rest, 2, 1, number_rate, rate, None)
    with wave.open(str(output), 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', ''))
        wav.writeframes(first + bytes(round(rate*.1)*2) + rest)
