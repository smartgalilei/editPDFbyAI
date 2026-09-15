"""Local, bounded background paints, inserted beneath existing foregrounds."""
import io
import pymupdf as fitz
from pypdf import PdfReader
from pypdf.generic import ContentStream,FloatObject
from fidelity import check_outside_regions


def numbers(values):return [FloatObject(v) for v in values]


def background(data,edit):
    reader=PdfReader(io.BytesIO(data));n=edit['page'];rect=fitz.Rect(edit['rect'])
    stream=ContentStream(reader.pages[n-1].get_contents(),reader)
    with fitz.open(stream=data,filetype='pdf') as doc:
        page=doc[n-1];drawings=page.get_drawings();log=page.get_bboxlog()
        candidates=[d for d in drawings if d.get('fill') is not None and (d['rect']+(-.001,-.001,.001,.001)).contains(rect)
                    and len(d['items'])==1 and d['items'][0][0]=='re']
        chosen=max(candidates,key=lambda d:d['seqno']) if candidates else None
        if any((kind=='fill-shade' or (kind=='fill-image' and chosen is None)) and rect.intersects(fitz.Rect(box)) for kind,box in log):
            raise ValueError('The selected area contains images or gradients; recoloring is unsupported.')
        if chosen:
            if chosen.get('fill_opacity')!=1 or chosen.get('layer'):
                raise ValueError('Transparent or optional-layer backgrounds are unsupported. Choose an opaque solid background.')
            if any(kind.endswith('text') and rect.intersects(fitz.Rect(box)) for kind,box in log[:chosen['seqno']]):
                raise ValueError('This shape is above the text and cannot be identified as a background.')
        elif any(rect.intersects(d['rect']) and d.get('fill') is not None for d in drawings):
            raise ValueError('The area crosses multiple backgrounds or non-rectangular shapes. Choose an area within one solid rectangle.')
        # Match the visible rectangle to a top-level native rectangle paint.
        current=fitz.Matrix(1,1);stack=[];path=[];matches=[];safe=True
        states=reader.pages[n-1]['/Resources'].get('/ExtGState',{})
        if hasattr(states,'get_object'):states=states.get_object()
        for i,(args,op) in enumerate(stream.operations):
            if op==b'q':stack.append((fitz.Matrix(current),safe))
            elif op==b'Q':
                if stack:current,safe=stack.pop()
            elif op in (b'W',b'W*'):safe=False
            elif op==b'gs':
                state=states.get(args[0],{})
                if hasattr(state,'get_object'):state=state.get_object()
                if str(state.get('/BM','/Normal')) not in ('/Normal','/Compatible') or str(state.get('/SMask','/None'))!='/None':safe=False
            elif op==b'cm':current=fitz.Matrix(*map(float,args))*current
            elif op in (b'm',b'l',b'c',b'v',b'y',b'h',b're'):
                if not (op==b'h' and len(path)==1 and path[0][1]==b're'):
                    path.append((args,op,fitz.Matrix(current)))
            elif op in (b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'S',b's',b'n'):
                if chosen and op in (b'f',b'F',b'f*',b'B',b'B*') and len(path)==1 and path[0][1]==b're':
                    a,_,matrix=path[0];x,y,w,h=map(float,a)
                    actual=fitz.Rect(x,y,x+w,y+h).normalize()*matrix*page.transformation_matrix
                    if all(abs(a-b)<.01 for a,b in zip(actual,chosen['rect'])):
                        matches.append((i,fitz.Matrix(current),path[0][:2],safe))
                path=[]
        if chosen and len(matches)!=1:
            raise ValueError('The background rectangle cannot be uniquely located; it may be nested or duplicated.')
        anchor,matrix,pathop,safe=matches[0] if chosen else (-1,fitz.Matrix(1,1),None,True)
        if not safe:raise ValueError('Background clipping, blend modes or transparency masks prevent recoloring.')
        inv=~matrix
        if abs(matrix.a*matrix.d-matrix.b*matrix.c)<1e-9:raise ValueError('The background transformation matrix is not invertible.')
        pdfrect=rect*~page.transformation_matrix
        paint=[([],b'q'),(numbers(inv),b'cm'),(numbers(edit['color']),b'rg'),
               (numbers([pdfrect.x0,pdfrect.y0,pdfrect.width,pdfrect.height]),b're'),([],b'f'),([],b'Q')]
        ops=[]
        if not chosen:ops.extend(paint)
        for i,(args,op) in enumerate(stream.operations):
            if i!=anchor:ops.append((args,op));continue
            if all(abs(a-b)<.001 for a,b in zip(rect,chosen['rect'])):
                ops.extend([([],b'q'),(numbers(edit['color']),b'rg'),(args,op),([],b'Q')])
            elif op in (b'B',b'B*'):
                # Repaint the original stroke once, above the new background.
                ops.append((args,b'f*' if op==b'B*' else b'f'))
                ops.extend(paint);ops.extend([pathop,([],b'S')])
            else:ops.append((args,op));ops.extend(paint)
        output=ContentStream(None,stream.pdf);output.operations=ops
        ref=doc.get_new_xref();doc.update_object(ref,'<<>>');doc.update_stream(ref,output.get_data());page.set_contents(ref)
        result=doc.tobytes(garbage=4,deflate=True)
    check_outside_regions(data,result,[dict(page=n,line=dict(bbox=list(rect),text=''),text='')])
    return result


def backgrounds(data,edits):
    for edit in edits:data=background(data,edit)
    return data
