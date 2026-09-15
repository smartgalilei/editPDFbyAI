"""Opt-in, local digit synthesis. Never described as the original typeface.

Only embedded Identity-H TrueType Bold / Regular pairs with tabular digits
are supported. Missing shapes are derived from the regular face, using the
observed bold digits to calibrate an outline expansion. No external fonts or AI.
"""
import io
import re
import statistics
from copy import deepcopy

import pathops
import pymupdf as fitz
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pypdf import PdfReader


class ApproximationError(ValueError):
    pass


def reject(message):
    raise ApproximationError('Cannot approximate missing digits: ' + message)


def family(name):
    name = name.split('+')[-1].lower()
    return re.sub(r'[\s_-]', '', re.sub(r'(bold|regular)$', '', name))


def font_key(name):
    return re.sub(r'[\s_-]','',name.lstrip('/').split('+')[-1]).lower()


class Embedded:
    def __init__(self, resource):
        from fidelity import FontCodec
        self.resource = resource
        self.codec = FontCodec(resource)
        self.name = self.codec.name
        if resource.get('/Subtype') != '/Type0' or resource.get('/Encoding') != '/Identity-H':
            reject('Only embedded TrueType fonts with Identity-H encoding are supported.')
        self.desc = resource['/DescendantFonts'][0].get_object()
        self.descriptor = self.desc['/FontDescriptor']
        if '/FontFile2' not in self.descriptor:
            reject('The font has no supported TrueType outlines.')
        self.raw = self.descriptor['/FontFile2'].get_data()
        self.tt = TTFont(io.BytesIO(self.raw), recalcTimestamp=False)
        if 'glyf' not in self.tt:
            reject('Unsupported glyph outline format.')
        self.upm = self.tt['head'].unitsPerEm
        mapping = self.desc.get('/CIDToGIDMap', '/Identity')
        self.cidmap = mapping.get_object().get_data() if hasattr(mapping.get_object() if hasattr(mapping, 'get_object') else mapping, 'get_data') else None
        if self.cidmap is None and str(mapping) != '/Identity':
            reject('Unsupported CID glyph mapping.')
        self.order = self.tt.getGlyphOrder()
        self.paths = {}

    def gid(self, cid):
        if self.cidmap is None:
            return cid
        return int.from_bytes(self.cidmap[2*cid:2*cid+2], 'big')

    def path(self, char):
        if char in self.paths:
            return self.paths[char]
        cid = self.codec.reverse.get(char)
        if cid is None:
            return None
        gid = self.gid(cid)
        if not 0 < gid < len(self.order):
            return None
        glyphs = self.tt.getGlyphSet()
        p = pathops.Path()
        glyphs[self.order[gid]].draw(p.getPen(glyphs))
        if not p.bounds or not p.area:
            return None
        p = p.transform(1000/self.upm, 0, 0, 1000/self.upm)
        self.paths[char] = p
        return p


def fonts(reader):
    seen = set()
    for page in reader.pages:
        for reference in page['/Resources'].get('/Font', {}).values():
            obj = reference.get_object()
            identity = getattr(obj,'indirect_reference',None).idnum if getattr(obj,'indirect_reference',None) else id(obj)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                yield Embedded(obj)
            except (ValueError, KeyError, TypeError):
                continue


class Synthesis:
    def __init__(self, bold, regular):
        self.bold, self.regular = bold, regular
        self.common = [c for c in '01234' if bold.path(c) is not None and regular.path(c) is not None]
        if len(self.common) < 3 or '0' not in self.common:
            reject('At least three comparable digits from 0-4, including 0, are required in the same font family.')
        widths = [bold.codec.width(bold.codec.reverse[c]) for c in self.common]
        if max(widths)-min(widths) > .5:
            reject('Only tabular digits are supported; missing character widths cannot be reliably inferred.')
        self.width = statistics.median(widths)
        # Estimate geometry from several observed pairs, rather than assuming
        # identical outlines or treating the regular face as the bold face.
        pairs = [(bold.path(c).bounds, regular.path(c).bounds) for c in self.common]
        self.rx = statistics.median((a[2]-a[0])/(b[2]-b[0]) for a,b in pairs)
        self.ry = statistics.median((a[3]-a[1])/(b[3]-b[1]) for a,b in pairs)
        self.dx = statistics.median((a[0]+a[2]-b[0]-b[2])/2 for a,b in pairs)
        self.dy = statistics.median((a[1]+a[3]-b[1]-b[3])/2 for a,b in pairs)
        def loss(strength):
            scores = []
            for c in self.common:
                p = self.make(c, strength)
                q = bold.path(c)
                union = pathops.op(p, q, pathops.PathOp.UNION).area
                scores.append(pathops.op(p, q, pathops.PathOp.XOR).area / union)
            return statistics.mean(scores)
        coarse = min(range(0, 121, 8), key=loss)
        self.strength = min(range(max(0,coarse-7), min(120,coarse+7)+1), key=loss)
        self.error = loss(self.strength)
        if self.strength in (0,120) or self.error > .35:
            reject('The weight fit differs too much to generate usable approximate digits.')

    def make(self, char, strength=None):
        p = self.regular.path(char)
        if p is None:
            reject(f'The matching Regular font is also missing digit {char}.')
        strength = self.strength if strength is None else strength
        b = p.bounds
        cx, cy = (b[0]+b[2])/2+self.dx, (b[1]+b[3])/2+self.dy
        w, h = (b[2]-b[0])*self.rx, (b[3]-b[1])*self.ry
        if strength:
            stroke = pathops.Path(p)
            stroke.stroke(strength, pathops.LineCap.BUTT_CAP, pathops.LineJoin.MITER_JOIN, 2)
            stroke.convertConicsToQuads(.1)
            p = pathops.op(p, stroke, pathops.PathOp.UNION)
            p.convertConicsToQuads(.1)
        x0,y0,x1,y1 = p.bounds
        sx,sy = w/(x1-x0),h/(y1-y0)
        result = p.transform(sx,0,0,sy,cx-w/2-sx*x0,cy-h/2-sy*y0)
        if result.bounds[0] < -2 or result.bounds[2] > self.width+2:
            reject(f'Generated digit {char} exceeds its original advance width.')
        return result

    def report(self, chars):
        return dict(font=self.bold.name, reference=self.regular.name, generated=''.join(chars),
                    method='Regular outline expansion and dimensional fitting', stroke=self.strength,
                    calibrationDifference=round(self.error,4), common=''.join(self.common))


def pair_for(bold, available):
    if not bold.name.lower().endswith('bold'):
        reject('Only missing digits in Bold fonts can be approximated.')
    donors = [f for f in available if family(f.name) == family(bold.name)
              and f.name != bold.name and not f.name.lower().endswith('bold')
              and all(f.path(c) is not None for c in '0123456789')]
    # Multiple subsets of the same regular font may coexist. The selected one
    # must cover all digits; use the best measured fit, never an unrelated font.
    models = []
    for donor in donors:
        try:
            models.append(Synthesis(bold, donor))
        except ApproximationError:
            pass
    if not models:
        reject('No matching Regular font with a complete digit set was found. Glyphs cannot be inferred without a reference.')
    return min(models, key=lambda m: m.error)


def add_paths(source, paths):
    """Append glyphs; all original GIDs and glyph instructions stay intact."""
    tt = deepcopy(source.tt)
    order = tt.getGlyphOrder()[:]
    added = {}
    for char, (path, width) in paths.items():
        name = 'PDFeditApprox' + str(ord(char))
        while name in order:
            name += '_'
        pen = TTGlyphPen(None)
        path.transform(source.upm/1000,0,0,source.upm/1000).draw(Cu2QuPen(pen, max_err=.5, reverse_direction=False))
        glyph = pen.glyph()
        tt['glyf'][name] = glyph
        glyph.recalcBounds(tt['glyf'])
        tt['hmtx'][name] = (round(width*source.upm/1000), glyph.xMin)
        added[char] = len(order)
        order.append(name)
    tt.setGlyphOrder(order)
    # PDF subsets sometimes have no Unicode cmap. Add one so renderers and
    # subsequent edits can verify the new glyphs without relying on used codes.
    mapping = {}
    for cid,char in source.codec.decode_map.items():
        gid = source.gid(cid)
        if gid < len(source.order):
            mapping.setdefault(ord(char), source.order[gid])
    mapping.update({ord(c):order[gid] for c,gid in added.items()})
    if 'cmap' not in tt:
        tt['cmap'] = newTable('cmap'); tt['cmap'].tableVersion=0; tt['cmap'].tables=[]
    table = CmapSubtable.newSubtable(12)
    table.platformID=3; table.platEncID=10; table.language=0; table.cmap=mapping
    tt['cmap'].tables = [t for t in tt['cmap'].tables if not (t.platformID==3 and t.platEncID==10)] + [table]
    out = io.BytesIO(); tt.save(out)
    return out.getvalue(), added


def new_stream(doc, data):
    xref=doc.get_new_xref(); doc.update_object(xref,'<<>>'); doc.update_stream(xref,data)
    return f'{xref} 0 R'


def unicode_cmap(mapping):
    chunks = []
    items = sorted(mapping.items())
    for start in range(0,len(items),100):
        batch = items[start:start+100]
        chunks += [f'{len(batch)} beginbfchar']
        chunks += [f'<{cid:04x}> <{char.encode("utf-16-be").hex()}>' for cid,char in batch]
        chunks += ['endbfchar']
    return ('/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n'
            '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
            '/CMapName /PDFeditApprox def /CMapType 2 def\n'
            '1 begincodespacerange <0000> <FFFF> endcodespacerange\n' + '\n'.join(chunks) +
            '\nendcmap CMapName currentdict /CMap defineresource pop end end').encode()


def target_names(data, edits):
    names = set()
    with fitz.open(stream=data,filetype='pdf') as doc:
        for e in edits:
            rect = fitz.Rect(e['line']['bbox'])
            for block in doc[e['page']-1].get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    if ''.join(s['text'] for s in line['spans']) != e['line']['text']:
                        continue
                    if not rect.intersects(fitz.Rect(line['bbox'])):
                        continue
                    names.update(font_key(s['font']) for s in line['spans'])
    return names


def target_fonts(data, reader, edits):
    targets={}
    for edit in edits:
        names=target_names(data,[edit])
        for reference in reader.pages[edit['page']-1]['/Resources'].get('/Font',{}).values():
            resource=reference.get_object()
            if font_key(str(resource.get('/BaseFont',''))) in names:
                if getattr(resource,'indirect_reference',None):
                    targets.setdefault(resource.indirect_reference.idnum,set()).update(set(edit.get('text','')) & set('0123456789'))
    return targets


def prepare(data, edits):
    reader=PdfReader(io.BytesIO(data)); available=list(fonts(reader))
    targets=target_fonts(data,reader,edits)
    jobs=[]
    for bold in available:
        font_id=bold.resource.indirect_reference.idnum if getattr(bold.resource,'indirect_reference',None) else None
        if font_id not in targets:
            continue
        requested=targets[font_id]
        missing=sorted(c for c in requested if bold.path(c) is None)
        if not missing:
            continue
        model=pair_for(bold,available)
        jobs.append((bold,model,missing))
    if not jobs:
        return data,[]
    reports=[]
    with fitz.open(stream=data,filetype='pdf') as doc:
        for bold,model,missing in jobs:
            # Append to a private FontFile stream. Other PDF font resources may
            # reference the original bytes and must not be changed implicitly.
            raw, gids=add_paths(bold,{c:(model.make(c),model.width) for c in missing})
            descriptor=bold.descriptor.indirect_reference.idnum
            descendant=bold.desc.indirect_reference.idnum
            fontxref=bold.resource.indirect_reference.idnum
            # Clone descriptors and descendants because PDFs can share them.
            newdesc=doc.get_new_xref();doc.update_object(newdesc,doc.xref_object(descriptor))
            newcid=doc.get_new_xref();doc.update_object(newcid,doc.xref_object(descendant))
            doc.xref_set_key(fontxref,'DescendantFonts',f'[{newcid} 0 R]')
            doc.xref_set_key(newcid,'FontDescriptor',f'{newdesc} 0 R')
            doc.xref_set_key(newdesc,'FontFile2',new_stream(doc,raw))
            mapping=bold.codec.decode_map.copy()
            cidstart=max([len(bold.order), *(cid+1 for cid in mapping), *(cid+1 for cid in bold.codec.widths)])
            if cidstart+len(missing)>65535:
                reject('The original font has insufficient encoding space.')
            cidmap=bytearray(bold.cidmap if bold.cidmap is not None else b''.join(i.to_bytes(2,'big') for i in range(len(bold.order))))
            cidmap.extend(b'\0'*max(0,2*(cidstart+len(missing))-len(cidmap)))
            widths=bold.codec.widths.copy()
            for i,c in enumerate(missing):
                cid=bold.codec.reverse.get(c,cidstart+i)
                mapping[cid]=c
                cidmap[2*cid:2*cid+2]=gids[c].to_bytes(2,'big')
                widths[cid]=model.width
            doc.xref_set_key(newcid,'CIDToGIDMap',new_stream(doc,bytes(cidmap)))
            doc.xref_set_key(newcid,'W','['+' '.join(f'{cid} [{w:.6f}]' for cid,w in sorted(widths.items()))+']')
            doc.xref_set_key(fontxref,'ToUnicode',new_stream(doc,unicode_cmap(mapping)))
            previous=str(bold.resource.get('/PDFeditApproxDigits',''))
            doc.xref_set_key(fontxref,'PDFeditApproxDigits','('+''.join(sorted(set(previous+''.join(missing))))+')')
            reports.append(model.report(missing))
        result=doc.tobytes(garbage=4,deflate=True)
    # Adding glyphs must not change ANY existing page, including pages sharing
    # these font resources. The ordinary edit pipeline checks locality again.
    with fitz.open(stream=data,filetype='pdf') as a,fitz.open(stream=result,filetype='pdf') as b:
        for pa,pb in zip(a,b):
            scale=min(2,2200/max(pa.rect.width,pa.rect.height))
            if pa.get_pixmap(matrix=fitz.Matrix(scale,scale)).samples != pb.get_pixmap(matrix=fitz.Matrix(scale,scale)).samples:
                reject('Font supplementation changed existing text rendering. The edit was cancelled.')
    return result,reports


def sample(data, page, line):
    """Standalone labelled specimen; no statement pages or contents are copied."""
    reader=PdfReader(io.BytesIO(data)); available=list(fonts(reader))
    targets=target_fonts(data,reader,[dict(page=page,line=line)])
    candidates=[f for f in available if getattr(f.resource,'indirect_reference',None) and f.resource.indirect_reference.idnum in targets and f.name.lower().endswith('bold')]
    if len(candidates)!=1:
        reject('Select a numeric line using a single Bold font.')
    model=pair_for(candidates[0],available)
    bold=model.bold
    # Build specimen-only fonts with accessible cmaps; source glyphs are never
    # overwritten. A second face holds generated 0–4 for an honest comparison.
    missing=[c for c in '0123456789' if bold.path(c) is None]
    combined,_=add_paths(bold,{c:(model.make(c),model.width) for c in missing})
    generated,_=add_paths(bold,{c:(model.make(c),model.width) for c in '0123456789'})
    doc=fitz.open();p=doc.new_page(width=620,height=720)
    p.insert_font(fontname='Observed',fontbuffer=combined)
    p.insert_font(fontname='Generated',fontbuffer=generated)
    cjk=fitz.Font('china-s');p.insert_font(fontname='Labels',fontbuffer=cjk.buffer)
    def label(y,text,size=11):
        p.insert_text((38,y),text,fontname='Labels',fontsize=size,color=(.20,.28,.25))
    label(44,'PDFedit / 近似glyph测试页',22)
    label(70,'仅供glyph比较 · 生成glyph不是原字体 · 不包含原文档内容')
    label(96,'原字体：'+bold.name,10)
    label(116,'参考：'+model.regular.name,10)
    label(160,'原有glyph：'+''.join(model.common))
    p.insert_text((40,219),''.join(model.common),fontname='Observed',fontsize=60)
    label(250,'同一算法生成上述数字：请比较粗细、转角与字腔')
    p.insert_text((40,309),''.join(model.common),fontname='Generated',fontsize=60)
    label(345,'完整数字：原有字符保留，仅缺失字符使用近似轮廓')
    p.insert_text((40,402),'0123456789',fontname='Observed',fontsize=58)
    label(432,'本页补齐：'+(' '.join(missing) or '无')+'（Approximated）')
    label(470,'常用Font size / 背景检查（虚构样例）')
    p.draw_rect((32,484,588,554),color=None,fill=(.94,.93,1))
    p.insert_text((44,512),'0123456789',fontname='Observed',fontsize=14)
    p.insert_text((44,541),'5.67    8.95    6.58',fontname='Observed',fontsize=22)
    label(592,f'轮廓扩展参数：{model.strength} / 1000 em；校准轮廓差异：{model.error:.1%}')
    label(614,'差异值只比较已有数字，不代表缺失数字与原字体的相似度。')
    label(644,'生成方法：同族 Regular 轮廓扩展、数字宽高与位置拟合。')
    label(666,'此页为独立测试页；原 PDF 的页面、金额和其他内容均未修改。')
    doc.set_metadata({'title':'PDFedit approximate glyph specimen','subject':'Generated digit shapes, not original glyphs'})
    result=doc.tobytes(garbage=4,deflate=True);doc.close()
    return result
