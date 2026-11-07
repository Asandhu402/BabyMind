import tempfile
import unittest
from pathlib import Path
from babymind.emotions import EmotionSystem

class EmotionSystemTests(unittest.TestCase):
    def test_emotional_state_changes_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"emotions.sqlite3"
            emotions=EmotionSystem(path)
            before=emotions.state()
            after=emotions.observe("I am excited and happy to learn and explore.")
            self.assertGreater(after["values"]["joy"],before["values"]["joy"])
            self.assertGreater(after["values"]["curiosity"],before["values"]["curiosity"])
            reopened=EmotionSystem(path)
            self.assertEqual(reopened.state()["values"],after["values"])

    def test_emotional_context_is_transparent(self):
        with tempfile.TemporaryDirectory() as directory:
            context=EmotionSystem(Path(directory)/"emotions.sqlite3").context()
            self.assertIn("computational signals",context)
            self.assertIn("not as proof",context)

if __name__ == "__main__":
    unittest.main()
