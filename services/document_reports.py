"""Filtered, formatted Excel records and PDF analysis reports."""
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape
import pandas as pd
from services import report_service, rules_service, prescription_service


def export_records(frame, filters):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    book=Workbook();sheet=book.active;sheet.title='Approved records'
    sheet.append(['MDRRMC Echague - Approved accident records'])
    sheet.append(['Generated',datetime.now(ZoneInfo('Asia/Manila')).isoformat()])
    sheet.append(['Filters',', '.join(f'{k}: {v}' for k,v in filters.items() if v) or 'All records'])
    sheet.append(['Record count',len(frame)])
    columns=list(frame.columns);sheet.append(columns)
    for row in report_service.records(frame):
        sheet.append([report_service.safe_cell(row.get(c)) for c in columns])
    for cell in sheet[5]:
        cell.fill=PatternFill('solid',fgColor='063C29');cell.font=Font(color='FFFFFF',bold=True);cell.alignment=Alignment(wrap_text=True)
    sheet.row_dimensions[5].height=32
    sheet.freeze_panes='A6'
    if columns:sheet.auto_filter.ref=f'A5:{get_column_letter(len(columns))}{max(5,sheet.max_row)}'
    for i,c in enumerate(columns,1):sheet.column_dimensions[get_column_letter(i)].width=42 if c in ('damage_injury','review_notes') else 23
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=sheet.PAPERSIZE_A3;sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    sheet.print_title_rows='1:5';sheet.sheet_view.showGridLines=False
    output=BytesIO();book.save(output);return output.getvalue()


def analysis_pdf(frame, filters, revision):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,KeepTogether
    from reportlab.graphics.shapes import Drawing,Rect,String
    from arm.pipeline import ARMPipeline
    styles=getSampleStyleSheet();styles['Normal'].fontSize=10;styles['Normal'].leading=15
    styles['Title'].textColor=colors.HexColor('#063C29')
    styles.add(ParagraphStyle(name='SmallNote',fontSize=9,leading=13,textColor=colors.HexColor('#405447')))
    output=BytesIO();doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=42)
    story=[]
    def p(text,style='Normal'):return Paragraph(escape(str(text)),styles[style])
    story += [p('Road Accident Analysis','Title'),p('Municipal Disaster Risk Reduction Management Council | Echague, Isabela','SmallNote'),Spacer(1,12)]
    generated=datetime.now(ZoneInfo('Asia/Manila')).strftime('%d %B %Y, %I:%M %p PHT')
    story += [p('Generated: '+generated,'SmallNote'),p('Filters: '+(', '.join(f'{k.replace("_"," ")}: {v}' for k,v in filters.items() if v) or 'All approved records'),'SmallNote'),p('Dataset revision: '+revision,'SmallNote'),Spacer(1,16)]
    severity=frame.severity.value_counts() if len(frame) else {}
    summary=[['Approved records','Fatal','Non-Fatal','Property damage','Unknown'],[str(len(frame)),str(severity.get('Fatal',0)),str(severity.get('Non-Fatal',0)),str(severity.get('Damage-to-Property',0)),str(severity.get('Unknown',0))]]
    table=Table(summary,colWidths=[101.6]*5);table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7f1eb')),('TEXTCOLOR',(0,0),(-1,-1),colors.HexColor('#063C29')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('BOTTOMPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),12)]));story += [table,Spacer(1,12),p('Totals count submitted records, not necessarily distinct incidents. Pending submissions and unapproved edits are excluded.','SmallNote')]
    if frame.empty:
        story.append(p('No approved records match these filters.','Heading2'))
    else:
        def chart(column,title):
            counts=frame[column].fillna('Unknown').astype(str).value_counts().head(8)
            height=len(counts)*30+12;drawing=Drawing(510,height);maximum=max(counts.max(),1)
            for i,(label,count) in enumerate(counts.items()):
                y=height-25-i*30
                label=label if len(label)<=30 else label[:27]+'...'
                drawing.add(String(0,y+3,label,fontSize=9))
                width=270*count/maximum
                drawing.add(Rect(175,y,width,16,fillColor=colors.HexColor('#4D896A'),strokeColor=None))
                drawing.add(String(182+width,y+3,str(count),fontSize=9))
            return [p(title,'Heading2'),drawing,Spacer(1,8)]
        story += chart('barangay','Barangays with the most records')
        story += chart('cause','Leading recorded causes')
        story += [PageBreak()]+chart('time_period','Time periods')+chart('collision_type','Collision types')
        candidate=ARMPipeline();candidate.data=frame.copy();candidate._staging=True;candidate.run(force=True)
        rules,_=rules_service.filter_rules(candidate.rules,limit=10)
        story += [PageBreak(),p('Patterns and suggested actions','Heading1'),p('Patterns below are recomputed using only the filtered records in this report. Support: at least 5%; confidence: at least 60%; lift: at least 1.20. Associations do not establish causation.','SmallNote'),Spacer(1,12)]
        if not rules:story.append(p('No patterns meet the thresholds for this selection.'))
        for index,rule in enumerate(rules,1):
            block=[p(f'{index}. {rule["antecedent_label"]} leads to {rule["consequent_label"]}','Heading3'),p(f'Share: {rule["support"]:.1%} | Match rate: {rule["confidence"]:.1%} | Lift: {rule["lift"]:.2f}','SmallNote')]
            for action in prescription_service.get().match_rule(rule):
                label={'enforcement':'Enforcement','engineering':'Engineering','education':'Public Information & Education'}.get(action['agency'],action['agency'])
                block.extend([p(label,'Heading4'),p(action['action'])])
            block.append(Spacer(1,12));story.append(KeepTogether(block))
    def footer(canvas,document):
        canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#405447'));canvas.drawString(42,24,'MDRRMC Echague | Approved records');canvas.drawRightString(A4[0]-42,24,f'Page {document.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer);return output.getvalue()
