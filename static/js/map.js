(async function () {
  'use strict';
  const el = id => document.getElementById(id);
  const status = el('map-status');
  const filters = {year: '', barangay: '', severity: ''};
  const empty = () => ({type: 'FeatureCollection', features: []});
  let map, extent, barangays, heatRenderer, countsReady = false, requestId = 0, controller, popup;
  const fit = () => map.fitBounds(extent, {padding: 35, duration: 500});

  function renderSummary(data) {
    el('map-count').textContent = `${fmt(data.total)} crashes`;
    el('map-coverage').textContent = `${fmt(data.plotted)} eligible crash points · ${fmt(data.excluded)} hidden from the point overlay because coordinates are missing, imputed, invalid or outside Echague. Barangay shading includes matched records regardless of coordinates.`;
    const ranking = el('map-ranking');
    ranking.replaceChildren();
    const maximum = Math.max(1, ...data.barangays.map(row => row.total));
    for (const row of data.barangays) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      const name = document.createElement('span'); name.textContent = row.name;
      const count = document.createElement('strong'); count.textContent = fmt(row.total);
      button.append(name, count);
      button.title = `Filter to ${row.name}`;
      button.onclick = () => { filters.barangay = row.name; el('m-barangay').value = row.name; loadPoints(); };
      const track = document.createElement('div'); track.className = 'map-rank-track';
      const bar = document.createElement('span'); bar.style.width = `${row.total / maximum * 100}%`; track.append(bar);
      const coverage = document.createElement('small'); coverage.textContent = `${fmt(row.plotted)} with mappable coordinates`;
      item.append(button, track, coverage); ranking.append(item);
    }
    if (!data.barangays.length) ranking.textContent = 'No records match these filters.';
  }

  async function loadPoints() {
    const current = ++requestId;
    countsReady = false;
    if (controller) controller.abort();
    controller = new AbortController();
    if (popup) popup.remove();
    map.getSource('crashes').setData(empty());
    map.getSource('barangay-heat').updateImage({url: heatRenderer.render()});

    status.textContent = 'Updating crash density…';
    try {
      const response = await fetch(`/api/map/summary?${new URLSearchParams(filters)}`, {signal: controller.signal});
      if (!response.ok) throw new Error('Unable to load crash data.');
      const data = await response.json();
      if (current !== requestId) return;
      map.getSource('crashes').setData({type: 'FeatureCollection', features: data.points.map(p => ({
        type: 'Feature', geometry: {type: 'Point', coordinates: [p.lng, p.lat]}, properties: p
      }))});

      map.getSource('barangay-heat').updateImage({url: heatRenderer.render(data.heat_barangays, data.heat_reference_max)});
      const counts = new Map((data.heat_barangays || []).map(row => [row.code, row.total]));
      map.getSource('barangays').setData({...barangays, features: barangays.features.map(f => ({...f, properties: {...f.properties, count: counts.get(f.properties.ADM4_PCODE) || 0}}))});
      countsReady = true;
      renderSummary(data);
      const matched = data.total - (data.heat_unmatched || 0);
      status.textContent = data.total ? `${fmt(matched)} crashes represented by barangay area. Click an area for its count.` : 'No crashes match the selected filters.';
      if (data.heat_unmatched) status.textContent += ` ${fmt(data.heat_unmatched)} records could not be matched to a barangay boundary.`;
    } catch (error) {
      if (error.name === 'AbortError' || current !== requestId) return;
      el('map-count').textContent = 'Unavailable'; el('map-coverage').textContent = '';
      el('map-ranking').replaceChildren();
      status.textContent = 'Crash data could not be loaded. Change a filter or reset to retry.';
    }
  }

  try {
    const boundary = await getJSON(el('accident-map').dataset.boundary);
    const baseStyle = await getJSON(el('accident-map').dataset.style);
    barangays = await getJSON(el('accident-map').dataset.barangays);
    const polygons = boundary.features.flatMap(f => f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates);
    const coords = polygons.flatMap(p => p[0]);
    extent = [[Math.min(...coords.map(c => c[0])), Math.min(...coords.map(c => c[1]))],
              [Math.max(...coords.map(c => c[0])), Math.max(...coords.map(c => c[1]))]];
    heatRenderer = new BarangayHeat(barangays, extent);
    // The outside mask clips both streets and heat at the municipal edge.
    const mask = {type: 'Feature', properties: {}, geometry: {type: 'Polygon', coordinates: [
      [[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]], ...polygons.map(p => p[0])
    ]}};
    map = new maplibregl.Map({
      container: 'accident-map', bounds: extent, fitBoundsOptions: {padding: 35},
      maxBounds: [[extent[0][0] - .07, extent[0][1] - .3], [extent[1][0] + .07, extent[1][1] + .3]],
      maxZoom: 18, renderWorldCopies: false, dragRotate: false, pitchWithRotate: false,
      style: baseStyle
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({unit: 'metric'}), 'bottom-left');
    map.on('error', event => {
      if (event.sourceId === 'openmaptiles' || /tiles\.openfreemap\.org/.test(event.error?.message || '')) el('map-tile-status').hidden = false;
    });
    map.on('webglcontextlost', () => { status.textContent = 'Map graphics were interrupted. Reload this page to restore the map.'; });
    await new Promise(resolve => map.on('load', resolve));
    map.addSource('municipality', {type: 'geojson', data: boundary});
    map.addSource('outside', {type: 'geojson', data: mask});
    map.addSource('crashes', {type: 'geojson', data: empty()});
    map.addSource('barangays', {type: 'geojson', data: barangays});
    map.addSource('barangay-heat', {type: 'image', url: heatRenderer.render(), coordinates: heatRenderer.coordinates});

    map.addLayer({id: 'municipal-tint', type: 'fill', source: 'municipality', paint: {'fill-color': '#f6edda', 'fill-opacity': .18}});
    map.addLayer({id: 'density', type: 'raster', source: 'barangay-heat', paint: {
      'raster-opacity': 1, 'raster-fade-duration': 0, 'raster-resampling': 'linear'
    }});
    map.addLayer({id: 'barangay-areas', type: 'fill', source: 'barangays', paint: {'fill-opacity': 0}});
    map.addLayer({id: 'barangay-borders', type: 'line', source: 'barangays', paint: {
      'line-color': '#867d6d', 'line-width': .65, 'line-opacity': .55
    }});
    map.on('click', 'barangay-areas', event => {
      if (!countsReady || el('m-points').checked) return;
      const p = event.features[0].properties;
      const content = document.createElement('div');
      const title = document.createElement('strong'); title.textContent = p.ADM4_EN;
      const detail = document.createElement('p'); detail.textContent = `${fmt(p.count || 0)} recorded crashes in the selected period.`;
      content.append(title, detail);
      if (popup) popup.remove();
      popup = new maplibregl.Popup().setLngLat(event.lngLat).setDOMContent(content).addTo(map);
    });
    map.addLayer({id: 'crash-points', type: 'circle', source: 'crashes', layout: {visibility: 'none'}, paint: {
      'circle-radius': 4, 'circle-color': ['match', ['get', 'severity'], 'Fatal', '#9f1736', '#1c6355'],
      'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1, 'circle-opacity': .85
    }});
    map.addLayer({id: 'outside-mask', type: 'fill', source: 'outside', paint: {'fill-color': '#f8f4f0', 'fill-opacity': .9999}});
    // Preserve any municipal holes as excluded areas as well.
    const holes = polygons.flatMap(p => p.slice(1)).map(ring => ({type: 'Feature', properties: {}, geometry: {type: 'Polygon', coordinates: [ring]}}));
    map.addSource('holes', {type: 'geojson', data: {type: 'FeatureCollection', features: holes}});
    map.addLayer({id: 'hole-mask', type: 'fill', source: 'holes', paint: {'fill-color': '#f8f4f0', 'fill-opacity': .9999}});
    map.addLayer({id: 'boundary', type: 'line', source: 'municipality', paint: {'line-color': '#354d43', 'line-width': 2}});
    map.on('click', 'crash-points', event => {
      const feature = event.features[0], p = feature.properties;
      const content = document.createElement('div');
      const title = document.createElement('strong'); title.textContent = p.barangay || 'Unspecified barangay'; content.append(title);
      for (const value of [`${p.date} · ${p.severity}`, p.collision_type, p.cause]) {
        const line = document.createElement('p'); line.textContent = value; content.append(line);
      }
      popup = new maplibregl.Popup().setLngLat(feature.geometry.coordinates).setDOMContent(content).addTo(map);
    });
    map.on('mouseenter', 'crash-points', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'crash-points', () => { map.getCanvas().style.cursor = ''; });
    el('m-points').onchange = event => { map.setLayoutProperty('crash-points', 'visibility', event.target.checked ? 'visible' : 'none'); if (popup) popup.remove(); };
    el('m-fit').onclick = fit;
    el('m-year').onchange = event => { filters.year = event.target.value; loadPoints(); };
    el('m-severity').onchange = event => { filters.severity = event.target.value; loadPoints(); };
    el('m-reset').onclick = () => {
      for (const key of Object.keys(filters)) { filters[key] = ''; el(`m-${key}`).value = ''; }
      fit(); loadPoints();
    };
    let previousWidth = el('accident-map').clientWidth;
    const resize = new ResizeObserver(() => {
      map.resize();
      const width = el('accident-map').clientWidth;
      if (width !== previousWidth) { previousWidth = width; map.fitBounds(extent, {padding: 25, duration: 0}); }
    });
    resize.observe(el('accident-map'));
    window.addEventListener('pagehide', () => { controller?.abort(); resize.disconnect(); map.remove(); }, {once: true});
    await loadPoints();
    try {
      const [options, years] = await Promise.all([getJSON('/api/filters'), getJSON('/api/overview/years')]);
      for (const year of years) el('m-year').appendChild(new Option(year, year));
      makeCombo(el('m-barangay'), el('l-barangay'), options.barangay, value => { filters.barangay = value; loadPoints(); });
    } catch (error) { status.textContent += ' Filter options could not be loaded; reload to retry.'; }
  } catch (error) {
    status.textContent = 'The map could not start. Reload and ensure WebGL graphics are enabled in your browser.';
  }
})();








