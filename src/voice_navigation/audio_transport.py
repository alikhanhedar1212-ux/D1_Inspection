"""Use the same PCM format and cached responses locally or on AidLux."""
from project_config import remote_file, setting, ssh_command
REMOTE_SOURCE = setting('microphone')
REMOTE_SINK = setting('speaker')


def capture_command(local, source):
    if local:
        return ['parec', '--device=' + source, '--raw', '--format=s16le',
                '--rate=16000', '--channels=1', '--latency-msec=100']
    return ssh_command('aidlux', ['python3', '-u',
                       remote_file('aidlux', 'voice_navigation', 'audio_sender.py'),
                       '--source', source])


def playback_command(local, audio_root, filename):
    if local:
        return ['paplay', str(audio_root / filename)]
    return ssh_command('aidlux', ['python3',
                       remote_file('aidlux', 'voice_navigation', 'play_reply.py'),
                       remote_file('aidlux', 'voice_navigation', 'audio/' + filename)], timeout=5)
