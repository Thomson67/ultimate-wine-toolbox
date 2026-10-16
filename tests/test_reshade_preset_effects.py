from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import reshade_preset_effects as e

class PresetEffectsTests(unittest.TestCase):
    def analyze(self, content, packs=None):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'preset.ini';source.write_text(content)
            if packs is None:return e.analyze(source)
            index=Path(folder)/'index.json';index.write_text(json.dumps({'packs':packs}))
            return e.analyze(source,index)

    def test_real_index_resolves_effect_sections_and_technique_refs_to_backend_packs(self):
        result=self.analyze('Techniques=AA@MartysMods_SMAA.fx,Color@PD80_01B_RT_Correct_Color.fx\n[CAS.fx]\nSharpness=1\n')
        self.assertEqual(set(result['packs']),{'reshade-shaders','immerse-shaders','prod80-shaders','sweetfx-shaders'})
        self.assertFalse(result['unknown']);self.assertFalse(result['ambiguous'])

    def test_inactive_sorting_does_not_pull_in_every_pack(self):
        result=self.analyze('Techniques=CAS@CAS.fx\nTechniqueSorting=CAS@CAS.fx,Other@PrivateShader.fx\n')
        self.assertEqual(result['packs'],['reshade-shaders','sweetfx-shaders'])
        self.assertFalse(result['unknown'])

    def test_unknown_and_ambiguous_files_are_reported_without_guessing_pack(self):
        result=self.analyze('Techniques=X@Shared.fx,Y@Custom.fx\n',{'one':['Shared.fx'],'two':['Shared.fx']})
        self.assertEqual(result['unknown'],['Custom.fx'])
        self.assertEqual(result['ambiguous'],{'Shared.fx':['one','two']})
        self.assertEqual(result['packs'],['reshade-shaders'])

    def test_already_required_pack_covers_duplicate_and_legacy_names_are_supported(self):
        result=self.analyze('Techniques=Unique,Shared\n',{'one':['Unique.fx','Shared.fx'],'two':['Shared.fx']})
        self.assertEqual(result['packs'],['one','reshade-shaders']);self.assertFalse(result['ambiguous'])
        result=self.analyze('Techniques=UnknownAlias\n')
        self.assertTrue(result['unknown'])

    def test_pinned_retro_extras_are_resolved(self):
        result=self.analyze('Techniques=xBR5x_NoBlend@5XBR_NoBlend.fx\n')
        self.assertIn('uwt-retro-extras',result['packs'])

if __name__=='__main__':unittest.main()
