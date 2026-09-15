import json
import base64
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
import engine
import server

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close()
    def request(self,path,body=None,auth=True,origin=None):
        headers={'X-PDFedit-Token':server.TOKEN} if auth else {}
        if origin:headers['Origin']=origin
        req=urllib.request.Request(self.base+'/api/'+path,headers=headers,
            data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req) as r:
            return json.load(r) if 'json' in r.headers.get('Content-Type','') else r.read()
    def setUp(self):
        self.s=self.request('demo',{})
    def test_layout_preview_apply_undo_and_mock_ai(self):
        from test_layout import fixture,operation
        data=fixture()
        with server.LOCK:server.load(data,'fictional-layout.pdf')
        state=self.request('state');rev=state['revision']
        self.assertTrue(state['capabilities']['layout'])
        op=operation(data,align='center',valign='middle',box='page')
        preview=self.request('manual',dict(revision=rev,operations=[op]))
        self.assertEqual(self.request('export'),data)
        state=self.request('apply',dict(revision=rev,candidateId=preview['candidateId']))
        self.assertNotEqual(self.request('export'),data)
        state=self.request('undo',dict(revision=state['revision']))
        self.assertEqual(self.request('export'),data)
        self.request('key',dict(key='test-fixture'))
        with patch('server.ask_deepseek',return_value=dict(summary='标题在页面居中',operations=[op])):
            preview=self.request('plan',dict(revision=state['revision'],instruction='把标题在页面水平vertically centered',pages=[1]))
        self.assertEqual(preview['pages'],1)
        self.request('key',dict(key=''))

    def test_color_preview_apply_export_undo_and_ai(self):
        from test_colors import fixture,text_op
        data=fixture()
        with server.LOCK:server.load(data,'fictional-color.pdf')
        state=self.request('state');rev=state['revision']
        self.assertTrue(state['capabilities']['colors'])
        ops=[text_op(data,text='title'),dict(type='background_color',page=1,rect=[30,60,470,140],color='#FFCC99')]
        plan=self.request('manual',dict(revision=rev,operations=ops))
        self.assertEqual(self.request('export'),data)
        state=self.request('apply',dict(revision=rev,candidateId=plan['candidateId']))
        self.assertEqual(state['pages'][0]['backgrounds'][0]['color'],'#FFCC99')
        exported=self.request('export')
        self.assertIn('Sample title',str(engine.describe(exported)))
        state=self.request('undo',dict(revision=state['revision']))
        self.assertEqual(self.request('export'),data)
        self.request('key',dict(key='test-fixture'))
        with patch('server.ask_deepseek',return_value=dict(summary='改变样例颜色',operations=ops)):
            plan=self.request('plan',dict(revision=state['revision'],instruction='标题用蓝色，背景用浅橙色',pages=[1]))
        self.assertEqual(len(plan['summaries']),2)
        self.request('key',dict(key=''))

    def test_auth_and_origin(self):
        for kwargs in [dict(auth=False),dict(origin='https://evil.example')]:
            with self.assertRaises(urllib.error.HTTPError) as e:self.request('state',**kwargs)
            self.assertEqual(e.exception.code,403)
    def test_apply_undo_redo_export(self):
        rev=self.s['revision']
        plan=self.request('manual',dict(revision=rev,operations=[dict(type='rotate',page=1,degrees=90)]))
        self.assertEqual(self.request('state')['pages'][0]['rotation'],0)
        s=self.request('apply',dict(revision=rev,candidateId=plan['candidateId']))
        self.assertEqual(s['pages'][0]['rotation'],90)
        s=self.request('undo',dict(revision=s['revision']))
        self.assertEqual(s['pages'][0]['rotation'],0)
        s=self.request('redo',dict(revision=s['revision']))
        self.assertEqual(s['pages'][0]['rotation'],90)
        self.assertTrue(self.request('export').startswith(b'%PDF'))
    def test_stale_revision(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('undo',dict(revision=-1))
    def test_mock_ai_and_selected_context(self):
        # Contract integration test only; no real API call or bill.
        self.request('key',dict(key='test-fixture'))
        def fake(key,instruction,context,allowed,model):
            self.assertEqual([p['page'] for p in context],[1])
            self.assertEqual(allowed,[1])
            return dict(summary='旋转第一页',operations=[dict(type='rotate',page=1,degrees=90)])
        with patch('server.ask_deepseek',side_effect=fake):
            p=self.request('plan',dict(revision=self.s['revision'],instruction='旋转第一页',pages=[1]))
        self.assertEqual(p['pages'],2)
        self.assertTrue(p['summaries'])
        self.request('key',dict(key=''))
    def test_ai_out_of_scope_is_rejected(self):
        self.request('key',dict(key='test-fixture'))
        with patch('server.ask_deepseek',return_value=dict(summary='越界',operations=[dict(type='rotate',page=2,degrees=90)])):
            with self.assertRaises(urllib.error.HTTPError):self.request('plan',dict(revision=self.s['revision'],instruction='旋转',pages=[1]))
        self.assertIsNone(server.STATE['candidate'])
    def test_key_not_exposed(self):
        self.request('key',dict(key='test-fixture-secret'))
        self.assertNotIn('test-fixture-secret',json.dumps(self.request('state')))
        self.request('key',dict(key=''))

    def test_approximate_preview_apply_undo_and_reopen_notice(self):
        from test_approximate import fixture,operation
        data=fixture()
        with server.LOCK:
            server.load(data,'fictional.pdf')
        s=self.request('state');op=operation(data)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('manual',dict(revision=s['revision'],operations=[op],approximateDigits=False))
        self.assertIsNone(server.STATE['candidate'])
        p=self.request('manual',dict(revision=s['revision'],operations=[op],approximateDigits=True))
        self.assertTrue(any(x.startswith('Approximated') for x in p['summaries']))
        self.assertEqual(self.request('export'),data)
        s=self.request('apply',dict(revision=s['revision'],candidateId=p['candidateId']))
        self.assertTrue(s['approximateFonts'])
        exported=self.request('export')
        self.assertIn('5.67',str(engine.describe(exported)))
        s=self.request('undo',dict(revision=s['revision']))
        self.assertFalse(s['approximateFonts'])
        self.assertEqual(self.request('export'),data)
        s=self.request('redo',dict(revision=s['revision']))
        self.assertTrue(s['approximateFonts'])

    def test_font_sample_leaves_document_and_candidate_unchanged(self):
        from test_approximate import fixture,operation
        data=fixture()
        with server.LOCK:
            server.load(data,'fictional.pdf')
        s=self.request('state')
        preview=self.request('manual',dict(revision=s['revision'],operations=[dict(type='rotate',page=1,degrees=90)]))
        sample=self.request('font-sample',dict(revision=s['revision'],page=1,line=operation(data)['line']))
        self.assertTrue(base64.b64decode(sample['pdf']).startswith(b'%PDF'))
        self.assertTrue(base64.b64decode(sample['image']).startswith(b'\x89PNG'))
        self.assertEqual(self.request('export'),data)
        self.assertEqual(self.request('state')['revision'],s['revision'])
        self.assertEqual(server.STATE['candidate_id'],preview['candidateId'])

    def test_mock_ai_defaults_to_approximate_mode(self):
        from test_approximate import fixture,operation
        data=fixture()
        with server.LOCK:
            server.load(data,'fictional.pdf')
        s=self.request('state');self.request('key',dict(key='test-fixture'))
        plan=dict(summary='修改虚构数字',operations=[operation(data)])
        with patch('server.ask_deepseek',return_value=plan):
            p=self.request('plan',dict(revision=s['revision'],instruction='修改虚构数字',pages=[1]))
        self.assertTrue(any(x.startswith('Approximated') for x in p['summaries']))
        self.request('key',dict(key=''))

if __name__=='__main__':unittest.main()
