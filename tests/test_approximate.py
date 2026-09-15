"""Generated fonts and fictional documents; no account statements in tests."""
import io
import unittest

import pathops
import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pypdf import PdfReader

import approximate
import engine
from fidelity import FidelityError


def test_font(bold=False):
    """Portable seven-segment digits, with known regular/bold geometry."""
    fb=FontBuilder(1000,isTTF=True)
    chars='0123456789.'
    order=['.notdef']+['u'+str(ord(c)) for c in chars]
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({ord(c):order[i+1] for i,c in enumerate(chars)})
    glyphs={};metrics={}
    segments=['abcdef','bc','abdeg','abcdg','bcfg','acdfg','acdefg','abc','abcdefg','abcdfg']
    coords=dict(a=(130,655,430,655),b=(465,375,465,620),c=(465,70,465,325),
                d=(130,35,430,35),e=(95,70,95,325),f=(95,375,95,620),g=(130,350,430,350))
    for i,name in enumerate(order):
        p=pathops.Path()
        if i:
            c=chars[i-1]; thick=85 if bold else 45
            rs=[(240,0,310,70)] if c=='.' else [
                (x0-thick/2,y0-thick/2,x1+thick/2,y1+thick/2)
                for k in segments[int(c)] for x0,y0,x1,y1 in [coords[k]]]
            for x0,y0,x1,y1 in rs:
                p.moveTo(x0,y0);p.lineTo(x0,y1);p.lineTo(x1,y1);p.lineTo(x1,y0);p.close()
        pen=TTGlyphPen(None);p.draw(pen);glyphs[name]=pen.glyph();metrics[name]=(600,0)
    fb.setupGlyf(glyphs);fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800,descent=-200)
    style='Bold' if bold else 'Regular'
    fb.setupNameTable(dict(familyName='FixtureDigits',styleName=style,uniqueFontIdentifier='FixtureDigits-'+style,fullName='FixtureDigits-'+style,psName='FixtureDigits-'+style))
    fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200,usWeightClass=700 if bold else 400)
    fb.setupPost();fb.setupMaxp()
    out=io.BytesIO();fb.save(out);return out.getvalue()


def fixture(donor=True, repeated=False):
    d=fitz.open();p=d.new_page(width=480,height=330)
    p.insert_font(fontname='Bold',fontbuffer=test_font(True))
    p.insert_text((30,35),'TYPOGRAPHY TEST / FICTIONAL',fontsize=13)
    p.insert_text((30,84),'01234',fontname='Bold',fontsize=18)
    p.draw_rect((25,110,450,167),color=None,fill=(.94,.93,1))
    p.insert_text((30,150),'0.00',fontname='Bold',fontsize=24)
    if repeated:
        p.insert_text((30,198),'0.00',fontname='Bold',fontsize=24)
    if donor:
        p.insert_font(fontname='Regular',fontbuffer=test_font())
        p.insert_text((30,260),'0123456789',fontname='Regular',fontsize=18)
    p=d.new_page(width=480,height=330)
    p.insert_font(fontname='Bold',fontbuffer=test_font(True))
    p.insert_text((30,100),'01234',fontname='Bold',fontsize=28)
    d.subset_fonts()
    result=d.tobytes(garbage=4,deflate=True);d.close();return result


def operation(data,value='5.67',last=False):
    rows=[l for l in engine.describe(data)[0]['lines'] if l['text']=='0.00']
    return dict(type='replace_text',page=1,line=rows[-1 if last else 0]['id'],text=value)


class ApproximateTests(unittest.TestCase):
    def test_default_rejects_and_opt_in_exports_real_text(self):
        data=fixture();op=operation(data)
        with self.assertRaises(FidelityError):
            engine.execute(data,[op])
        result,summaries=engine.execute(data,[op],approximate_digits=True)
        with fitz.open(stream=result,filetype='pdf') as doc:
            self.assertIn('5.67',doc[0].get_text())
            self.assertNotIn('0.00',doc[0].get_text())
        self.assertTrue(any(s.startswith('Approximated digits 567') for s in summaries))
        self.assertIn('0.00',str(engine.describe(data)))

    def test_existing_glyphs_and_shared_page_unchanged(self):
        data=fixture()
        line=next(l for l in engine.describe(data)[0]['lines'] if l['text']=='0.00')
        prepared,_=approximate.prepare(data,[dict(page=1,line=line,text='5.67')])
        with fitz.open(stream=data,filetype='pdf') as a,fitz.open(stream=prepared,filetype='pdf') as b:
            for x,y in zip(a,b):
                self.assertEqual(x.get_pixmap(matrix=fitz.Matrix(3,3)).samples,y.get_pixmap(matrix=fitz.Matrix(3,3)).samples)
        result,_=engine.execute(data,[operation(data)],approximate_digits=True)
        with fitz.open(stream=data,filetype='pdf') as a,fitz.open(stream=result,filetype='pdf') as b:
            self.assertEqual(a[1].get_pixmap().samples,b[1].get_pixmap().samples)

    def test_generated_font_can_be_reopened_and_edited_again(self):
        data=fixture()
        result,_=engine.execute(data,[operation(data)],approximate_digits=True)
        line=next(l for l in engine.describe(result)[0]['lines'] if l['text']=='5.67')
        result,summaries=engine.execute(result,[dict(type='replace_text',page=1,line=line['id'],text='8.95')],approximate_digits=True)
        self.assertIn('8.95',str(engine.describe(result)))
        self.assertTrue(any('89' in s and s.startswith('Approximated') for s in summaries))

    def test_repeated_values_still_select_last_row(self):
        data=fixture(repeated=True)
        result,_=engine.execute(data,[operation(data,last=True)],approximate_digits=True)
        text=[l['text'] for l in engine.describe(result)[0]['lines']]
        self.assertEqual(text.count('0.00'),1)
        self.assertEqual(text.count('5.67'),1)

    def test_no_donor_or_non_digits_not_guessed(self):
        data=fixture(donor=False)
        with self.assertRaisesRegex(approximate.ApproximationError,'Regular'):
            engine.execute(data,[operation(data)],approximate_digits=True)
        data=fixture()
        with self.assertRaises(FidelityError):
            engine.execute(data,[operation(data,'ABCD')],approximate_digits=True)

    def test_sample_is_separate_labelled_document(self):
        data=fixture();desc=engine.describe(data)
        line=next(l for l in desc[0]['lines'] if l['text']=='0.00')
        sample=approximate.sample(data,1,line)
        with fitz.open(stream=sample,filetype='pdf') as d:
            self.assertEqual(len(d),1)
            self.assertIn('0123456789',d[0].get_text())
            self.assertIn('近似',d[0].get_text())
            self.assertNotIn('TYPOGRAPHY TEST',d[0].get_text())
        self.assertEqual(desc,engine.describe(data))

    def test_only_requested_missing_digits_added(self):
        data=fixture()
        result,_=engine.execute(data,[operation(data,'0.05')],approximate_digits=True)
        faces=list(approximate.fonts(PdfReader(io.BytesIO(result))))
        bold=next(f for f in faces if f.name.lower().endswith('bold'))
        self.assertIsNotNone(bold.path('5'))
        self.assertIsNone(bold.path('6'))
        self.assertEqual(str(bold.resource['/PDFeditApproxDigits']),'5')

    def test_strict_existing_edit_does_not_add_synthetic_font(self):
        data=fixture()
        a,_=engine.execute(data,[operation(data,'2.20')])
        b,summaries=engine.execute(data,[operation(data,'2.20')],approximate_digits=True)
        self.assertFalse(any(s.startswith('Approximated') for s in summaries))
        with fitz.open(stream=a,filetype='pdf') as x,fitz.open(stream=b,filetype='pdf') as y:
            self.assertEqual(x[0].get_pixmap().samples,y[0].get_pixmap().samples)

    def test_opt_in_type_is_validated(self):
        with self.assertRaises(ValueError):
            engine.execute(fixture(),[],approximate_digits='false')

    def test_fractional_digits_and_font_name_spacing(self):
        data=fixture()
        with fitz.open(stream=data,filetype='pdf') as doc:
            for f in doc[0].get_fonts():
                if f[3].endswith('Bold'):
                    doc.xref_set_key(f[0],'BaseFont','/'+f[3].replace(' ','-'))
            data=doc.tobytes()
        for value in ('2.25','1.06'):
            result,_=engine.execute(data,[operation(data,value)],approximate_digits=True)
            self.assertIn(value,str(engine.describe(result)))


if __name__=='__main__':
    unittest.main()
