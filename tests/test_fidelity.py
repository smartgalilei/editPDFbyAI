"""Pixel comparisons against independently rendered expected documents."""
import unittest
import io
from pathlib import Path
import pymupdf as fitz
import engine
from fidelity import FidelityError


def fixture(value='0.00',font='hebo',image=False,mode=0,opacity=1,rotate=0):
    d=fitz.open();p=d.new_page(width=420,height=240)
    p.draw_rect((20,70,400,130),color=None,fill=(.94,.92,1))
    p.draw_line((20,75),(400,125),color=(.82,.84,.92),width=.5)
    if image:
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,380,60),False)
        pix.clear_with(212)
        p.insert_image((20,70,400,130),pixmap=pix)
    p.insert_text((30,42),'Typography check',fontsize=13)
    p.insert_text((35,108),'Version '+value,fontname=font,fontsize=22,
                  color=(.13,.16,.22),fill_opacity=opacity,stroke_opacity=opacity,render_mode=mode,border_width=.35)
    p.insert_text((30,178),'Keep this paragraph unchanged.',fontsize=11)
    p.set_rotation(rotate)
    data=d.tobytes();d.close();return data


def edit(data,new):
    line=next(l for l in engine.describe(data)[0]['lines'] if 'Version ' in l['text'])
    return engine.execute(data,[dict(type='replace_text',page=1,line=line['id'],text='Version '+new)])[0]


def pixels(data):
    with fitz.open(stream=data,filetype='pdf') as d:
        return d[0].get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).samples

class FidelityTests(unittest.TestCase):
    def test_bold_colored_background_exact_pixels(self):
        actual=edit(fixture(),'1.00')
        self.assertEqual(pixels(actual),pixels(fixture('1.00')))
    def test_italic_exact_pixels(self):
        self.assertEqual(pixels(edit(fixture(font='heit'),'1.00')),pixels(fixture('1.00',font='heit')))
    def test_image_background_exact_pixels(self):
        self.assertEqual(pixels(edit(fixture(image=True),'1.00')),pixels(fixture('1.00',image=True)))
    def test_synthetic_bold_and_opacity_exact_pixels(self):
        self.assertEqual(pixels(edit(fixture(mode=2,opacity=.65),'1.00')),pixels(fixture('1.00',mode=2,opacity=.65)))
    def test_rotated_page_exact_pixels(self):
        self.assertEqual(pixels(edit(fixture(rotate=90),'1.00')),pixels(fixture('1.00',rotate=90)))
    def test_different_font_exact_pixels(self):
        self.assertEqual(pixels(edit(fixture(font='cobo'),'1.00')),pixels(fixture('1.00',font='cobo')))
    def test_no_replacement_font_added(self):
        before=fixture();after=edit(before,'1.00')
        with fitz.open(stream=before,filetype='pdf') as a,fitz.open(stream=after,filetype='pdf') as b:
            self.assertEqual([f[1:] for f in a[0].get_fonts()],[f[1:] for f in b[0].get_fonts()])
    def test_missing_character_rejected(self):
        with self.assertRaisesRegex(FidelityError,'glyph'):
            edit(fixture(),'中文')
    def test_longer_text_rejected_without_shrinking(self):
        with self.assertRaises(FidelityError):edit(fixture(),'123456789.00')
    def test_text_deletion_preserves_background(self):
        data=fixture();line=next(l for l in engine.describe(data)[0]['lines'] if 'Version ' in l['text'])
        edited,_=engine.execute(data,[dict(type='redact_text',page=1,line=line['id'])])
        with fitz.open(stream=edited,filetype='pdf') as d:
            pix=d[0].get_pixmap();offset=(90*pix.width+35)*3
            self.assertNotEqual(pix.samples[offset:offset+3],b'\xff\xff\xff')
            self.assertNotIn('Version',d[0].get_text())
    def test_repeated_text_uses_target_position(self):
        def make(first='0.00',last='0.00'):
            data=fixture(first)
            with fitz.open(stream=data,filetype='pdf') as d:
                d[0].insert_text((35,218),'Version '+last,fontname='hebo',fontsize=22)
                return d.tobytes()
        data=make()
        line=[l for l in engine.describe(data)[0]['lines'] if l['text']=='Version 0.00'][-1]
        actual,_=engine.execute(data,[dict(type='replace_text',page=1,line=line['id'],text='Version 1.25')])
        self.assertEqual(pixels(actual),pixels(make(last='1.25')))

    def test_repeated_split_digits_uses_target_position(self):
        def make(last='0.00'):
            d=fitz.open();p=d.new_page(width=420,height=240)
            for index,value in enumerate(('0.00','0.00',last)):
                y=60+index*65
                p.draw_rect((20,y-25,400,y+15),color=None,fill=(.94,.92,1))
                p.insert_text((35,y),'Reading '+str(index+1),fontname='hebo',fontsize=16)
                x=290
                if index==0:
                    p.insert_text((x,y),value,fontname='hebo',fontsize=16)
                else:
                    for char in value:
                        p.insert_text((x,y),char,fontname='hebo',fontsize=16)
                        x+=fitz.get_text_length(char,fontname='hebo',fontsize=16)
            data=d.tobytes();d.close();return data
        data=make()
        line=[l for l in engine.describe(data)[0]['lines'] if l['text']=='0.00'][-1]
        actual,_=engine.execute(data,[dict(type='replace_text',page=1,line=line['id'],text='1.25')])
        self.assertEqual(pixels(actual),pixels(make('1.25')))

    def test_overlapping_duplicate_text_still_rejected(self):
        data=fixture()
        with fitz.open(stream=data,filetype='pdf') as d:
            d[0].insert_text((35,108),'Version 0.00',fontname='hebo',fontsize=22)
            data=d.tobytes()
        with self.assertRaises(FidelityError):edit(data,'1.00')

    def test_duplicate_target_is_located_before_missing_glyph_check(self):
        from test_approximate import test_font
        d=fitz.open();p=d.new_page(width=420,height=240)
        p.insert_text((240,70),'0.00',fontname='hebo',fontsize=18)
        p.insert_font(fontname='Subset',fontbuffer=test_font(True))
        p.insert_text((240,160),'0.00',fontname='Subset',fontsize=18)
        d.subset_fonts();data=d.tobytes();d.close()
        row=[l for l in engine.describe(data)[0]['lines'] if l['text']=='0.00'][-1]
        # The other row has the desired glyphs. Its edit fails locality; the
        # actual target fails glyph availability. This used to become a vague
        # "cannot uniquely locate" error instead of identifying the real cause.
        with self.assertRaisesRegex(FidelityError,'no verified glyph'):
            engine.execute(data,[dict(type='replace_text',page=1,line=row['id'],text='5.67')])

    def test_duplicate_right_aligned_growth_targets_one_row(self):
        from test_alignment import fixture
        data=fixture(('28.140','28.140','28.140'),split=True)
        row=[l for l in engine.describe(data)[0]['lines'] if l['text']=='28.140'][-1]
        result,_=engine.execute(data,[dict(type='replace_text',page=1,line=row['id'],text='112.560',align='right')])
        expected=fixture(('28.140','28.140','112.560'),split=True)
        self.assertEqual(pixels(result),pixels(expected))

    def test_embedded_glyph_without_internal_unicode_cmap(self):
        from test_approximate import test_font
        from fontTools.ttLib import TTFont
        from pypdf import PdfReader
        d=fitz.open();p=d.new_page(width=420,height=240)
        p.insert_font(fontname='Embedded',fontbuffer=test_font(True))
        p.insert_text((200,90),'0.00',fontname='Embedded',fontsize=18)
        data=d.tobytes();d.close()
        reader=PdfReader(io.BytesIO(data))
        font=reader.pages[0]['/Resources']['/Font']['/Embedded'].get_object()
        ff=font['/DescendantFonts'][0].get_object()['/FontDescriptor']['/FontFile2']
        tt=TTFont(io.BytesIO(ff.get_data()));del tt['cmap']
        buf=io.BytesIO();tt.save(buf)
        with fitz.open(stream=data,filetype='pdf') as d:
            d.update_stream(ff.indirect_reference.idnum,buf.getvalue())
            data=d.tobytes()
        row=engine.describe(data)[0]['lines'][0]
        result,details=engine.execute(data,[dict(type='replace_text',page=1,line=row['id'],text='8.00')])
        self.assertIn('8.00',str(engine.describe(result)))
        self.assertFalse(engine.approximate_fonts(result))

    def test_split_mixed_weight_runs(self):
        def build(value):
            d=fitz.open();p=d.new_page(width=420,height=240)
            p.draw_rect((20,70,400,130),color=None,fill=(.94,.92,1))
            p.insert_text((35,108),'Version ',fontname='helv',fontsize=22)
            x=35+fitz.get_text_length('Version ',fontname='helv',fontsize=22)
            p.insert_text((x,108),value,fontname='hebo',fontsize=22)
            data=d.tobytes();d.close();return data
        self.assertEqual(pixels(edit(build('0.00'),'1.00')),pixels(build('1.00')))

    def test_existing_kern_spacing_preserved(self):
        data=fixture()
        with fitz.open(stream=data,filetype='pdf') as d:
            for x in d[0].get_contents():
                stream=d.xref_stream(x)
                if b'56657273696f6e20302e3030' in stream:
                    stream=stream.replace(b'[<56657273696f6e20302e3030>]',b'[<56657273696f6e20> -50 <30> 15 <2e3030>]')
                    d.update_stream(x,stream)
            data=d.tobytes()
        actual=edit(data,'1.00')
        with fitz.open(stream=data,filetype='pdf') as d:
            for x in d[0].get_contents():
                stream=d.xref_stream(x).replace(b'<30> 15',b'<31> 15')
                d.update_stream(x,stream)
            expected=d.tobytes()
        self.assertEqual(pixels(actual),pixels(expected))

if __name__=='__main__':unittest.main()
