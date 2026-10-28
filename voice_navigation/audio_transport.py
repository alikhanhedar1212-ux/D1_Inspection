"""Use the same PCM format and cached responses locally or on AidLux."""
REMOTE_SOURCE = 'alsa_input.usb-Newmine_Newmine_20180508-00.analog-stereo'
REMOTE_SINK = 'alsa_output.usb-Generic_USB2.0_Device_20170726905923-01.analog-stereo'


def capture_command(local, source):
    if local:
        return ['parec', '--device=' + source, '--raw', '--format=s16le',
                '--rate=16000', '--channels=1', '--latency-msec=100']
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
            'aidlux', 'python3', '-u', '/home/aidlux/voice_navigation/audio_sender.py',
            '--source', source]


def playback_command(local, audio_root, filename):
    if local:
        return ['paplay', str(audio_root / filename)]
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
            'aidlux', 'python3', '/home/aidlux/voice_navigation/play_reply.py',
            '/home/aidlux/voice_navigation/audio/' + filename]
