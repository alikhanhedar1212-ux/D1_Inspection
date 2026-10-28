import tempfile
from pathlib import Path
import unittest
import numpy as np
from scipy.signal import stft
from noise_filter import MicrophoneDenoiser


class DenoisingTests(unittest.TestCase):
    def test_stream_boundaries_and_stationary_noise_reduction(self):
        noise = .15 * np.sin(2 * np.pi * 125 * np.arange(32000) / 16000)
        _, _, z = stft(noise, 16000, nperseg=1024, noverlap=768)
        data = (noise * 32768).astype('<i2').tobytes()
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'noise.npz'
            np.savez(profile, power=np.median(abs(z[:, 3:-3]) ** 2, axis=1))
            first = MicrophoneDenoiser(profile)
            expected = first.feed(data)
            second = MicrophoneDenoiser(profile)
            actual = b''.join(second.feed(data[i:i+731]) for i in range(0, len(data), 731))
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), len(data))
            clean = np.frombuffer(actual, '<i2').astype(float)[16000:]
            original = np.frombuffer(data, '<i2').astype(float)[16000:]
            self.assertLess(np.sqrt(np.mean(clean**2)), .25 * np.sqrt(np.mean(original**2)))


if __name__ == '__main__':
    unittest.main()
