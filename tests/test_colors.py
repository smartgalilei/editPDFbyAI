import unittest
import pymupdf as fitz
import engine
from test_alignment import pixels


def fixture(text_color=(0,0,0),background=(.93,.93,1),partial=False,rotation=0):
    d=fitz.open();p=d.new_page(width=500,height=300)
    p.draw_rect((30,60,470,140),fill=background,color=(.3,.3,.3),width=1)
    if partial:p.draw_rect((250,65,460,135),fill=(1,230/255,.6),color=None)
    p.insert_text((40,100),'Sample ',fontsize=18,fontname='hebo')
    x=40+fitz.get_text_length('Sample ',fontname='hebo',fontsize=18)
    p.insert_text((x,100),'title',fontsize=18,fontname='hebo',color=text_color)
    p.insert_text((40,200),'Footer remains unchanged',fontsize=12)
    p.set_rotation(rotation)
    return d.tobytes()


def text_op(data,**args):
    line=next(l for l in engine.describe(data)[0]['lines'] if l['text']=='Sample title')
    return dict(type='color_text',page=1,line=line['id'],color='#336699',**args)


class ColorTests(unittest.TestCase):
    def test_partial_text_matches_independent_drawing(self):
        data=fixture();out,_=engine.execute(data,[text_op(data,text='title')])
        self.assertEqual(pixels(out),pixels(fixture(text_color=(.2,.4,.6))))
        a=engine.describe(data);b=engine.describe(out)
        self.assertEqual([(l['text'],l['bbox']) for l in a[0]['lines']],[(l['text'],l['bbox']) for l in b[0]['lines']])

    def test_full_background_keeps_border_text_and_geometry(self):
        for rot in (0,90,180,270):
            data=fixture(rotation=rot)
            out,_=engine.execute(data,[dict(type='background_color',page=1,rect=[30,60,470,140],color='#FFCC99')])
            self.assertEqual(pixels(out),pixels(fixture(background=(1,.8,.6),rotation=rot)))
            self.assertEqual(engine.describe(data)[0]['lines'],engine.describe(out)[0]['lines'])

    def test_partial_background(self):
        data=fixture()
        out,_=engine.execute(data,[dict(type='background_color',page=1,rect=[250,65,460,135],color='#FFE699')])
        self.assertEqual(pixels(out),pixels(fixture(partial=True)))

    def test_blank_background_and_text_color_batch(self):
        data=fixture()
        out,_=engine.execute(data,[text_op(data,text='title'),dict(type='background_color',page=1,rect=[30,180,470,220],color='#CCFFCC')])
        with fitz.open(stream=fixture(text_color=(.2,.4,.6)),filetype='pdf') as d:
            d[0].draw_rect((30,180,470,220),fill=(.8,1,.8),color=None,overlay=False)
            expected=d.tobytes()
        self.assertEqual(pixels(out),pixels(expected))

    def test_repeated_fragment_requires_occurrence(self):
        d=fitz.open();p=d.new_page();p.insert_text((50,60),'Test Test',fontsize=16);data=d.tobytes()
        op=dict(type='color_text',page=1,line='l1',text='Test',color='#FF0000')
        with self.assertRaisesRegex(ValueError,'repeats'):engine.execute(data,[op])
        out,_=engine.execute(data,[dict(op,occurrence=2)])
        with fitz.open(stream=out,filetype='pdf') as d:
            spans=d[0].get_text('dict')['blocks'][0]['lines'][0]['spans']
            self.assertEqual(spans[0]['color'],0);self.assertEqual(spans[-1]['color'],0xff0000)

    def test_invalid_inputs_and_cross_background(self):
        data=fixture()
        for op in (dict(type='background_color',page=1,rect=[20,50,480,150],color='#FFFFFF'),dict(type='background_color',page=1,rect=[0,0,600,600],color='#FFFFFF'),dict(text_op(data),color='red'),dict(text_op(data),text='missing'),dict(text_op(data),occurrence=0)):
            with self.subTest(op=op),self.assertRaises(ValueError):engine.execute(data,[op])

    def test_image_background_rejected(self):
        d=fitz.open();p=d.new_page();pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(100)
        p.insert_image((20,20,200,200),pixmap=pix)
        with self.assertRaisesRegex(ValueError,'images'):engine.execute(d.tobytes(),[dict(type='background_color',page=1,rect=[30,30,100,100],color='#FFFFFF')])

    def test_fractional_background_boundary_matches(self):
        def make(color):
            d=fitz.open();p=d.new_page(width=300,height=200)
            p.draw_rect((20.13,30.27,250.63,100.87),fill=color,color=(0,0,0),width=.7)
            return d.tobytes()
        data=make((.9,.9,.9))
        out,_=engine.execute(data,[dict(type='background_color',page=1,rect=[20.13,30.27,250.63,100.87],color='#FFCC99')])
        self.assertEqual(pixels(out),pixels(make((1,.8,.6))))

    def test_text_whole_line_and_shared_object_restore_color(self):
        d=fitz.open();p=d.new_page();p.insert_text((40,60),'First Second',fontsize=18,color=(.2,.4,.6))
        x=p.get_contents()[0];d.update_stream(x,d.xref_stream(x).replace(b'ET',b'0 -50 Td [(Footer)] TJ\nET'));data=d.tobytes()
        op=dict(type='color_text',page=1,line='l1',text='Second',color='#FF0000')
        out,_=engine.execute(data,[op])
        lines=engine.describe(out)[0]['lines']
        self.assertEqual(lines[-1]['color'],0x336699)
        whole,_=engine.execute(data,[dict(type='color_text',page=1,line='l1',color='#FF0000')])
        self.assertEqual(engine.describe(whole)[0]['lines'][0]['color'],0xff0000)

    def test_transparent_background_rejected(self):
        d=fitz.open();p=d.new_page();p.draw_rect((10,10,200,100),fill=(.5,.5,.5),fill_opacity=.5)
        with self.assertRaisesRegex(ValueError,'Transparent'):engine.execute(d.tobytes(),[dict(type='background_color',page=1,rect=[20,20,180,80],color='#FFFFFF')])

    def test_background_preserves_foreground_image(self):
        def make(color):
            d=fitz.open();p=d.new_page(width=300,height=200)
            p.draw_rect((10,10,290,190),fill=color,color=None)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(100)
            p.insert_image((50,50,100,100),pixmap=pix)
            return d.tobytes()
        data=make((.9,.9,.9));out,_=engine.execute(data,[dict(type='background_color',page=1,rect=[10,10,290,190],color='#FFCC99')])
        self.assertEqual(pixels(out),pixels(make((1,.8,.6))))

    def test_text_color_rotated_pages(self):
        for rot in (90,180,270):
            data=fixture(rotation=rot);out,_=engine.execute(data,[text_op(data,text='title')])
            self.assertEqual(pixels(out),pixels(fixture(text_color=(.2,.4,.6),rotation=rot)))

    def test_alignment_preserves_mixed_colors_and_replacement_rejects_merge(self):
        data=fixture();colored,_=engine.execute(data,[text_op(data,text='title')])
        line=engine.describe(colored)[0]['lines'][0]
        moved,_=engine.execute(colored,[dict(type='align_text',page=1,line=line['id'],align='right',box=[30,60,460,140])])
        with fitz.open(stream=moved,filetype='pdf') as d:
            spans=d[0].get_text('dict')['blocks'][0]['lines'][0]['spans']
            self.assertEqual([s['color'] for s in spans],[0,0x336699])
        with self.assertRaisesRegex(ValueError,'different styles'):
            engine.execute(colored,[dict(type='replace_text',page=1,line=line['id'],text='Another title',align='right')])
