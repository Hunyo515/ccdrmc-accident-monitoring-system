/* Barangay-wide count shading. Geometry controls spread; no synthetic crash points. */
class BarangayHeat {
  constructor(collection, extent) {
    this.coordinates = [[extent[0][0], extent[1][1]], extent[1],
      [extent[1][0], extent[0][1]], extent[0]];
    const mercatorY = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
    const west = extent[0][0], east = extent[1][0];
    const north = mercatorY(extent[1][1]), south = mercatorY(extent[0][1]);
    this.canvas = document.createElement('canvas');
    this.canvas.width = 1536;
    this.canvas.height = Math.round(1536 * (north - south) / ((east - west) * Math.PI / 180));
    const project = p => [(p[0] - west) / (east - west) * this.canvas.width,
      (north - mercatorY(p[1])) / (north - south) * this.canvas.height];
    this.areas = collection.features.map(feature => {
      const geometry = feature.geometry;
      const polygons = (geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates)
        .map(p => p.map(ring => ring.map(project)));
      const points = polygons.flat(2);
      const left = Math.max(0, Math.floor(Math.min(...points.map(p => p[0]))) - 2);
      const top = Math.max(0, Math.floor(Math.min(...points.map(p => p[1]))) - 2);
      const width = Math.min(this.canvas.width - left, Math.ceil(Math.max(...points.map(p => p[0]))) - left + 3);
      const height = Math.min(this.canvas.height - top, Math.ceil(Math.max(...points.map(p => p[1]))) - top + 3);
      const mask = document.createElement('canvas'); mask.width = width; mask.height = height;
      const ctx = mask.getContext('2d', {willReadFrequently: true});
      for (const polygon of polygons) {
        ctx.beginPath();
        for (const ring of polygon) {
          ring.forEach(([x,y], i) => i ? ctx.lineTo(x-left,y-top) : ctx.moveTo(x-left,y-top));
          ctx.closePath();
        }
        ctx.fill('evenodd');
      }
      const pixels = ctx.getImageData(0,0,width,height).data;
      const distances = new Float32Array(width * height);
      for (let i=0;i<distances.length;i++) distances[i] = pixels[i*4+3] > 127 ? 1e6 : 0;
      // Two-pass distance-to-edge transform creates a gradient shaped by the polygon.
      for (let y=0;y<height;y++) for (let x=0;x<width;x++) {
        const i=y*width+x;
        if (!distances[i]) continue;
        distances[i]=Math.min(distances[i], x ? distances[i-1]+1 : 1,
          y ? distances[i-width]+1 : 1,
          x && y ? distances[i-width-1]+Math.SQRT2 : 1e6,
          x<width-1 && y ? distances[i-width+1]+Math.SQRT2 : 1e6);
      }
      let maximum=1;
      for (let y=height-1;y>=0;y--) for (let x=width-1;x>=0;x--) {
        const i=y*width+x;
        if (!distances[i]) continue;
        distances[i]=Math.min(distances[i], x<width-1 ? distances[i+1]+1 : 1,
          y<height-1 ? distances[i+width]+1 : 1,
          x<width-1 && y<height-1 ? distances[i+width+1]+Math.SQRT2 : 1e6,
          x && y<height-1 ? distances[i+width-1]+Math.SQRT2 : 1e6);
        maximum=Math.max(maximum,distances[i]);
      }
      const depth = new Uint8Array(distances.length);
      for (let i=0;i<depth.length;i++) if(distances[i]) depth[i]=Math.max(1,Math.round(255*Math.sqrt(distances[i]/maximum)));
      return {code:feature.properties.ADM4_PCODE,left,top,width,height,depth};
    });
  }
  render(rows=[], referenceMax=0) {
    const counts = new Map(rows.map(row=>[row.code,row.total]));
    const ctx=this.canvas.getContext('2d');
    const result=ctx.createImageData(this.canvas.width,this.canvas.height);
    for (const area of this.areas) {
      const count=counts.get(area.code)||0;
      if(!count || !referenceMax) continue;
      const signal=Math.min(1,Math.sqrt(count/referenceMax));
      for(let y=0;y<area.height;y++) for(let x=0;x<area.width;x++) {
        const depth=area.depth[y*area.width+x]/255;
        if(!depth) continue;
        const core=signal*(.25+.75*depth);
        const i=((area.top+y)*this.canvas.width+area.left+x)*4;
        const alpha=Math.round(255*(.16+.64*signal)*Math.min(1,depth*3));
        if(alpha<result.data[i+3]) continue;
        result.data[i]=255-Math.round(10*core);
        result.data[i+1]=Math.round(165*(1-core)+12*core);
        result.data[i+2]=Math.round(55*(1-core)+12*core);
        result.data[i+3]=alpha;
      }
    }
    ctx.putImageData(result,0,0);
    return this.canvas.toDataURL('image/png');
  }
}
