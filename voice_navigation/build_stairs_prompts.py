from pathlib import Path
import subprocess
from gtts import gTTS
r=Path(__file__).parent/'audio'
for name,text in [('request_open_door','请帮我开门'),('confirm_door_open','确认是否已开门')]:
 mp3=r/(name+'.mp3');wav=r/(name+'.wav')
 gTTS(text,lang='zh-CN').save(str(mp3))
 subprocess.run(['ffmpeg','-nostdin','-y','-loglevel','error','-i',str(mp3),'-ar','16000','-ac','1',str(wav)],check=True)
 print(wav,flush=True)
