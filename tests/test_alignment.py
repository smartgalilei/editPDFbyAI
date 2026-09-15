import unittest
import io
import pymupdf as fitz
import engine
from fidelity import FidelityError


def fixture(values=('28.140','125,480.16','-0.021'), split=False, blocked=False, grid=False):
    d=fitz.open();p=d.new_page(width=520,height=330)
    p.insert_text((30,35),'FICTIONAL / ALIGNMENT TEST',fontsize=14)
    for i,value in enumerate(values):
        y=95+i*75
        p.draw_rect((22,y-28,500,y+14),fill=(.94,.93,1),color=None)
        p.insert_text((30,y),'Reading '+str(i+1),fontsize=13)
        x=470-fitz.get_text_length(value,fontname='hebo',fontsize=16)
        if blocked:p.insert_text((x-60,y),'X',fontsize=13)
        if grid:p.draw_line((x-4,y-25),(x-4,y+10),width=.5)
        if split:
            for c in value:
                p.insert_text((x,y),c,fontname='hebo',fontsize=16)
                x+=fitz.get_text_length(c,fontname='hebo',fontsize=16)
        else:p.insert_text((x,y),value,fontname='hebo',fontsize=16)
    b=d.tobytes();d.close();return b


def edit(data,old,new,align='right'):
    line=next(l for l in engine.describe(data)[0]['lines'] if l['text']==old)
    return engine.execute(data,[dict(type='replace_text',page=1,line=line['id'],text=new,align=align)])[0]


def pixels(data):
    with fitz.open(stream=data,filetype='pdf') as d:
        return d[0].get_pixmap(matrix=fitz.Matrix(3,3)).samples


class AlignmentTests(unittest.TestCase):
    def test_increasing_digits_matches_independent_right_aligned_pdf(self):
        before=fixture()
        actual=edit(before,'28.140','112.560')
        expected=fixture(('112.560','125,480.16','-0.021'))
        self.assertEqual(pixels(actual),pixels(expected))

    def test_batch_grouped_negative_numbers(self):
        before=fixture();ops=[]
        changes={'28.140':'112.560','125,480.16':'1,125,480.16','-0.021':'-0.084'}
        for l in engine.describe(before)[0]['lines']:
            if l['text'] in changes:ops.append(dict(type='replace_text',page=1,line=l['id'],text=changes[l['text']],align='right'))
        actual,_=engine.execute(before,ops)
        self.assertEqual(pixels(actual),pixels(fixture(tuple(changes.values()))))

    def test_split_numeric_objects(self):
        actual=edit(fixture(split=True),'28.140','112.560')
        self.assertEqual(pixels(actual),pixels(fixture(('112.560','125,480.16','-0.021'))))

    def test_shorter_right_aligned_number(self):
        actual=edit(fixture(),'125,480.16','480.16')
        self.assertEqual(pixels(actual),pixels(fixture(('28.140','480.16','-0.021'))))

    def test_text_and_table_collision_rejected(self):
        for kwargs in (dict(blocked=True),dict(grid=True)):
            data=fixture(**kwargs)
            with self.assertRaisesRegex(ValueError,'other text|table boundary'):
                edit(data,'28.140','1,111,112,560.00')

    def test_page_overflow_rejected(self):
        with self.assertRaises(FidelityError):edit(fixture(),'28.140','1'*100)

    def test_original_alignment_still_rejects_growth(self):
        with self.assertRaisesRegex(FidelityError,'right alignment'):edit(fixture(),'28.140','112.560',align='original')

    def test_general_text_and_invalid_alignment_enum(self):
        self.assertIn('New Heading',str(engine.describe(edit(fixture(),'28.140','New Heading'))))
        with self.assertRaises(ValueError):edit(fixture(),'28.140','112.560',align='invalid')

    def test_equal_length_edit_preserves_TJ_spacing(self):
        data=fixture()
        with fitz.open(stream=data,filetype='pdf') as d:
            for x in d[0].get_contents():
                raw=d.xref_stream(x)
                if b'32382e313430' in raw:
                    d.update_stream(x,raw.replace(b'<32382e313430>',b'<32382e> 12 <31> 12 <3430>'))
            data=d.tobytes()
        actual=edit(data,'28.140','28.250',align='original')
        with fitz.open(stream=data,filetype='pdf') as d:
            for x in d[0].get_contents():
                raw=d.xref_stream(x).replace(b'<31> 12 <3430>',b'<32> 12 <3530>')
                d.update_stream(x,raw)
            expected=d.tobytes()
        self.assertEqual(pixels(actual),pixels(expected))

    def test_right_alignment_with_approximate_digits(self):
        from test_approximate import fixture as font_fixture
        data=font_fixture()
        # Move fictional source text right to leave adequate space for growth.
        with fitz.open(stream=data,filetype='pdf') as d:
            for x in d[0].get_contents():
                d.update_stream(x,d.xref_stream(x).replace(b'30 180 Tm',b'300 180 Tm'))
            data=d.tobytes()
        line=next(l for l in engine.describe(data)[0]['lines'] if l['text']=='0.00')
        result,_=engine.execute(data,[dict(type='replace_text',page=1,line=line['id'],text='12.56',align='right')],approximate_digits=True)
        new=next(l for l in engine.describe(result)[0]['lines'] if l['text']=='12.56')
        self.assertAlmostEqual(new['bbox'][2],line['bbox'][2],places=2)
        self.assertTrue(engine.approximate_fonts(result))


if __name__=='__main__':unittest.main()
