"""Per-frame battle-role checks must not resolve filesystem paths repeatedly."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.manual_battle import is_script

class ScriptIdentityTests(unittest.TestCase):
    def controller(self,folder,script,session='first'):
        return SimpleNamespace(folder=folder,automation=SimpleNamespace(script=script,session=SimpleNamespace(id=session)))
    def test_repeated_frame_checks_do_not_access_filesystem_after_binding(self):
        c=self.controller(ROOT,ROOT/'Bots/auto_battle.py');self.assertTrue(is_script(c))
        with patch.object(Path,'resolve',side_effect=AssertionError('Filesystem access in frame guard')):
            for _ in range(100):self.assertTrue(is_script(c))
    def test_equal_basename_outside_project_is_not_the_builtin(self):
        c=self.controller(ROOT,ROOT.parent/'elsewhere/auto_battle.py');self.assertFalse(is_script(c))
        c.automation.script=ROOT/'Bots/auto_battle.py';self.assertTrue(is_script(c))
    def test_new_session_revalidates_symlink_while_loaded_session_keeps_its_role(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'Bots').mkdir();one=root/'one.py';two=root/'two.py';one.write_text('');two.write_text('');link=root/'Bots/auto_battle.py';link.symlink_to(one)
            c=self.controller(root,one);self.assertTrue(is_script(c));link.unlink();link.symlink_to(two)
            self.assertTrue(is_script(c))
            c.automation.session=SimpleNamespace(id='second');self.assertFalse(is_script(c))

if __name__=='__main__':unittest.main()
