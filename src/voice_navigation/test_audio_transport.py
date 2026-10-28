from pathlib import Path
import unittest
from audio_transport import capture_command, playback_command, REMOTE_SOURCE


class TransportTests(unittest.TestCase):
    def test_local_never_calls_ssh(self):
        self.assertEqual(capture_command(True, 'mic')[0], 'parec')
        self.assertEqual(playback_command(True, Path('/audio'), 'im_here.wav'),
                         ['paplay', '/audio/im_here.wav'])

    def test_remote_uses_existing_device_and_script(self):
        cmd = capture_command(False, REMOTE_SOURCE)
        self.assertEqual(cmd[0], 'ssh')
        self.assertIn('D1_Inspection/src/voice_navigation/audio_sender.py', cmd[-1])
        self.assertIn(REMOTE_SOURCE, cmd[-1])

    def test_computer_mic_and_robot_reply_are_independent(self):
        self.assertEqual(capture_command(True, 'mic')[0], 'parec')
        reply = playback_command(False, Path('/audio'), 'im_here.wav')
        self.assertEqual(reply[0], 'ssh')
        self.assertIn('aidlux', reply)
        self.assertIn('D1_Inspection/src/voice_navigation/play_reply.py', reply[-1])
        self.assertIn('D1_Inspection/src/voice_navigation/audio/im_here.wav', reply[-1])


if __name__ == '__main__':
    unittest.main()
