"""General alignment on independent, fictional layout fixtures."""
import unittest
import pymupdf as fitz
import engine
from test_alignment import pixels


def fixture(x=60,y=90,text='Sample title',rotation=0,transformed=False):
    d=fitz.open();p=d.new_page(width=600,height=500)
    p.draw_rect((20,20,580,480),fill=(.94,.93,1),color=None)
    p.insert_text((35,35),'FICTIONAL LAYOUT SAMPLE',fontsize=10)
    p.insert_text((x,y),text,fontsize=16,fontname='hebo')
    p.insert_text((35,465),'Unchanged footer',fontsize=11)
    if transformed:
        for ref in p.get_contents():
            raw=d.xref_stream(ref)
            if b'53616d706c65207469746c65' in raw:
                d.update_stream(ref,raw.replace(b'BT',b'1.2 0 0 0.8 0 0 cm\nBT\n3 Ts\n85 Tz'))
    p.set_rotation(rotation)
    return d.tobytes()


def operation(data,**fields):
    l=next(l for l in engine.describe(data)[0]['lines'] if l['text']=='Sample title')
    return dict(type='align_text',page=1,line=l['id'],**fields)


class LayoutTests(unittest.TestCase):
    def test_nine_anchors_match_independent_render(self):
        data=fixture();old=engine.describe(data)[0]['lines'][1];r=fitz.Rect(old['bbox'])
        target=fitz.Rect(160,170,500,370)
        for align in ('left','center','right'):
            for valign in ('top','middle','bottom'):
                with self.subTest(align=align,valign=valign):
                    x={'left':target.x0,'center':(target.x0+target.x1-r.width)/2,'right':target.x1-r.width}[align]
                    y={'top':target.y0,'middle':(target.y0+target.y1-r.height)/2,'bottom':target.y1-r.height}[valign]
                    out,_=engine.execute(data,[operation(data,align=align,valign=valign,box=list(target))])
                    self.assertEqual(pixels(out),pixels(fixture(x,y+old['origin'][1]-r.y0)))

    def test_replace_and_align_non_numeric(self):
        data=fixture();op=operation(data,align='center',valign='middle',box=[150,150,500,380]);op.update(type='replace_text',text='A longer sample title')
        out,_=engine.execute(data,[op]);line=next(l for l in engine.describe(out)[0]['lines'] if l['text']==op['text'])
        self.assertAlmostEqual((line['bbox'][0]+line['bbox'][2])/2,325,places=2)
        self.assertAlmostEqual((line['bbox'][1]+line['bbox'][3])/2,265,places=2)

    def test_rotated_and_scaled_coordinates(self):
        for rot in (0,90,180,270):
            for transformed in (False,True):
                with self.subTest(rotation=rot,transformed=transformed):
                    data=fixture(rotation=rot,transformed=transformed)
                    out,_=engine.execute(data,[operation(data,align='right',valign='bottom',box=[150,150,500,380])])
                    line=next(l for l in engine.describe(out)[0]['lines'] if l['text']=='Sample title')
                    self.assertAlmostEqual(line['bbox'][2],500,places=2)
                    self.assertAlmostEqual(line['bbox'][3],380,places=2)
                    self.assertEqual(engine.describe(out)[0]['rotation'],rot)

    def test_page_center(self):
        data=fixture();out,_=engine.execute(data,[operation(data,align='center',valign='middle',box='page')])
        r=fitz.Rect(next(l for l in engine.describe(out)[0]['lines'] if l['text']=='Sample title')['bbox'])
        self.assertAlmostEqual((r.x0+r.x1)/2,300,places=2)
        self.assertAlmostEqual((r.y0+r.y1)/2,250,places=2)

    def test_invalid_geometry_and_collision(self):
        data=fixture()
        for fields in (dict(box=[1,2,3]),dict(box=[1,2,3,2]),dict(box=[1,2,700,800]),dict(valign='diagonal'),dict(align='justify'),dict(box=[30,25,400,80],align='left',valign='top'),dict(box=[100,100,110,110],align='left',valign='top')):
            with self.subTest(fields=fields),self.assertRaises(ValueError):engine.execute(data,[operation(data,**fields)])

    def test_preserve_kerning_and_next_show_position(self):
        data=fixture()
        with fitz.open(stream=data,filetype='pdf') as d:
            for ref in d[0].get_contents():
                raw=d.xref_stream(ref)
                if b'53616d706c65207469746c65' in raw:
                    d.update_stream(ref,raw.replace(b'<53616d706c65207469746c65>',b'<53616d706c65> 30 <207469746c65>'))
            data=d.tobytes()
        out,_=engine.execute(data,[operation(data,align='left',valign='top',box=[160,170,500,370])])
        before=next(l for l in engine.describe(data)[0]['lines'] if l['text']=='Sample title')
        after=next(l for l in engine.describe(out)[0]['lines'] if l['text']=='Sample title')
        self.assertAlmostEqual(before['bbox'][2]-before['bbox'][0],after['bbox'][2]-after['bbox'][0],places=2)

    def test_mixed_font_move_keeps_styles(self):
        d=fitz.open();p=d.new_page(width=600,height=500)
        p.insert_text((60,90),'Sample ',fontname='hebo',fontsize=16)
        x=60+fitz.get_text_length('Sample ',fontname='hebo',fontsize=16)
        p.insert_text((x,90),'title',fontname='heit',fontsize=16)
        data=d.tobytes();d.close()
        out,_=engine.execute(data,[operation(data,align='right',valign='bottom',box=[150,150,500,380])])
        with fitz.open(stream=out,filetype='pdf') as d:
            spans=d[0].get_text('dict')['blocks'][0]['lines'][0]['spans']
            self.assertEqual([s['font'] for s in spans],['Helvetica-Bold','Helvetica-Oblique'])

    def test_replacement_restores_following_text_state(self):
        d=fitz.open();p=d.new_page(width=600,height=500)
        p.insert_text((60,90),'Sample title',fontname='hebo',fontsize=16)
        ref=p.get_contents()[0];raw=d.xref_stream(ref)
        raw=raw.replace(b'ET',b'0 -300 Td [(Footer)] TJ\nET')
        d.update_stream(ref,raw);data=d.tobytes();d.close()
        op=operation(data,align='right',valign='bottom',box=[150,150,500,300]);op.update(type='replace_text',text='New heading')
        out,_=engine.execute(data,[op])
        before=next(l for l in engine.describe(data)[0]['lines'] if l['text']=='Footer')
        after=next(l for l in engine.describe(out)[0]['lines'] if l['text']=='Footer')
        self.assertEqual(before['bbox'],after['bbox'])
