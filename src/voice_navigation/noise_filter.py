"""Measured stationary microphone noise subtraction at 16 kHz."""
from pathlib import Path
import numpy as np
from scipy.signal import stft, istft
from scipy.ndimage import uniform_filter


class MicrophoneDenoiser:
    def __init__(self, profile):
        self.noise = np.load(profile)['power'][:, None]
        if self.noise.shape != (513, 1):
            raise ValueError('Invalid microphone noise profile')
        self.pending = bytearray()
        self.context = np.zeros(1024)

    def reset(self):
        self.pending.clear()
        self.context[:] = 0

    def feed(self, data):
        self.pending.extend(data)
        output = bytearray()
        while len(self.pending) >= 3200:
            chunk = np.frombuffer(bytes(self.pending[:3200]), dtype='<i2').astype(float) / 32768
            del self.pending[:3200]
            signal = np.concatenate((self.context, chunk))
            _, _, spectrum = stft(signal, 16000, nperseg=1024, noverlap=768)
            power = abs(spectrum) ** 2
            gain = np.maximum(.04, np.sqrt(np.maximum(power - 1.5 * self.noise, 0) /
                                          np.maximum(power, 1e-12)))
            gain = uniform_filter(gain, size=(3, 3))
            _, clean = istft(spectrum * gain, 16000, nperseg=1024, noverlap=768)
            clean = clean[1024:2624]
            output.extend(np.clip(clean * 32768, -32768, 32767).astype('<i2').tobytes())
            self.context = signal[-1024:].copy()
        return bytes(output)
