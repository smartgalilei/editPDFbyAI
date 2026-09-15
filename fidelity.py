"""Strict text edits within existing PDF content streams.

The original font resource and graphics/text state are retained. No covering,
font substitution, synthetic bold, font size reduction, or background sampling.
pypdf's CMap decoder is pinned and exercised by the fixture suite.
"""
import difflib
import io
import math
import re
from copy import deepcopy
import pymupdf as fitz
from pypdf import PdfReader
from pypdf._cmap import get_encoding
from pypdf.generic import (ContentStream, DecodedStreamObject, ByteStringObject,
                           TextStringObject, ArrayObject, FloatObject)

class FidelityError(ValueError):
    pass

def fail(message):
    raise FidelityError('Cannot preserve the original layout: ' + message)

def raw_bytes(obj):
    if isinstance(obj, ByteStringObject):
        return bytes(obj)
    if isinstance(obj, TextStringObject):
        return obj.original_bytes
    return None

def edit_ranges(old,new):
    if len(old)!=len(new):
        return difflib.SequenceMatcher(a=old,b=new,autojunk=False).get_opcodes()
    # Repeated digits can make SequenceMatcher choose an insertion/deletion
    # rather than a same-position replacement. Equal-length edits keep slots.
    result=[];start=0
    for i in range(1,len(old)+1):
        if i==len(old) or (old[i]==new[i]) != (old[start]==new[start]):
            result.append(('equal' if old[start]==new[start] else 'replace',start,i,start,i))
            start=i
    return result

class FontCodec:
    def __init__(self, font):
        self.font = font
        self.used_codes = set()
        self.name = str(font.get('/BaseFont','')).lstrip('/')
        self.encoding, self.cmap = get_encoding(font)
        subtype = font.get('/Subtype')
        if subtype == '/Type0':
            if font.get('/Encoding') != '/Identity-H' or not self.cmap:
                fail('This composite font encoding is unsupported. Use the original editable source.')
            self.unit = 2
            self.decode_map = {}
            for k,v in self.cmap.items():
                if isinstance(k,str) and len(k)==1 and isinstance(v,str) and len(v)==1:
                    self.decode_map[ord(k)] = v
            descendant = font['/DescendantFonts'][0].get_object()
            self.default_width = float(descendant.get('/DW',1000))
            self.widths = {}
            w = descendant.get('/W',[])
            if hasattr(w,'get_object'): w=w.get_object()
            i = 0
            while i < len(w):
                start = int(w[i]); item = w[i+1]; i += 2
                if isinstance(item,ArrayObject):
                    self.widths.update({start+j:float(v) for j,v in enumerate(item)})
                else:
                    end = int(item); width = float(w[i]); i += 1
                    if end-start > 65535: fail('Invalid font width table.')
                    self.widths.update({j:width for j in range(start,end+1)})
            descriptor = descendant.get('/FontDescriptor',{})
        elif subtype in ('/Type1','/TrueType'):
            self.unit = 1
            self.decode_map = {}
            for code in range(256):
                try:
                    u = self.encoding.get(code,chr(code)) if isinstance(self.encoding,dict) else bytes([code]).decode(self.encoding)
                    u = self.cmap.get(u,u)
                    if isinstance(u,str) and len(u)==1:self.decode_map[code]=u
                except (UnicodeError,LookupError): pass
            first = int(font.get('/FirstChar',0))
            widths=font.get('/Widths',[])
            if hasattr(widths,'get_object'): widths=widths.get_object()
            self.widths = {first+i:float(w) for i,w in enumerate(widths)}
            self.default_width = None
            descriptor = font.get('/FontDescriptor',{})
        else:
            fail('Unsupported font type (such as Type3).')
        if hasattr(descriptor,'get_object'): descriptor = descriptor.get_object()
        self.face = None
        self.confirmed_codes=set()
        for key in ('/FontFile2','/FontFile3','/FontFile'):
            if key in descriptor:
                raw=descriptor[key].get_data()
                try:self.face = fitz.Font(fontbuffer=raw)
                except Exception:pass
                if key=='/FontFile2' and subtype=='/Type0':
                    # Embedded PDF subsets may omit an internal Unicode cmap.
                    # Confirm outlines using PDF CIDToGIDMap + glyf instead of
                    # requiring the character to have appeared on this page.
                    try:
                        from fontTools.ttLib import TTFont
                        tt=TTFont(io.BytesIO(raw),lazy=False)
                        mapping=descendant.get('/CIDToGIDMap','/Identity')
                        if hasattr(mapping,'get_object'):mapping=mapping.get_object()
                        mapped=mapping.get_data() if hasattr(mapping,'get_data') else None
                        if mapped is not None or str(mapping)=='/Identity':
                            order=tt.getGlyphOrder()
                            for cid in self.decode_map:
                                gid=cid if mapped is None else int.from_bytes(mapped[cid*2:cid*2+2],'big')
                                if 0<gid<len(order) and tt['glyf'][order[gid]].numberOfContours!=0:
                                    self.confirmed_codes.add(cid)
                        tt.close()
                    except (KeyError,ValueError,TypeError):pass
                break
        base = self.name.split('+')[-1]
        if self.face is None and base in fitz.Base14_fontnames:
            self.face = fitz.Font(base)
        self.reverse = {}
        for code,char in self.decode_map.items():
            self.reverse.setdefault(char,code)

    def decode(self,data):
        if len(data)%self.unit: fail('Invalid text encoding length.')
        result=[]
        for i in range(0,len(data),self.unit):
            code=int.from_bytes(data[i:i+self.unit],'big')
            char=self.decode_map.get(code)
            if char is None: fail('The text uses an unsupported glyph mapping.')
            result.append((char,code))
        return result

    def encode(self,text):
        codes=[]
        for char in text:
            code=self.reverse.get(char)
            if code is None or (code not in self.used_codes and code not in self.confirmed_codes and (self.face is None or not self.face.has_glyph(ord(char),fallback=False))):
                fail(f'The original font "{self.name}" has no verified glyph for "{char}". The font will not be substituted.')
            codes.append(code)
        return codes

    def width(self,code):
        if code in self.widths:return self.widths[code]
        if self.default_width is not None:return self.default_width
        if self.name in fitz.Base14_fontnames and self.face:
            return self.face.text_length(self.decode_map[code],fontsize=1000)
        fail('Cannot determine the original font character width.')

    def pack(self,codes):
        return ByteStringObject(b''.join(c.to_bytes(self.unit,'big') for c in codes))

def collect(page,reader):
    """Retain original kerning numbers and each text state's exact parameters."""
    stream=ContentStream(page.get_contents(),reader)
    fonts=page['/Resources'].get('/Font',{})
    current=dict(font=None,size=0,charspace=0,wordspace=0,mode=0,rise=0,hscale=100,ctm=(1,0,0,1,0,0),
                 fill=('DeviceGray',('0',)),stroke=('DeviceGray',('0',)),effects=())
    stack=[]; shows=[]; codecs={}; tm=fitz.Matrix(1,1)
    for index,(operands,operator) in enumerate(stream.operations):
        if operator==b'q': stack.append(current.copy())
        elif operator==b'Q':
            if stack: current=stack.pop()
        elif operator==b'cm':current['ctm']=tuple(fitz.Matrix(*map(float,operands))*fitz.Matrix(*current['ctm']))
        elif operator==b'BT':tm=fitz.Matrix(1,1)
        elif operator==b'Tm':tm=fitz.Matrix(*map(float,operands))
        elif operator==b'Ts':current['rise']=float(operands[0])
        elif operator==b'Tz':current['hscale']=float(operands[0])
        elif operator in (b'g',b'rg',b'k',b'G',b'RG',b'K'):
            key='fill' if operator.islower() else 'stroke'
            space={b'g':'DeviceGray',b'rg':'DeviceRGB',b'k':'DeviceCMYK'}[operator.lower()]
            current[key]=(space,tuple(str(v) for v in operands))
        elif operator in (b'cs',b'CS'):
            current['fill' if operator==b'cs' else 'stroke']=(str(operands[0]),())
        elif operator in (b'sc',b'scn',b'SC',b'SCN'):
            key='fill' if operator.islower() else 'stroke'
            current[key]=(current[key][0],tuple(str(v) for v in operands))
        elif operator==b'gs':current['effects']+=tuple(str(v) for v in operands)
        elif operator==b'Tf':current.update(font=str(operands[0]),size=float(operands[1]))
        elif operator==b'Tc':current['charspace']=float(operands[0])
        elif operator==b'Tw':current['wordspace']=float(operands[0])
        elif operator==b'Tr':current['mode']=int(operands[0])
        elif operator in (b'Tj',b'TJ',b"'",b'"'):
            if operator==b'"':current.update(wordspace=float(operands[0]),charspace=float(operands[1]))
            if current['font'] not in fonts or current['size']<=0:continue
            try:
                if current['font'] not in codecs:
                    codecs[current['font']]=FontCodec(fonts[current['font']].get_object())
                codec=codecs[current['font']]
                arr=operands[0] if operator==b'TJ' else [operands[-1]]
                chars=[]; codes=[]; gaps=[0.0]
                for part in arr:
                    raw=raw_bytes(part)
                    if raw is not None:
                        for char,code in codec.decode(raw):
                            chars.append(char);codes.append(code);gaps.append(0.0)
                    else:gaps[-1]+=float(part)
                if current['mode'] != 3: codec.used_codes.update(codes)
                shows.append(dict(index=index,operator=operator,operands=operands,codec=codec,
                                  text=''.join(chars),codes=codes,gaps=gaps,state=current.copy(),basis=tuple(tm*fitz.Matrix(*current['ctm']))))
            except (ValueError,TypeError,KeyError):
                continue # Unsupported runs are never guessed or rewritten.
    return stream,shows

def advance(show,codes):
    codec=show['codec'];state=show['state']
    return sum(codec.width(v)+1000*state['charspace']/state['size']+
        (1000*state['wordspace']/state['size'] if codec.unit==1 and v==32 else 0) for v in codes)

def write_changes(data,replacements):
    with fitz.open(stream=data,filetype='pdf') as doc:
        for n,(stream,shows,changes) in replacements.items():
            ops=[]
            for i,(args,operator) in enumerate(stream.operations):
                if i not in changes:
                    ops.append((args,operator));continue
                change=changes[i];show,arr=change[:2]
                if operator==b"'":ops.append(([],b'T*'))
                elif operator==b'"':
                    ops.extend([([args[0]],b'Tw'),([args[1]],b'Tc'),([],b'T*')])
                if isinstance(arr,dict):
                    ops.extend(arr['operations']);continue
                if len(change)>2:ops.append(([FloatObject(change[2])],b'Ts'))
                ops.append(([arr],b'TJ'))
                if len(change)>2:ops.append(([FloatObject(show['state']['rise'])],b'Ts'))
            # Do not mutate the collected stream: multiple localization probes
            # must all start with exactly the same original operations.
            output=ContentStream(None,stream.pdf)
            output.operations=ops
            xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
            doc.update_stream(xref,output.get_data())
            doc[n-1].set_contents(xref)
        return doc.tobytes(garbage=4,deflate=True)

def candidate_at_target(data,edit,stream,shows,candidate):
    """Locate original glyphs without attempting the user's replacement.

    A temporary memory-only probe substitutes each selected glyph with its
    advance. Text after it stays put. No replacement font, width or alignment
    decision is needed to identify the source object.
    """
    changes={};length=len(edit['line']['text'])
    for show,start,end in candidate:
        if show['state']['mode']>=3:
            fail('Hidden or clipping text cannot be located by visible position.')
        lo=max(0,-start);hi=min(len(show['codes']),length-start)
        if hi<=lo:continue
        codec=show['codec'];arr=ArrayObject()
        for i,code in enumerate(show['codes']):
            if show['gaps'][i]:arr.append(FloatObject(show['gaps'][i]))
            if lo<=i<hi:arr.append(FloatObject(-advance(show,[code])))
            else:arr.append(codec.pack([code]))
        if show['gaps'][-1]:arr.append(FloatObject(show['gaps'][-1]))
        changes[show['index']]=(show,arr)
    probe=write_changes(data,{edit['page']:(stream,shows,changes)})
    check_outside_regions(data,probe,[dict(page=edit['page'],line=edit['line'],text='')])

def recolor(edit,segments,changes):
    """Change only selected character paints; keep encoded glyphs and advances."""
    a,b=edit['color_range'];rgb=[FloatObject(v) for v in edit['color']]
    for show,start,end in segments:
        lo=max(0,a-start);hi=min(len(show['codes']),b-start)
        if hi<=lo:continue
        if show['state']['mode']>=3 or show['index'] in changes:
            fail('Hidden or clipping text and repeated edits to the same object are unsupported.')
        operations=[]
        for left,right,selected in ((0,lo,False),(lo,hi,True),(hi,len(show['codes']),False)):
            if left==right:continue
            arr=ArrayObject()
            for i in range(left,right):
                if show['gaps'][i]:arr.append(FloatObject(show['gaps'][i]))
                arr.append(show['codec'].pack([show['codes'][i]]))
            if selected:operations.extend([([],b'q'),(rgb,b'rg'),(rgb,b'RG')])
            operations.append(([arr],b'TJ'))
            if selected:operations.append(([],b'Q'))
        if show['gaps'][-1]:operations.append(([ArrayObject([FloatObject(show['gaps'][-1])])],b'TJ'))
        changes[show['index']]=(show,dict(operations=operations))

def aligned(data,edit,segments,changes):
    """Translate native runs, restoring text advance and rise after each show."""
    line=edit['line'];old=line['text'];new=edit['text']
    shows=[s[0] for s in segments];first=shows[0];codec=first['codec']
    if ''.join(s['text'] for s in shows)!=old:
        fail('The target line shares an object with other text and cannot be moved independently.')
    if any(s['index'] in changes or s['state']['mode']>=3 for s in shows):
        fail('The target includes repeated edits, hidden text or clipping text.')
    moving=old==new
    if not moving and any(s['state']!=first['state'] for s in shows):
        fail('Replacement spans different styles and cannot be merged. Try an alignment-only change.')
    widths=[advance(s,s['codes'])-sum(s['gaps']) for s in shows]
    total=sum(widths)
    if total<=0:fail('Cannot determine the original line width.')
    codes=codec.encode(new) if not moving else None
    new_width=advance(first,codes) if not moving else total
    rect=fitz.Rect(line['bbox']);width=rect.width*new_width/total
    with fitz.open(stream=data,filetype='pdf') as doc:
        p=doc[edit['page']-1];bounds=p.rect*p.derotation_matrix
        box=line.get('box','original')
        target=bounds if box=='page' else rect if box=='original' else fitz.Rect(box)
        horizontal=line.get('align','original');vertical=line.get('valign','baseline')
        x={'original':rect.x0,'left':target.x0,'center':(target.x0+target.x1-width)/2,'right':target.x1-width}[horizontal]
        y={'baseline':rect.y0,'top':target.y0,'middle':(target.y0+target.y1-rect.height)/2,'bottom':target.y1-rect.height}[vertical]
        destination=fitz.Rect(x,y,x+width,y+rect.height)
        if not (bounds+(-.01,-.01,.01,.01)).contains(destination):fail('Aligned text would extend beyond the page.')
        if box!='original' and not (target+(-.01,-.01,.01,.01)).contains(destination):fail('The text does not fit. Enlarge the target area.')
        for block in p.get_text('dict')['blocks']:
            for other in block.get('lines',[]):
                r=fitz.Rect(other['bbox'])
                if tuple(r)==tuple(rect) and ''.join(t['text'] for t in other['spans'])==old:continue
                if destination.intersects(r):fail('Aligned text would overlap other text. Adjust the target area.')
        for drawing in p.get_drawings():
            if drawing.get('color') is None:continue
            for item in drawing['items']:
                edges=[]
                if item[0]=='l':edges=[(item[1],item[2])]
                elif item[0]=='re':
                    r=item[1];edges=[(r.tl,r.bl),(r.tr,r.br),(r.tl,r.tr),(r.bl,r.br)]
                for a,b in edges:
                    r=fitz.Rect(min(a.x,b.x)-.1,min(a.y,b.y)-.1,max(a.x,b.x)+.1,max(a.y,b.y)+.1)
                    if destination.intersects(r) and not rect.intersects(r):fail('Aligned text would cross a table boundary. The edit was cancelled.')
        for i,show in enumerate(shows):
            basis=fitz.Matrix(*show['basis'])*p.transformation_matrix
            # Only horizontal text is accepted by the public engine. Reject
            # singular transforms rather than guessing a translation.
            h=show['state']['hscale']/100
            a,b,c,d=basis.a*h,basis.b*h,basis.c,basis.d
            det=a*d-b*c
            if abs(det)<1e-9:fail('The text transformation matrix is not invertible.')
            dx=x-rect.x0;dy=y-rect.y0
            u=(d*dx-c*dy)/det;v=(-b*dx+a*dy)/det
            shift=u*1000/show['state']['size']
            if moving:
                arr=ArrayObject([FloatObject(-shift)])
                for j,code in enumerate(show['codes']):
                    if show['gaps'][j]:arr.append(FloatObject(show['gaps'][j]))
                    arr.append(show['codec'].pack([code]))
                arr.extend([FloatObject(show['gaps'][-1]),FloatObject(shift)])
            elif i==0:
                arr=ArrayObject([FloatObject(-shift),codec.pack(codes),FloatObject(shift+new_width-widths[0])])
            else:
                changes[show['index']]=(show,ArrayObject([FloatObject(-widths[i])]))
                continue
            changes[show['index']]=(show,arr,show['state']['rise']+v)
    edit['destination_bbox']=list(destination)


def native_edits(data,edits,_selection=None,approximate_digits=False):
    """edits: page number, original line text/rect, replacement. Atomic bytes out."""
    edits=deepcopy(edits)
    reports=[]
    if approximate_digits:
        from approximate import prepare
        data,reports=prepare(data,edits)
    reader=PdfReader(io.BytesIO(data),strict=False)
    replacements={}; summaries=[]
    for edit in edits:
        n=edit['page']; old=edit['line']['text']; new=edit['text']
        if new==old and 'color' not in edit and not edit['line'].get('layout') and edit['line'].get('align','original')=='original':
            summaries.append(f'Page {n}: text is unchanged; no edit needed.');continue
        if n not in replacements:
            stream,shows=collect(reader.pages[n-1],reader)
            replacements[n]=(stream,shows,{})
        stream,shows,changes=replacements[n]
        # A line can be one operand or several consecutive styled text runs.
        candidates=[]
        for show in shows:
            start=0
            while old in show['text'][start:]:
                offset=show['text'].find(old,start)
                candidates.append([(show,-offset,len(show['text'])-offset)])
                start=offset+len(old)
        for i in range(len(shows)):
            joined='';segments=[]
            for show in shows[i:i+32]:
                start=len(joined);joined+=show['text']
                segments.append((show,start,len(joined)))
                if joined==old:
                    if len(segments)>1:candidates.append(segments.copy())
                    break
                if not old.startswith(joined):break
        if not candidates:
            fail(f'No matching text object on page {n}. It may use complex encoding, nested objects or different space representations.')
        if len(candidates)>32:
            fail('Too many repeated text candidates. Extract the target page into a separate PDF first.')
        selected=(_selection or {}).get((n,edit['line']['id']))
        if selected is None and len(candidates)>1:
            # Find the source object BEFORE checking replacement feasibility.
            # A valid target with a missing glyph / insufficient space must not
            # be discarded merely because the requested edit cannot succeed.
            valid=[];errors=[]
            for candidate_index in range(len(candidates)):
                try:
                    candidate_at_target(data,edit,stream,shows,candidates[candidate_index])
                    valid.append(candidate_index)
                except FidelityError as error:
                    errors.append(str(error))
            if len(valid)!=1:
                if not valid and errors and (len(set(errors))==1 or all('glyph' in e for e in errors)):
                    raise FidelityError(errors[0])
                fail(f'Page {n}, {edit["line"]["id"]}: {len(valid)} of {len(candidates)} candidates match the original position. Text may overlap or coordinates may not match.')
            selected=valid[0]
        candidates=[candidates[0 if selected is None else selected]]
        if 'color' in edit:
            recolor(edit,candidates[0],changes)
            continue
        if edit['line'].get('layout') or edit['line'].get('align','original')!='original':
            aligned(data,edit,candidates[0],changes)
            summaries.append(f'Page {n}: {old} → {new} (aligned to target; font size and background preserved)')
            continue
        by_show={}
        for tag,a,b,c,d in edit_ranges(old,new):
            if tag=='equal':continue
            segments=[seg for seg in candidates[0] if seg[1]<=a and b<=seg[2]]
            if len(segments)==1:
                parts=[(segments[0],(a,b,c,d))]
            elif b-a==d-c and b>a:
                # Equal-length changes can span separately drawn characters;
                # each character keeps its original run's font and position.
                parts=[]
                for segment in candidates[0]:
                    lo=max(a,segment[1]);hi=min(b,segment[2])
                    if lo<hi:parts.append((segment,(lo,hi,c+lo-a,c+hi-a)))
                if sum(part[1]-part[0] for _,part in parts)!=b-a:
                    fail('Split text objects do not cover the full edit range.')
            else:
                fail('The length change spans multiple style objects. Narrow the edit range.')
            for segment,part in parts:
                show,start,end=segment
                a,b,c,d=part
                a-=start;b-=start
                if show['state']['mode']>=3:fail('Hidden text or clipping paths cannot be safely rewritten.')
                if show['index'] in changes:fail('Multiple edits affect the same text object. Combine them and retry.')
                code=show['codec'];state=show['state'];codes=show['codes'];gaps=show['gaps']
                added=code.encode(new[c:d])
                removed_advance=advance(show,codes[a:b])-sum(gaps[a+1:b])
                new_advance=advance(show,added)
                kept_gaps=gaps[a+1:b] if b-a==len(added) else []
                new_advance-=sum(kept_gaps)
                if new_advance>removed_advance+0.5:
                    fail('The new text exceeds the original area. For longer numbers, request right alignment with enough free space to the left.')
                by_show.setdefault(show['index'],(show,[]))[1].append((a,b,added,new_advance-removed_advance,kept_gaps))
        for index,(show,patches) in by_show.items():
            code=show['codec'];codes=show['codes'];gaps=show['gaps']
            output=ArrayObject();cursor=0
            def emit_original(a,b):
                for i in range(a,b):
                    if gaps[i]:output.append(FloatObject(gaps[i]))
                    output.append(code.pack([codes[i]]))
            for a,b,added,compensation,kept_gaps in patches:
                emit_original(cursor,a)
                if gaps[a]:output.append(FloatObject(gaps[a]))
                for i,v in enumerate(added):
                    if i and kept_gaps and kept_gaps[i-1]:output.append(FloatObject(kept_gaps[i-1]))
                    output.append(code.pack([v]))
                if abs(compensation)>0.00001:output.append(FloatObject(compensation))
                cursor=b
            emit_original(cursor,len(codes))
            if gaps[-1]:output.append(FloatObject(gaps[-1]))
            changes[index]=(show,output)
        summaries.append(f'Page {n}: {old} → {new} (original font, size, weight and background preserved)')
    positioned=[e for e in edits if 'destination_bbox' in e]
    for i,e in enumerate(positioned):
        for other in positioned[i+1:]:
            if e['page']==other['page'] and fitz.Rect(e['destination_bbox']).intersects(fitz.Rect(other['destination_bbox'])):
                fail('Aligned target areas overlap. The entire plan was cancelled.')
    result=write_changes(data,replacements)
    check_outside_regions(data,result,edits)
    with fitz.open(stream=result,filetype='pdf') as doc:
        for e in edits:
            if 'destination_bbox' not in e:continue
            old=fitz.Rect(e['destination_bbox'])
            matches=[line for block in doc[e['page']-1].get_text('dict')['blocks'] for line in block.get('lines',[])
                     if ''.join(s['text'] for s in line['spans'])==e['text']
                     and all(abs(a-b)<.3 for a,b in zip(line['bbox'],old))]
            if len(matches)!=1:fail('The aligned text position failed validation. The edit was cancelled.')
    for report in reports:
        summaries.append(f'Approximated digits {report["generated"]}: {report["font"]}; reference {report["reference"]}. Generated glyphs are approximations; existing glyphs and backgrounds are preserved.')
    return result,summaries

def check_outside_regions(before,after,edits):
    """Reject changes to any rendered pixel outside selected line bounds (+4pt).

This also catches a matching string in the wrong place, shared resources,
advance errors affecting later lines, or accidental loss of graphics state.
"""
    with fitz.open(stream=before,filetype='pdf') as a,fitz.open(stream=after,filetype='pdf') as b:
        for n in sorted({e['page'] for e in edits}):
            p=a[n-1];q=b[n-1]
            scale=min(2.0,2200/max(p.rect.width,p.rect.height))
            mat=fitz.Matrix(scale,scale)
            pix=p.get_pixmap(matrix=mat,alpha=False);other=q.get_pixmap(matrix=mat,alpha=False)
            if (pix.width,pix.height)!=(other.width,other.height):fail('Page dimensions changed unexpectedly.')
            left=pix.samples;right=other.samples
            if left==right:
                if any(e['text']!=e['line']['text'] for e in edits if e['page']==n):
                    fail('No visible change was detected; the original font may lack a glyph.')
                continue
            regions=[]
            for e in edits:
                if e['page']!=n:continue
                for region in [e['line']['bbox']]+([e['destination_bbox']] if 'destination_bbox' in e else []):
                    rect=(fitz.Rect(region)+(-4,-4,4,4))*p.rotation_matrix*mat
                    regions.append((max(0,math.floor(rect.x0)),max(0,math.floor(rect.y0)),
                                    min(pix.width,math.ceil(rect.x1)),min(pix.height,math.ceil(rect.y1))))
            for y in range(pix.height):
                ranges=sorted((r[0],r[2]) for r in regions if r[1]<=y<r[3])
                cursor=0;start=y*pix.stride
                for x0,x1 in ranges+[(pix.width,pix.width)]:
                    if x0>cursor and left[start+cursor*3:start+x0*3]!=right[start+cursor*3:start+x0*3]:
                        fail('Visual changes were detected outside the target text. The entire plan was cancelled.')
                    cursor=max(cursor,x1)
