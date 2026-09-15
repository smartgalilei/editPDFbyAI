"""Local PDF operations. Plans produce new bytes, never mutate the input file."""
import math
import re
import pymupdf as fitz
from fidelity import native_edits

fitz.TOOLS.set_small_glyph_heights(True)
MAX_BYTES = 40 * 1024 * 1024
FALLBACK = fitz.Font("china-s")

def attach_font(page):
    names = {f[4] for f in page.get_fonts()}
    i = 0
    while f"PDFeditCJK{i}" in names:
        i += 1
    name = f"PDFeditCJK{i}"
    page.insert_font(fontname=name, fontbuffer=FALLBACK.buffer)
    return name


def open_pdf(data):
    if len(data) > MAX_BYTES:
        raise ValueError('The file exceeds the 40 MB limit.')
    doc = fitz.open(stream=data, filetype='pdf')
    if doc.needs_pass:
        doc.close()
        raise ValueError('Decrypt the PDF on your device before opening it.')
    if not 0 < len(doc) <= 300:
        doc.close()
        raise ValueError('PDFs must contain 1-300 pages.')
    return doc

def lines(page):
    result = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            spans = line['spans']
            value = ''.join(s['text'] for s in spans)
            if value.strip():
                s = spans[0]
                result.append(dict(id=f'l{len(result)+1}', text=value, bbox=list(line['bbox']),
                                   size=s['size'], color=s['color'], origin=list(s['origin']),
                                   horizontal=list(line['dir']) == [1.0, 0.0]))
    return result

def background_areas(page):
    result=[]
    for drawing in page.get_drawings():
        if drawing.get('fill') is not None and len(drawing['items'])==1 and drawing['items'][0][0]=='re':
            result.append(dict(bbox=list(drawing['rect']),color='#'+''.join(f'{round(c*255):02X}' for c in drawing['fill'][:3])))
            if len(result)>=200:break
    return result

def describe(data):
    with open_pdf(data) as doc:
        return [dict(page=i+1, width=p.rect.width, height=p.rect.height,
                     rotation=p.rotation, unrotatedWidth=(p.rect*p.derotation_matrix).width,
                     unrotatedHeight=(p.rect*p.derotation_matrix).height, backgrounds=background_areas(p), lines=lines(p)) for i, p in enumerate(doc)]

def approximate_fonts(data):
    if not data:
        return []
    found=set()
    with open_pdf(data) as doc:
        for p in doc:
            for font in p.get_fonts():
                kind,chars=doc.xref_get_key(font[0],'PDFeditApproxDigits')
                if kind=='string' and chars:
                    found.add(f'{font[3]}：{chars}')
    return sorted(found)

def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer between {low} and {high}.')
    return value

def string(value, label, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label} must not be empty or exceed {maximum} characters.')
    return value

def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be between {low} and {high}.')
    return value

def color(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
        raise ValueError('Use a six-digit hexadecimal color, such as #336699.')
    return tuple(int(value[i:i+2],16)/255 for i in (1,3,5))

def render(data, page):
    with open_pdf(data) as doc:
        integer(page, 1, len(doc), 'Page number')
        p = doc[page-1]
        scale = min(1.5, 1600 / max(p.rect.width, p.rect.height))
        return p.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png')

def execute(data, operations, approximate_digits=False):
    if type(approximate_digits) is not bool:
        raise ValueError('The approximate digits setting must be a boolean.')
    if not isinstance(operations, list) or not 1 <= len(operations) <= 60:
        raise ValueError('Each plan must contain 1-60 operations.')
    schemas = {
        'color_text': {'type','page','line','color'},
        'background_color': {'type','page','rect','color'},
        'align_text': {'type','page','line'},
        'replace_text': {'type','page','line','text'}, 'redact_text': {'type','page','line'},
        'highlight': {'type','page','line'}, 'add_text': {'type','page','text','rect','size'},
        'rotate': {'type','page','degrees'}, 'delete_pages': {'type','pages'},
        'reorder_pages': {'type','pages'},
    }
    with open_pdf(data) as doc:
        lookup = {i+1: {l['id']: l for l in lines(p)} for i, p in enumerate(doc)}
        seen, tasks, structure, summaries = set(), [], None, []
        for op in operations:
            if not isinstance(op, dict) or op.get('type') not in schemas:
                raise ValueError('The plan contains an unsupported operation.')
            kind = op['type']
            expected=schemas[kind] | (set(op)&{'align','valign','box'} if kind in ('replace_text','align_text') else set())
            if kind=='color_text':expected |= set(op)&{'text','occurrence'}
            if set(op) != expected:
                raise ValueError(f'{kind} has missing or unknown parameters.')
            if kind in ('delete_pages','reorder_pages'):
                if structure:
                    raise ValueError('A plan can contain only one page deletion or reorder operation.')
                pages = op['pages']
                if not isinstance(pages,list) or not pages:
                    raise ValueError('The page list must not be empty.')
                for n in pages:
                    integer(n,1,len(doc),'Page number')
                if len(set(pages)) != len(pages):
                    raise ValueError('The page list must not contain duplicates.')
                if kind == 'delete_pages' and len(pages) == len(doc):
                    raise ValueError('Cannot delete every page.')
                if kind == 'reorder_pages' and sorted(pages) != list(range(1,len(doc)+1)):
                    raise ValueError('Reordering must include every page exactly once.')
                structure = op
                summaries.append(('Delete pages ' if kind == 'delete_pages' else 'Reorder pages to ') + ', '.join(map(str,pages)))
                continue
            n = integer(op['page'],1,len(doc),'Page number')
            page = doc[n-1]
            if kind in ('replace_text','align_text','color_text','redact_text','highlight'):
                line = lookup[n].get(op['line']) if isinstance(op['line'],str) else None
                if not line:
                    raise ValueError(f'Target text line not found on page {n}.')
                if (n,op['line']) in seen:
                    raise ValueError('Only one operation per text line is allowed in a plan.')
                seen.add((n,op['line']))
                rect = fitz.Rect(line['bbox'])
                if not line['horizontal']:
                    raise ValueError('Editing vertical or angled text is unsupported.')
                if kind=='color_text':
                    rgb=color(op['color'])
                    target=op.get('text',line['text'])
                    string(target,'Target text')
                    positions=[i for i in range(len(line['text'])) if line['text'].startswith(target,i)]
                    if not positions:raise ValueError('The specified text fragment was not found in this line.')
                    if len(positions)>1 and 'occurrence' not in op:
                        raise ValueError('The text fragment repeats. Specify an occurrence or select the whole line.')
                    occurrence=integer(op.get('occurrence',1),1,len(positions),'Occurrence')
                    start=positions[occurrence-1]
                    line=dict(line,color_range=(start,start+len(target)))
                    tasks.append((kind,n,rect,line,rgb,None))
                    summaries.append(f'Page {n}: recolor occurrence {occurrence} of "{target}" to {op["color"]}')
                elif kind in ('replace_text','align_text'):

                    align=op.get('align','original')
                    if align not in ('original','left','center','right'):
                        raise ValueError('Horizontal alignment must be original, left, center or right.')
                    valign=op.get('valign','baseline')
                    if valign not in ('baseline','top','middle','bottom'):
                        raise ValueError('Vertical alignment must be baseline, top, middle or bottom.')
                    box=op.get('box','original')
                    if isinstance(box,list):
                        if len(box)!=4:raise ValueError('The target area requires four coordinates.')
                        for v in box:number(v,0,20000,'Coordinate')
                        area=fitz.Rect(box)
                        if area.is_empty or not (page.rect*page.derotation_matrix).contains(area):
                            raise ValueError('The target area is empty or outside the page.')
                    elif box not in ('original','page'):
                        raise ValueError('Alignment reference must be original, page or rectangle coordinates.')
                    line=dict(line,align=align,valign=valign,box=box,layout=kind=='align_text' or align!='original' or valign!='baseline' or box!='original')
                    value = line['text'] if kind=='align_text' else string(op['text'],'Replacement text')
                    if '\n' in value or '\r' in value:
                        raise ValueError('Replacement text must be a single line. Edit paragraphs line by line.')
                    tasks.append(('replace_text',n,rect,line,value,line['size']))
                    action=f'Move "{value}"' if kind=='align_text' else f'{line["text"]} → {value}'
                    layout_note=''
                    if line['layout']:
                        h={'original':'keep horizontal position','left':'left aligned','center':'horizontally centered','right':'right aligned'}[align]
                        v={'baseline':'keep baseline','top':'top aligned','middle':'vertically centered','bottom':'bottom aligned'}[valign]
                        reference='custom area '+str(box) if isinstance(box,list) else {'original':'original text area','page':'whole page'}[box]
                        layout_note=f'; relative to {reference}: {h}, {v}'
                    summaries.append(f'Page {n}: {action} (original font, size, weight and background preserved)'+layout_note)
                else:
                    tasks.append((kind,n,rect,line,None,None))
                    summaries.append(f'Page {n}: ' + ('Delete text "' if kind == 'redact_text' else 'Highlight "') + line['text'] + '"')
            elif kind=='background_color':
                rgb=color(op['color']);r=op['rect']
                if not isinstance(r,list) or len(r)!=4:raise ValueError('Background area must be [x0,y0,x1,y1].')
                for v in r:number(v,0,20000,'Coordinate')
                rect=fitz.Rect(r)
                if rect.is_empty or not (page.rect*page.derotation_matrix).contains(rect):
                    raise ValueError('The background area is empty or outside the page.')
                tasks.append((kind,n,rect,None,rgb,None))
                summaries.append(f'Page {n}: set background color in {r} to {op["color"]}')
            elif kind == 'add_text':
                value = string(op['text'],'New text')
                size = number(op['size'],7,72,'Font size')
                r = op['rect']
                if not isinstance(r,list) or len(r)!=4:
                    raise ValueError('Text area must be [x0,y0,x1,y1].')
                for v in r:
                    number(v,0,20000,'Coordinate')
                rect = fitz.Rect(r)
                bounds = page.rect * page.derotation_matrix
                if rect.is_empty or not bounds.contains(rect):
                    raise ValueError('The new text area extends beyond the page.')
                tasks.append((kind,n,rect,None,value,size))
                summaries.append(f'Page {n}: add {value}')
            elif kind == 'rotate':
                integer(op['degrees'],90,270,'Rotation')
                if op['degrees'] not in (90,180,270):
                    raise ValueError('Rotation must be 90, 180 or 270 degrees.')
                tasks.append((kind,n,None,None,op['degrees'],None))
                summaries.append(f'Rotate page {n} clockwise by {op["degrees"]} degrees')
        return apply_tasks(data,tasks,structure,summaries,approximate_digits)

def apply_tasks(data,tasks,structure,summaries,approximate_digits=False):
    edits=[dict(page=n,line=line,text=value) for kind,n,rect,line,value,size in tasks if kind=='replace_text']
    edits.extend(dict(page=n,line=line,text=line['text'],color=value,color_range=line['color_range']) for kind,n,rect,line,value,size in tasks if kind=='color_text')
    if edits:
        data,details=native_edits(data,edits,approximate_digits=approximate_digits)
        generated=[s for s in details if s.startswith('Approximated')]
        if generated:
            summaries=[s.replace(' (original font, size, weight and background preserved)',' (existing glyphs and background preserved; missing digits approximated)') for s in summaries]
            summaries.extend(generated)
    from colors import backgrounds
    data=backgrounds(data,[dict(page=n,rect=list(rect),color=value) for kind,n,rect,line,value,size in tasks if kind=='background_color'])
    with open_pdf(data) as doc:
        for n in {t[1] for t in tasks if t[0]=='redact_text'}:
            if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in doc[n-1].annots()):
                raise ValueError('The page contains pending redaction annotations. Resolve them before editing.')
        for kind,n,rect,line,value,size in tasks:
            if kind=='redact_text':
                doc[n-1].add_redact_annot(rect, fill=False, cross_out=False)
        for n in {t[1] for t in tasks if t[0]=='redact_text'}:
            doc[n-1].apply_redactions(images=0, graphics=0)
        for kind,n,rect,line,value,size in tasks:
            page = doc[n-1]
            if kind == 'highlight':
                page.add_highlight_annot(rect)
            elif kind == 'add_text':
                result = page.insert_textbox(rect,value,fontname=attach_font(page),fontsize=size)
                if result < 0:
                    raise ValueError(f'New text does not fit on page {n}. Enlarge the area or shorten the text.')
            elif kind == 'rotate':
                page.set_rotation((page.rotation+value)%360)
        if structure:
            if structure['type']=='delete_pages':
                doc.delete_pages([n-1 for n in structure['pages']])
            else:
                doc.select([n-1 for n in structure['pages']])
        return doc.tobytes(garbage=4,deflate=True), summaries

def demo(language="en"):
    if language == 'en':
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((54,65),'editPDFbyAI / Sample document',fontsize=11,color=(.22,.4,.36))
        for y,text,size in [(115,'Project proposal',26),(165,'Project: Document workspace',14),
                            (200,'Delivery date: October 1, 2026',14),(235,'Budget: USD 50,000',14),
                            (290,'Make document editing simple.',13),
                            (320,'Describe a change, preview it, then apply.',13),
                            (400,'Fictional sample. No real business data.',11)]:
            p.insert_text((54,y),text,fontsize=size)
        p.draw_line((54,365),(540,365),color=(.8,.83,.81))
        p=doc.new_page()
        p.insert_text((54,90),'Next steps',fontsize=25)
        p.insert_text((54,150),'Confirm the scope, review the changes, then export.',fontsize=14)
        result=doc.tobytes();doc.close();return result
    doc = fitz.open()
    p = doc.new_page()
    demo_font = attach_font(p)
    p.insert_text((54,65),'PDFedit / Sample document',fontsize=11,color=(.22,.4,.36))
    p.insert_text((54,115),'项目合作提案',fontname=demo_font,fontsize=26)
    p.insert_text((54,165),'项目名称：智能文档工作台',fontname=demo_font,fontsize=14)
    p.insert_text((54,200),'交付日期：2026年10月01日',fontname=demo_font,fontsize=14)
    p.insert_text((54,235),'项目预算：人民币 50,000 元',fontname=demo_font,fontsize=14)
    p.insert_text((54,290),'我们希望让每一份文档的修改都变得简单。',fontname=demo_font,fontsize=13)
    p.insert_text((54,320),'用自然语言描述修改，预览后再应用。',fontname=demo_font,fontsize=13)
    p.draw_line((54,365),(540,365),color=(.8,.83,.81))
    p.insert_text((54,400),'备注：这是一份虚构示例，不含真实业务数据。',fontname=demo_font,fontsize=11)
    p = doc.new_page()
    demo_font = attach_font(p)
    p.insert_text((54,90),'下一步',fontname=demo_font,fontsize=25)
    p.insert_text((54,150),'确认范围，完成评审，然后导出 PDF。',fontname=demo_font,fontsize=14)
    doc.subset_fonts()
    result = doc.tobytes()
    doc.close()
    return result
