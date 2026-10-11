"""Print charts from the same aggregates used by the dashboard; no tile requests."""
from io import BytesIO
from math import cos, radians
import textwrap
from services.contextual_prescriptions import plain_language
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle
from reportlab.lib.colors import HexColor
from reportlab.platypus import Image

PALETTE = ['#2463a7', '#168779', '#b56a22', '#8060b4', '#c74762']


def bars(rows, width=505):
    labels = [textwrap.wrap(plain_language(str(r['label'])), 29) or ['Unknown'] for r in rows]
    heights = [max(26, len(lines)*11+8) for lines in labels]
    height = sum(heights)+15
    drawing = Drawing(width, height)
    maximum = max([r['count'] for r in rows]+[1])
    y = height-10
    for row, lines, step in zip(rows, labels, heights):
        y -= step
        for j, label in enumerate(lines):
            drawing.add(String(0, y+step-12-j*11, label, fontSize=8))
        length = 295*row['count']/maximum
        drawing.add(Rect(165, y+5, length, 14, fillColor=HexColor('#d65a37' if row['count']==maximum else '#b9cfdf'), strokeColor=None))
        drawing.add(String(171+length, y+8, str(row['count']), fontSize=8))
    return drawing


def series_chart(labels, series, line=False, hourly=False):
    drawing = Drawing(505, 225)
    maximum = max([v for values in series.values() for v in values]+[1]) or 1
    left, bottom, width, height = 38, 42, 452, 140
    for tick in range(5):
        y = bottom+height*tick/4
        drawing.add(Line(left, y, left+width, y, strokeColor=HexColor('#e0e6e9')))
        drawing.add(String(left-7, y-3, f'{maximum*tick/4:g}', textAnchor='end', fontSize=7))
    step = width/max(len(labels), 1)
    for index, label in enumerate(labels):
        drawing.add(String(left+step*(index+.5), bottom-14, str(label).replace(' AM','a').replace(' PM','p') if hourly else str(label), textAnchor='middle', fontSize=6 if hourly else 7))
    for s, (name, values) in enumerate(series.items()):
        color = HexColor(PALETTE[s % len(PALETTE)])
        previous = None
        for i, value in enumerate(values):
            x = left+step*(i+.5); y = bottom+height*value/maximum
            if line:
                if previous: drawing.add(Line(*previous, x, y, strokeColor=color, strokeWidth=2))
                drawing.add(Circle(x, y, 2.5, fillColor=HexColor('#d65a37') if value==maximum else color, strokeColor=None))
                drawing.add(String(x, y+7, str(value), textAnchor='middle', fontSize=7))
                previous = (x, y)
            else:
                bw = step*.8/max(len(series), 1)
                bar_x = x-step*.4+s*bw
                fill = HexColor('#d65a37') if value==maximum else (color if len(series)>1 else HexColor('#b9cfdf'))
                drawing.add(Rect(bar_x, bottom, bw*.9, height*value/maximum, fillColor=fill, strokeColor=None))
                drawing.add(String(bar_x+bw*.45, y+4, str(value), textAnchor='middle', fontSize=5 if len(series)>1 else 6, fontName='Helvetica-Bold' if value==maximum else 'Helvetica'))
        if len(series)>1:
            lx = (s % 3)*168; ly = 212-(s//3)*14
            drawing.add(Rect(lx, ly-2, 7, 7, fillColor=color, strokeColor=None))
            drawing.add(String(lx+11, ly-1, name, fontSize=7))
    return drawing


def accident_map(frame):
    """Barangay-count shading with soft interior diffusion, never invented crash points."""
    import numpy as np
    from PIL import Image as PILImage, ImageDraw
    from scipy.ndimage import distance_transform_edt
    from services.map_service import barangay_boundary, _barangay_key
    from collections import Counter
    features = barangay_boundary()['features']
    counts = Counter()
    for name, count in frame.barangay.value_counts().items():
        counts[_barangay_key(name)] += int(count)
    def polygons(feature):
        g = feature['geometry']
        return [g['coordinates']] if g['type']=='Polygon' else g['coordinates']
    coords = [p for f in features for poly in polygons(f) for p in poly[0]]
    xs, ys = zip(*[(p[0], p[1]) for p in coords])
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    scale = min(920/((xmax-xmin)*cos(radians((ymin+ymax)/2))), 840/(ymax-ymin))
    def xy(p): return (40+(p[0]-xmin)*cos(radians((ymin+ymax)/2))*scale, 40+(ymax-p[1])*scale)
    size = (1000, int(80+(ymax-ymin)*scale))
    canvas = PILImage.new('RGB', size, 'white')
    peak = max(counts.values(), default=1)
    matched = set()
    for f in features:
        key = _barangay_key(f['properties']['ADM4_EN']); matched.add(key)
        mask = PILImage.new('L', size); pen = ImageDraw.Draw(mask)
        for poly in polygons(f):
            pen.polygon([xy(p) for p in poly[0]], fill=255)
            for hole in poly[1:]: pen.polygon([xy(p) for p in hole], fill=0)
        area = np.asarray(mask)>0
        count = counts.get(key, 0)
        rgb = np.full((size[1], size[0], 3), 248, dtype=np.uint8)
        if count and area.any():
            depth = distance_transform_edt(area); depth /= max(depth.max(), 1)
            strength = (count/peak)**.5
            mix = np.sqrt(depth)*strength
            orange = np.array([255, 179, 91]); red = np.array([222, 44, 35])
            color = orange+(red-orange)*mix[..., None]
            alpha = .18+.58*strength*np.sqrt(depth)
            rgb = (255*(1-alpha[..., None])+color*alpha[..., None]).astype('uint8')
        canvas.paste(PILImage.fromarray(rgb), (0, 0), mask)
    pen = ImageDraw.Draw(canvas)
    for f in features:
        for poly in polygons(f):
            for ring in poly: pen.line([xy(p) for p in ring], fill='#66706b', width=1)
    pen.text((930, 30), 'N', fill='#263c35'); pen.line((935, 65, 935, 45), fill='#263c35', width=2)
    output = BytesIO(); canvas.save(output, format='PNG'); output.seek(0)
    return Image(output, width=470, height=470*size[1]/size[0]), sum(v for k,v in counts.items() if k not in matched), peak
