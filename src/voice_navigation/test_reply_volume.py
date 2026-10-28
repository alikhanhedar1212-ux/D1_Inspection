from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
from play_reply import play,AUDIO,SINK

class ReplyVolumeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.audio = Path(directory.name)
        (self.audio/'wake_reply.wav').write_bytes(b'test audio placeholder')
        patcher = patch('play_reply.AUDIO', self.audio)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_reply_sets_40_percent_before_playback(self):
        calls=[]
        for _ in range(2):play(self.audio/'wake_reply.wav',runner=lambda argv,**kwargs:calls.append(argv))
        self.assertEqual([c[0] for c in calls],['pactl','paplay','pactl','paplay'])
        for c in calls[::2]:self.assertEqual(c,['pactl','set-sink-volume',SINK,'40%'])

    def test_volume_failure_prevents_loud_playback(self):
        calls=[]
        def fail(argv,**kwargs):calls.append(argv);raise RuntimeError('sink unavailable')
        with self.assertRaises(RuntimeError):play(self.audio/'wake_reply.wav',runner=fail)
        self.assertEqual(len(calls),1)

    def test_arbitrary_path_is_not_played(self):
        calls=[]
        with self.assertRaises(ValueError):play('/tmp/unrelated.wav',runner=lambda *args,**kwargs:calls.append(args))
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
