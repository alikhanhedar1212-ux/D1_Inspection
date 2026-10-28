"""AidLux reply playback: reapply the user's 40% volume for every utterance."""
from pathlib import Path
import subprocess
import sys

SINK='alsa_output.usb-Generic_USB2.0_Device_20170726905923-01.analog-stereo'
AUDIO=Path(__file__).resolve().parent/'audio'

def play(path,runner=subprocess.run):
    path=Path(path).resolve()
    if path.parent!=AUDIO.resolve() or path.suffix!='.wav' or not path.is_file():
        raise ValueError('Reply audio must be an existing cached WAV')
    runner(['pactl','set-sink-volume',SINK,'40%'],check=True,timeout=3)
    runner(['paplay','--device='+SINK,str(path)],check=True,timeout=15)

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: play_reply.py cached.wav')
    play(sys.argv[1])
