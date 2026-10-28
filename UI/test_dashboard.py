import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import voice_dashboard


class DashboardTests(unittest.TestCase):
    def test_html_is_loaded_from_ui_independently_of_event_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = voice_dashboard.Handler.__new__(voice_dashboard.Handler)
            handler.path = '/'
            handler.wfile = io.BytesIO()
            responses = []
            handler.send_response = responses.append
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            with patch.object(voice_dashboard, 'ROOT', Path(tmp)):
                handler.do_GET()
            self.assertEqual(responses, [200])
            self.assertIn(b'<!doctype html>', handler.wfile.getvalue())

    def test_partial_event_write_does_not_break_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {'event': 'transcript', 'text': '去门口', 'event_id': 1}
            (root / 'ui_events.jsonl').write_text(json.dumps(event) + '\n{"event":')
            (root / 'ui_session.json').write_text(json.dumps({'local': True}))
            with patch.object(voice_dashboard, 'ROOT', root):
                data = voice_dashboard.snapshot()
            self.assertEqual(data['events'], [event])
            self.assertEqual(data['session'], {'local': True})
            self.assertFalse(data['running'])


if __name__ == '__main__':
    unittest.main()
