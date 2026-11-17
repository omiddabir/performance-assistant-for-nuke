import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import quote
from nuke_performance_assistant.privacy import redact_diagnostics


def payload(name):
    home='C:/Users/'+name
    return {'native_preferences_file':home+'/.nuke/preferences17.1.nk',
            'cache_environment':{'NUKE_TEMP_DIR':home+'/Temp'},
            'hardware':{'disk':{'path':home+'/private','free_gb':123},'gpus':[{'name':'RTX','uuid':'GPU-secret','vram_gb':16}]},
            'values':{'cache_path':home+'/cache','comp_pct':75},'staged':{'cache_path':'[getenv NUKE_TEMP_DIR]'},
            'reasoning':[name,quote(name,safe=''),{'nested':[home,'USER~1','Render-Station']}],
            'preference_schema':[{'name':'studioPrivateTool'}]}

class PrivacyTests(unittest.TestCase):
    def test_identities_nested_and_encoded_nonmutating_idempotent(self):
        for name in ('Jane Smith','آیدا نوشالی',"O'Brien",'a.b','Amy','USER~1'):
            data=payload(name); before=copy.deepcopy(data)
            with patch('nuke_performance_assistant.privacy.identities',return_value=[('C:/Users/'+name,'<home>'),(name,'<user>'),('USER~1','<user>'),('Render-Station','<computer>')]):
                result=redact_diagnostics(data)
                self.assertEqual(result,redact_diagnostics(result))
            self.assertEqual(data,before)
            for ascii_mode in (True,False):
                encoded=json.dumps(result,ensure_ascii=ascii_mode)
                self.assertNotIn(name,encoded)
                self.assertNotIn(quote(name,safe=''),encoded)
                self.assertNotIn(json.dumps(name,ensure_ascii=ascii_mode)[1:-1],encoded)
            self.assertNotIn('uuid',result['hardware']['gpus'][0])
            self.assertNotIn('preference_schema',result)
            self.assertEqual(result['preference_schema_count'],1)
            self.assertEqual(result['values']['comp_pct'],75)
            self.assertEqual(result['staged']['cache_path'],'[getenv NUKE_TEMP_DIR]')

    def test_schema_explicit(self):
        result=redact_diagnostics(payload('Synthetic'),include_schema=True)
        self.assertEqual(len(result['preference_schema']),1)
        self.assertEqual(result['preference_schema_count'],1)

    def test_generic_names_and_whole_tokens(self):
        for name in ('nuke','cache'):
            with patch('getpass.getuser',return_value=name), patch.dict('os.environ',{'USER':name,'USERNAME':name,'LOGNAME':name}):
                result=redact_diagnostics({'nuke':'nuke cache caching','cache':123})
                self.assertEqual(result['nuke'],'nuke cache caching')
                self.assertEqual(result['cache'],123)
        with patch('nuke_performance_assistant.privacy.identities',return_value=[('Amy','<user>')]):
            self.assertEqual(redact_diagnostics({'text':'Amy amyloid'})['text'],'<user> amyloid')

    def test_path_forms(self):
        for path in ('/Users/Synthetic/private','/home/Synthetic/private',r'C:\Users\Synthetic\private',r'\\server\share\private'):
            result=redact_diagnostics({'hardware':{'disk':{'path':path}}})
            self.assertNotIn('Synthetic',json.dumps(result))
            self.assertNotIn('server',json.dumps(result))

    def test_real_identity_collection_and_all_encodings(self):
        for name in ('Jane Smith','آیدا نوشالی',"O'Brien",'a.b','Amy'):
            home='C:\\Users\\'+name
            with patch('getpass.getuser',return_value=name), patch.dict('os.environ',{'USER':name,'USERNAME':name,'LOGNAME':name,'COMPUTERNAME':'Synthetic Host'}), patch('os.path.expanduser',return_value=home), patch('socket.gethostname',return_value='Synthetic Host'), patch('platform.node',return_value='Synthetic Host'), patch('nuke_performance_assistant.privacy.short_home',return_value=r'C:\Users\USER~1'):
                data=payload(name)
                data['warnings']=[home,quote(home,safe=''),home.replace('\\','/'),r'C:\Users\USER~1',quote(name,safe='').lower(),'Synthetic Host']
                result=redact_diagnostics(data)
                self.assertEqual(result,redact_diagnostics(result))
                for ensure in (True,False):
                    text=json.dumps(result,ensure_ascii=ensure).lower()
                    for identity in (name,'USER~1','Synthetic Host'):
                        self.assertNotIn(json.dumps(identity,ensure_ascii=ensure)[1:-1].lower(),text)
                        self.assertNotIn(quote(identity,safe='').lower(),text)

    def test_free_paths_and_whitelist(self):
        data={'warnings':['/opt/studio/private',r'C:\secret\private','/var/team/private','/<folder>; /opt/another/private'],
              'install':'/Applications/Nuke17.1/Nuke.app'}
        result=redact_diagnostics(data)
        self.assertNotIn('private',json.dumps(result))
        self.assertEqual(result['install'],data['install'])
        self.assertEqual(result,redact_diagnostics(result))
