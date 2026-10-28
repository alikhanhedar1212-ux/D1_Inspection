from pathlib import Path
import tempfile
import unittest
import wave

from battery_audio import compose_wavs


def save(path, rate, data, channels=1):
    with wave.open(str(path), 'wb') as w:
        w.setparams((channels, 2, rate, 0, 'NONE', ''))
        w.writeframes(data)


class BatteryAudioTests(unittest.TestCase):
    def test_preserves_user_prefix_exactly_while_resampling_number(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = b'\x12\x04'*4800
            save(root/'prefix.wav',48000,prefix)
            save(root/'number.wav',22050,b'\x31\x02'*2205)
            compose_wavs(root/'prefix.wav',root/'number.wav',root/'reply.wav')
            with wave.open(str(root/'reply.wav')) as w:
                self.assertEqual(w.getframerate(),48000)
                self.assertEqual(w.readframes(4800),prefix)
                self.assertEqual(w.readframes(4800),bytes(9600))
                number = w.readframes(10000)
                self.assertGreater(len(number),8000)
                self.assertLess(len(number),9000)

    def test_rejects_empty_or_incompatible_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            save(root/'prefix.wav',48000,b'')
            save(root/'number.wav',48000,b'\x00\x01'*100)
            with self.assertRaises(ValueError):
                compose_wavs(root/'prefix.wav',root/'number.wav',root/'out.wav')


if __name__ == '__main__':unittest.main()
