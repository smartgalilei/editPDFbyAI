import unittest
import pymupdf as fitz
import engine

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.data=engine.demo(language="zh")
    def text(self,data):
        with engine.open_pdf(data) as d:
            return ''.join(p.get_text() for p in d)
    def target(self,needle):
        return next(l['id'] for l in engine.describe(self.data)[0]['lines'] if needle in l['text'])
    def test_chinese_replace_roundtrip(self):
        new,_=engine.execute(self.data,[dict(type='replace_text',page=1,line=self.target('交付日期'),text='交付日期：2026年11月01日')])
        self.assertNotIn('2026年10月01日',self.text(new))
        self.assertIn('2026年11月01日',self.text(new))
        self.assertIn('2026年10月01日',self.text(self.data))
        self.assertIn('项目预算',self.text(new))
        self.assertTrue(engine.render(new,1).startswith(b'\x89PNG'))
    def test_replacement_stays_in_original_width(self):
        original = next(l for l in engine.describe(self.data)[0]['lines'] if '交付日期' in l['text'])
        new,_ = engine.execute(self.data,[dict(type='replace_text',page=1,line=original['id'],text='交付日期：2026年11月01日')])
        replaced = next(l for l in engine.describe(new)[0]['lines'] if '交付日期' in l['text'])
        self.assertLessEqual(replaced['bbox'][2],original['bbox'][2]+1)

    def test_multiple_stable_lines(self):
        new,_=engine.execute(self.data,[dict(type='redact_text',page=1,line=self.target('项目名称')),dict(type='replace_text',page=1,line=self.target('交付日期'),text='交付日期：2026年11月01日')])
        self.assertNotIn('智能文档工作台',self.text(new))
        self.assertIn('交付日期：2026年11月01日',self.text(new))
    def test_highlight(self):
        new,_=engine.execute(self.data,[dict(type='highlight',page=1,line=self.target('项目名称'))])
        with engine.open_pdf(new) as d:
            self.assertEqual(len(list(d[0].annots())),1)
    def test_add_text(self):
        new,_=engine.execute(self.data,[dict(type='add_text',page=1,text='已审核',rect=[54,460,350,510],size=14)])
        self.assertIn('已审核',self.text(new))
    def test_rotate(self):
        new,_=engine.execute(self.data,[dict(type='rotate',page=1,degrees=90)])
        self.assertEqual(engine.describe(new)[0]['rotation'],90)
    def test_delete(self):
        new,_=engine.execute(self.data,[dict(type='delete_pages',pages=[1])])
        self.assertEqual(len(engine.describe(new)),1)
        self.assertIn('下一步',self.text(new))
    def test_reorder(self):
        new,_=engine.execute(self.data,[dict(type='reorder_pages',pages=[2,1])])
        self.assertIn('下一步',engine.describe(new)[0]['lines'][0]['text'])
    def test_atomic_failures(self):
        invalid=[[],[dict(type='shell',command='x')],[dict(type='delete_pages',pages=[1,2])],
                 [dict(type='rotate',page=True,degrees=90)],[dict(type='rotate',page=9,degrees=90)],
                 [dict(type='rotate',page=1,degrees=91)],[dict(type='reorder_pages',pages=[1,1])],
                 [dict(type='replace_text',page=1,line='l999',text='x')],
                 [dict(type='replace_text',page=1,line='l1',text='很长'*300)],
                 [dict(type='add_text',page=1,text='过长'*100,rect=[54,450,65,458],size=14)],
                 [dict(type='add_text',page=1,text='x',rect=[0,0,9999,9999],size=14)]]
        for ops in invalid:
            with self.subTest(ops=ops):
                with self.assertRaises(ValueError):engine.execute(self.data,ops)
        self.assertIn('2026年10月01日',self.text(self.data))
    def test_scanned_page(self):
        d=fitz.open();d.new_page();data=d.tobytes();d.close()
        self.assertEqual(engine.describe(data)[0]['lines'],[])
    def test_password_protection(self):
        with engine.open_pdf(self.data) as d:
            encrypted=d.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='test')
        with self.assertRaises(ValueError):engine.describe(encrypted)

if __name__=='__main__':unittest.main()
