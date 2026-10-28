from pathlib import Path
import unittest
from unittest.mock import patch
from play_reply import play,AUDIO,SINK

class ReplyVolumeTests(unittest.TestCase):
    def test_each_reply_sets_40_percent_before_playback(self):
        calls=[]
        for _ in range(2):play(AUDIO/'wake_reply.wav',runner=lambda argv,**kwargs:calls.append(argv))
        self.assertEqual([c[0] for c in calls],['pactl','paplay','pactl','paplay'])
        for c in calls[::2]:self.assertEqual(c,['pactl','set-sink-volume',SINK,'40%'])

    def test_volume_failure_prevents_loud_playback(self):
        calls=[]
        def fail(argv,**kwargs):calls.append(argv);raise RuntimeError('sink unavailable')
        with self.assertRaises(RuntimeError):play(AUDIO/'wake_reply.wav',runner=fail)
        self.assertEqual(len(calls),1)

    def test_arbitrary_path_is_not_played(self):
        calls=[]
        with self.assertRaises(ValueError):play('/tmp/unrelated.wav',runner=lambda *args,**kwargs:calls.append(args))
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
