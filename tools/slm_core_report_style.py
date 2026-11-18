"""Local, self-contained PDF and HTML views of the same report blocks."""
from html import escape
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                               LongTable, TableStyle, KeepTogether, CondPageBreak)

# Ink, light fill, accent. Labels always accompany colours.
PALETTE = {
    'fail': ('#8E2636', '#FCEEF0', '#B83B4F'),
    'pass': ('#155E45', '#EAF6EF', '#247959'),
    'wait': ('#794005', '#FFF2DF', '#AA5B0B'),
    'info': ('#214E79', '#EBF3FB', '#356D9D'),
    'neutral': ('#415365', '#EFF3F6', '#647589'),
}
INK, MUTED, LINE = '#182D40', '#495D70', '#CDD8E0'
TITLE = 'Synthèse du contrôle du CCTP'


def finding_parts(x):
    tone, status = ('fail','Non conforme') if x['outcome']=='ecart' else ('pass','Conforme')
    fields = [('Pourquoi ?', x['why'], 'why'), ('Dans le CCTP', '« '+x['subject']+' »', 'quote')]
    if x['conclusion_kind']=='coherence':
        fields.append(('Base de comparaison','Pièces du dossier.', 'source'))
    else:
        label = 'Référentiel technique' if x['conclusion_kind']=='technical' else 'Texte juridique utilisé'
        fields.append((label,x['law'] or 'Référence non enregistrée.', 'source'))
        if x['rule'] and len(x['rule'])<=360:
            fields.append(('Extrait du critère','« '+x['rule']+' »','excerpt'))
    return tone, status, fields


def render_html(readings, analysis, blocks):
    e=lambda s: escape(str(s))
    themed=''.join('.cctp .'+k+'{--ink:'+i+';--bg:'+b+';--accent:'+a+'}' for k,(i,b,a) in PALETTE.items())
    css=""" .cctp{max-width:58rem;margin:2rem auto;padding:0 clamp(.7rem,3vw,2.5rem);color:#182d40;font:1rem/1.5 system-ui,Arial,sans-serif;overflow-wrap:anywhere}
.cctp *{box-sizing:border-box}.cctp h1{font-size:clamp(1.7rem,4vw,2.5rem);line-height:1.14;margin:.35rem 0}.cctp p{margin:.45rem 0}
.cctp .eyebrow,.cctp dt{font-size:.77rem;letter-spacing:.07em;text-transform:uppercase;font-weight:750}.cctp .eyebrow,.cctp .meta,.cctp .note{color:#495d70}
.cctp header{border-top:4px solid #233f52;padding-top:1rem;margin-bottom:1.1rem}.cctp .verdict{padding:1rem 1.3rem;background:var(--bg);border-left:6px solid var(--accent)}
.cctp .verdict h2{margin:.16rem 0 .5rem;color:var(--ink);line-height:1.25}.cctp .verdict .eyebrow{color:var(--ink)}.cctp .source{color:#214e79}
.cctp .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,9rem),1fr));gap:.5rem;margin:1rem 0 .25rem;padding:0;list-style:none}
.cctp .annex{margin-top:1.5rem;border-top:1px solid #cdd8e0;padding-top:.65rem}.cctp .annex summary{font-weight:700;color:#415365;cursor:pointer}
.cctp .metrics li{border-top:3px solid var(--accent);background:var(--bg);color:var(--ink);padding:.5rem .75rem;font-size:.84rem;font-weight:650}
.cctp .metrics strong{display:block;font-size:1.65rem;line-height:1.15}.cctp .note,.cctp .meta{font-size:.85rem}
.cctp h2.section{border-bottom:2px solid var(--accent);color:var(--ink);margin:1.7rem 0 .6rem;padding-bottom:.25rem;font-size:1.25rem}
.cctp h3{font-size:1rem}.cctp .finding{margin:.75rem 0;border:1px solid #cdd8e0;border-left:4px solid var(--accent);break-inside:avoid}
.cctp .finding h3{margin:0;padding:.5rem .9rem;background:var(--bg);color:var(--ink)}.cctp dl{margin:0;padding:.6rem .9rem}.cctp dt{margin-top:.34rem;color:#495d70}.cctp dt:first-child{margin:0}.cctp dt.source{color:#214e79}.cctp dd{margin:0 0 .4rem}
.cctp .scroll{overflow-x:auto;margin:.5rem 0}.cctp table{width:100%;border-collapse:collapse;font-size:.9rem}.cctp th,.cctp td{text-align:left;vertical-align:top;padding:.45rem .6rem;border-bottom:1px solid #cdd8e0}
.cctp th{background:var(--bg);color:var(--ink);font-weight:700}.cctp tbody tr:nth-child(even){background:#f6f8fa}.cctp .badge{display:inline-block;color:var(--ink);background:var(--bg);border-left:3px solid var(--accent);padding:.1rem .45rem;font-weight:700;white-space:nowrap}
@media(max-width:580px){.cctp .scroll table{min-width:32rem}.cctp{margin:1rem auto}}
@media print{.cctp{max-width:none;margin:0;padding:0}.cctp th,.cctp .badge,.cctp .metrics,.cctp .verdict,.cctp .finding h3{print-color-adjust:exact;-webkit-print-color-adjust:exact}.cctp .scroll{overflow:visible}.cctp .scroll table{min-width:0}.cctp tr{break-inside:avoid}.cctp h2,.cctp h3{break-after:avoid}}"""
    out=['<section class="v5 cctp"><style>'+css+themed+'</style><header><span class="eyebrow">CCTP Clair · Rapport de contrôle</span><h1>'+TITLE+'</h1><p>'+e(readings.get('filename') or 'Document')+'</p><p class="meta">Date juridique : '+e(analysis.get('date_reference') or '?')+'</p></header>']
    def table(tone, headers, body):
        out.append('<div class="scroll"><table class="'+tone+'"><thead><tr>'+''.join('<th scope="col">'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+c+'</td>' for c in row)+'</tr>' for row in body)+'</tbody></table></div>')
    for typ,v in blocks:
        if typ=='verdict':
            title,why,ref,tone=v
            out.append(f'<div class="verdict {tone}"><span class="eyebrow">Verdict du dossier</span><h2>{e(title)}</h2><p><b>Pourquoi ?</b> {e(why)}</p>'+('<p class="source"><b>Référence :</b> '+e(ref)+'</p>' if ref else '')+'</div>')
        elif typ=='metrics':
            out.append('<ul class="metrics" aria-label="Décisions et repères du dossier">'+''.join(f'<li class="{tone}"><strong>{n}</strong>{e(label)}</li>' for n,label,tone in v)+'</ul>')
        elif typ=='annex_start': out.append('<details class="annex"><summary>'+e(v)+'</summary>')
        elif typ=='annex_end': out.append('</details>')
        elif typ=='overview':
            body=[]
            for x in v:
                tone,status,_=finding_parts(x)
                body.append([f'<span class="badge {tone}">{status}</span>',e(x['subject']),e(x['id']+' · p. '+x['page'])])
            table('neutral',['Résultat','Prescription du CCTP','Point / page'],body)
        elif typ=='finding':
            tone,status,fields=finding_parts(v)
            out.append(f'<article class="finding {tone}"><h3>{status} · {e(v["id"])} · Document page {e(v["page"])}</h3><dl>'+''.join(f'<dt class="{cls}">{e(label)}</dt><dd class="{cls}">{e(val)}</dd>' for label,val,cls in fields)+'</dl></article>')
        elif typ=='heading': out.append(f'<h2 class="section {v[1]}">{e(v[0])}</h2>')
        elif typ=='table': table(v[3],v[0],[[e(c) for c in row] for row in v[1]])
        elif typ=='subheading': out.append('<h3>'+e(v)+'</h3>')
        else: out.append('<p'+(' class="note"' if typ=='note' else '')+'>'+e(v)+'</p>')
    return ''.join(out)+'</section>'


def render_pdf(readings, analysis, blocks):
    from v4_9_readable_report import styles
    styles()
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=36,rightMargin=36,topMargin=37,bottomMargin=39,title=TITLE,author='CCTP Clair')
    width=doc.width-12
    hx=colors.HexColor
    def st(name,size,leading,ink=INK,bold=False,**kwargs):
        return ParagraphStyle(name,fontName='CctpArialBold' if bold else 'CctpArial',fontSize=size,leading=leading,textColor=hx(ink),**kwargs)
    body=st('body',10.2,14.2,spaceAfter=5)
    small=st('small',8.8,11.5,MUTED,spaceAfter=2)
    cell=st('cell',9.5,12.7)
    title_s=st('title',24,28,bold=True,spaceAfter=6)
    kick=st('kick',8.7,12,MUTED,True,spaceAfter=3)
    def p(value,s=body):return Paragraph(escape(str(value)),s)
    def field(label,text,style):
        return Paragraph('<font name="CctpArialBold">'+escape(label)+'</font> '+escape(str(text)),style)
    def pads(x,y):
        return [(side+'PADDING',(0,0),(-1,-1),n) for side,n in [('LEFT',x),('RIGHT',x),('TOP',y),('BOTTOM',y)]]
    def tbl(data,widths,commands,repeat=0,long=False):
        cls=LongTable if long else Table
        return cls(data,colWidths=widths,hAlign='LEFT',repeatRows=repeat,splitInRow=1,
                   style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]+commands))
    def grid(tone,headers,rows,ratios):
        ink,bg,accent=PALETTE[tone]
        hs=st('th',9,11.5,ink,True)
        return tbl([[p(x,hs) for x in headers]]+rows,[width*n for n in ratios],pads(6,4.5)+[
            ('BACKGROUND',(0,0),(-1,0),hx(bg)),('LINEBELOW',(0,0),(-1,0),1,hx(accent)),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,hx('#F5F8FA')]),('LINEBELOW',(0,1),(-1,-1),.28,hx(LINE))],1,True)
    story=[p('CCTP CLAIR   /   RAPPORT DE CONTRÔLE',kick),p(TITLE,title_s),p(readings.get('filename') or 'Document',body),
           p('Date juridique : '+str(analysis.get('date_reference') or '?'),small),Spacer(1,8)]
    for typ,v in blocks:
        if typ=='verdict':
            title,why,ref,tone=v
            ink,bg,accent=PALETTE[tone]
            items=[p('VERDICT DU DOSSIER',st('k',8.5,11,ink,True,spaceAfter=4)),p(title,st('v',15.5,19,ink,True,spaceAfter=5)),field('Pourquoi ?',why,body)]
            if ref:items.append(field('Référence :',ref,st('src',9,13,PALETTE['info'][0])))
            story.extend([tbl([[items]],[width],pads(12,9)+[('BACKGROUND',(0,0),(-1,-1),hx(bg)),('LINEBEFORE',(0,0),(0,-1),4,hx(accent))]),Spacer(1,10)])
        elif typ=='metrics':
            vals=[];commands=pads(8,5)
            for i,(n,label,tone) in enumerate(v):
                ink,bg,accent=PALETTE[tone]
                vals.append([p(n,st('number',19,22,ink,True)),p(label,st('label',9,12,ink,True))])
                commands.extend([('BACKGROUND',(i,0),(i,0),hx(bg)),('LINEABOVE',(i,0),(i,0),2,hx(accent))])
            story.extend([tbl([vals],[width/len(v)]*len(v),commands+[('INNERGRID',(0,0),(-1,-1),2,colors.white)]),Spacer(1,4)])
        elif typ=='note':story.append(p(v,small))
        elif typ=='heading':
            label,tone=v; ink,bg,accent=PALETTE[tone]
            hs=st('section',14,18,ink,True,spaceBefore=12,spaceAfter=5,keepWithNext=True)
            story.append(p(label,hs))
        elif typ=='subheading':
            story.append(p(v,st('sub',10.2,14,PALETTE['neutral'][0],True,spaceBefore=5,spaceAfter=4,keepWithNext=True)))
        elif typ=='annex_start':
            story.extend([CondPageBreak(doc.height-12),p(v,st('annex',14,18,PALETTE['neutral'][0],True,spaceAfter=5,keepWithNext=True))])
        elif typ=='annex_end': pass
        elif typ=='overview':
            rows=[]
            for x in v:
                tone,status,_=finding_parts(x)
                rows.append([p(status,st('status',9.5,12,PALETTE[tone][0],True)),p(x['subject'],cell),p(x['id']+' · p. '+x['page'],cell)])
            t=grid('neutral',['Résultat','Prescription du CCTP','Point / page'],rows,[.20,.60,.20])
            for i,x in enumerate(v,1):
                style=PALETTE['fail' if x['outcome']=='ecart' else 'pass']
                t.setStyle(TableStyle([('BACKGROUND',(0,i),(0,i),hx(style[1])),('LINEBEFORE',(0,i),(0,i),2,hx(style[2]))]))
            story.append(t)
        elif typ=='finding':
            tone,status,fields=finding_parts(v);ink,bg,accent=PALETTE[tone]
            bar=tbl([[p(status+' · '+v['id']+' · Document page '+v['page'],st('status',11,14,ink,True))]],[width],
                pads(9,5)+[('BACKGROUND',(0,0),(-1,-1),hx(bg)),('LINEBEFORE',(0,0),(0,-1),3,hx(accent))])
            content=[bar,Spacer(1,4)]
            for label,val,cls in fields:
                color=PALETTE['info'][0] if cls=='source' else (MUTED if cls=='excerpt' else INK)
                size=9 if cls in ('source','excerpt') else 10
                s=st('field',size,size*1.35,color,leftIndent=9,spaceAfter=3)
                content.append(field(label+('' if label.endswith('?') else ' :'),val,s))
            story.extend([KeepTogether(content),Spacer(1,5)])
        elif typ=='table':
            heads,rows,ratios,tone=v
            story.extend([grid(tone,heads,[[p(c,cell) for c in row] for row in rows],ratios),Spacer(1,6)])
        else:story.append(p(v))
    def frame(c,d):
        w,h=A4;c.saveState()
        c.setStrokeColor(hx('#234658'));c.setLineWidth(2 if d.page==1 else .55);c.line(42,h-27,w-42,h-27)
        c.setStrokeColor(hx(LINE));c.setLineWidth(.5);c.line(42,33,w-42,33)
        c.setFillColor(hx(MUTED));c.setFont('CctpArialBold',8);c.drawString(42,20,'CCTP CLAIR')
        c.setFont('CctpArial',8);c.drawString(105,20,'Rapport de contrôle');c.drawRightString(w-42,20,'Page '+str(d.page))
        c.restoreState()
    doc.build(story,onFirstPage=frame,onLaterPages=frame)
    return buffer.getvalue()
