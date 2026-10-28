"""AidLux PulseAudio PCM stream. stdout contains only 16 kHz mono s16le."""
import argparse
import os
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--source', default='alsa_input.usb-Newmine_Newmine_20180508-00.analog-stereo')
args = parser.parse_args()
sources = subprocess.check_output(['pactl', 'list', 'short', 'sources'], text=True)
names = [line.split('\t')[1] for line in sources.splitlines() if '\t' in line]
if args.source not in names or args.source.endswith('.monitor'):
    raise SystemExit('Requested microphone unavailable: ' + args.source)
capture = subprocess.Popen(['parec', '--device=' + args.source, '--raw',
                            '--format=s16le', '--rate=48000', '--channels=2',
                            '--latency-msec=100'], stdout=subprocess.PIPE)
try:
    converter = subprocess.Popen(['ffmpeg', '-v', 'error', '-f', 's16le',
                                  '-ar', '48000', '-ac', '2', '-i', 'pipe:0',
                                  '-af', 'highpass=f=100,lowpass=f=7500',
                                  '-ar', '16000', '-ac', '1', '-f', 's16le',
                                  'pipe:1'], stdin=capture.stdout)
    capture.stdout.close()
    converter.wait()
finally:
    capture.terminate()
    capture.wait()

