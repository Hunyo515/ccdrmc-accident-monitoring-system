(function () {
  const COLOR = {
    emphasis: "#ed1911",
    nonEmphasis: "#b5d5ff",
    fatal: "#d92b2b",
    text: "#5b6474",
    grid: "rgba(28,33,48,0.06)",
  };

  // A short qualitative palette for grouped bar charts (5 barangays): the
  // top-ranked barangay gets the emphasis color, the rest step down a
  // blue gradient so the "leader" still reads clearly in a multi-series
  // chart without introducing hues outside the site's palette.
  const GROUP_PALETTE = ["#ed1911", "#24356f", "#3d63c4", "#7aa3ea", "#b5d5ff"];

  const filters = { yearFrom: "", yearTo: "", barangay: "", collisionType: "", cause: "" };
  let baselineFatalRate = 0;
  let barangayColors = {};
  const esc=window.escapeHTML;
  const charts = {};

  function destroyChart(id) {
    if (charts[id]) { charts[id].destroy(); charts[id] = null; }
  }

  function highlightByMax(data) {
    const maxIdx = data.reduce((best, v, i) => (v > data[best] ? i : best), 0);
    return data.map((_, i) => (i === maxIdx ? COLOR.emphasis : COLOR.nonEmphasis));
  }

  function baseScales(extra) {
    return Object.assign({
      x: { beginAtZero: true, ticks: { color: COLOR.text }, grid: { color: COLOR.grid } },
      y: { ticks: { color: COLOR.text, font: { size: 11.5 } }, grid: { display: false } },
    }, extra || {});
  }

  function pct(part, total) { return total ? ((part / total) * 100).toFixed(1) : "0.0"; }

  function queryString(extra) {
    const p = new URLSearchParams();
    if (filters.yearFrom) p.set("year_from", filters.yearFrom);
    if (filters.yearTo) p.set("year_to", filters.yearTo);
    if (filters.barangay) p.set("barangay", filters.barangay);
    if (filters.collisionType) p.set("collision_type", filters.collisionType);
    if (filters.cause) p.set("cause", filters.cause);
    Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
    return p.toString();
  }

  // NOTE: bar click handlers defer via setTimeout because the drilldown destroys
  // and rebuilds the chart; doing that synchronously inside Chart.js's own click
  // event throws "Cannot read properties of undefined (reading 'handleEvent')".

  // ---- Generic horizontal bar with end labels + emphasis-by-max ----
  function renderHBar(canvasId, labels, data, opts) {
    opts = opts || {};
    const ctx = document.getElementById(canvasId);
    destroyChart(canvasId);
    const maxVal = Math.max(...data, 1);
    charts[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data,
          backgroundColor: opts.colors || highlightByMax(data),
          borderRadius: 3,
          maxBarThickness: 22,
        }],
      },
      plugins: [window.chartEndLabelPlugin],
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { right: 44 } },
        onClick: (evt, elements) => { if (elements.length && opts.onBarClick) { const i = elements[0].index; setTimeout(() => opts.onBarClick(i), 0); } },
        onHover: (evt, elements) => { evt.native.target.style.cursor = (opts.onBarClick && elements.length) ? "pointer" : "default"; },
        plugins: { legend: { display: false } },
        scales: baseScales({ x: { beginAtZero: true, suggestedMax: maxVal * 1.16, ticks: { color: COLOR.text }, grid: { color: COLOR.grid } } }),
      },
    });
  }

  // ---- Generic vertical bar with end labels + emphasis-by-max ----
  function renderVBar(canvasId, labels, data, opts) {
    opts = opts || {};
    const ctx = document.getElementById(canvasId);
    destroyChart(canvasId);
    const maxVal = Math.max(...data, 1);
    charts[canvasId] = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ data, backgroundColor: opts.colors || highlightByMax(data), borderRadius: 3, maxBarThickness: 28 }] },
      plugins: [window.chartEndLabelPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 20 } },
        onClick: (evt, elements) => { if (elements.length && opts.onBarClick) { const i = elements[0].index; setTimeout(() => opts.onBarClick(i), 0); } },
        onHover: (evt, elements) => { evt.native.target.style.cursor = (opts.onBarClick && elements.length) ? "pointer" : "default"; },
        plugins: { legend: { display: false } },
        scales: baseScales({
          x: { ticks: { color: COLOR.text, maxRotation: 0, autoSkip: false, font: {size:10} }, grid: { display: false } },
          y: { beginAtZero: true, suggestedMax: maxVal * 1.18, ticks: { color: COLOR.text }, grid: { color: COLOR.grid } },
        }),
      },
    });
  }

  // ---- KPIs ----
  function renderKPIs(data) {
    const k = data.kpis;
    const t = data.fatality_trend;
    const strip = document.getElementById("kpi-strip");

    let trendHtml = "";
    if (t.previous_year !== null && t.previous_year !== undefined) {
      const cls = t.direction === "up" ? "up" : (t.direction === "down" ? "down" : "flat");
      const iconName = t.direction === "up" ? "trending-up" : (t.direction === "down" ? "trending-down" : "chevrons-up-down");
      const sign = t.delta > 0 ? "+" : "";
      trendHtml = `<span class="kpi-trend ${cls}">${window.ICONS[iconName] || ""} ${sign}${t.delta} vs ${t.previous_year} (${t.previous})</span>`;
    }

    strip.innerHTML = `
      <div class="kpi-lead">
        <div class="kpi-label">${window.ICONS["triangle-alert"] || ""} Fatal crash records</div>
        <div class="kpi-value">${fmt(k.fatal_count)}<span class="kpi-unit">of ${fmt(k.total_accidents)} crashes \u00b7 ${k.fatal_rate_pct}%</span></div>
        <div class="kpi-sub">${trendHtml}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">${window.ICONS["circle-alert"] || ""} Leading cause</div>
        <div class="kpi-value" style="font-size:17px;">${esc(k.top_cause)}</div>
        <div class="kpi-sub">${fmt(k.top_cause_count)} crashes</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">${window.ICONS["map-pin"] || ""} Most affected barangay</div>
        <div class="kpi-value" style="font-size:17px;">${esc(k.top_barangay)}</div>
        <div class="kpi-sub">${fmt(k.top_barangay_count)} crashes</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">${window.ICONS["clock"] || ""} Most frequent crash time</div>
        <div class="kpi-value" style="font-size:17px;">${esc(k.time_period.label)}</div>
        <div class="kpi-sub">${fmt(k.time_period.count)} records per listed period · time_period</div>
      </div>
    `;
  }

  function renderTimeCharts(data) {
    destroyChart('monthly-chart');
    charts['monthly-chart']=new Chart(document.getElementById('monthly-chart'),{
      type:'line',data:{labels:data.yearly_trend.map(r=>r.year),datasets:[{label:'Crash records',data:data.yearly_trend.map(r=>r.count),borderColor:'#2463a7',backgroundColor:'#2463a7',pointRadius:4,tension:0,fill:false}]},
      plugins:[window.chartEndLabelPlugin],options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:24}},plugins:{legend:{display:false}},scales:{x:{title:{display:true,text:'Year'},grid:{display:false}},y:{beginAtZero:true,grace:'15%',ticks:{precision:0},title:{display:true,text:'Number of records'}}}}}
    );
    renderVBar('month-distribution-chart',data.month_distribution.map(r=>r.label.slice(0,3)),data.month_distribution.map(r=>r.count));
  }

  // ---- Generic category panel: overview bar chart <-> fatality-detail bar chart ----
  function makeCategoryPanel(opts) {
    let rows = [];
    const render = opts.vertical ? renderVBar : renderHBar;

    function showOverview() {
      document.getElementById(opts.breadcrumbId).style.display = "none";
      const counts = rows.map((r) => r.count);
      render(opts.chartId, rows.map((r) => r.label), counts, {
        colors: opts.chartId === "barangay-chart" ? rows.map(r=>barangayColors[r.label]) : highlightByMax(counts),
        onBarClick: (i) => showDetail(rows[i]),
      });
      if (opts.insightId) document.getElementById(opts.insightId).innerHTML = opts.captionFn(rows);
    }

    function showDetail(row) {
      document.getElementById(opts.breadcrumbId).style.display = "flex";
      document.getElementById(opts.crumbLabelId).textContent = `${row.label} \u2014 fatality check`;
      renderHBar(opts.chartId, ["Non-fatal injury", "Fatal", "Property damage", "Unknown"], [row.non_fatal, row.fatal, row.property_damage, row.unknown], { colors: [COLOR.nonEmphasis, COLOR.fatal, "#168779", "#a4aab5"] });
      const rate = row.count ? (row.fatal / row.count) * 100 : 0;
      const cmp = rate > baselineFatalRate ? "above" : (rate < baselineFatalRate ? "below" : "in line with");
      const sampleNote = row.count < 30
        ? ` This is a small sample (${fmt(row.count)} records) \u2014 read the rate as indicative, not conclusive.`
        : "";
      if (opts.insightId) {
        document.getElementById(opts.insightId).innerHTML =
          `${window.ICONS["triangle-alert"] || ""} <span>Of ${fmt(row.count)} crashes recorded as <b>${esc(row.label)}</b>, <b>${fmt(row.fatal)}</b> were fatal (${rate.toFixed(2)}%) \u2014 ${cmp} the current view's overall rate of ${baselineFatalRate.toFixed(2)}%.${sampleNote}</span>`;
      }
    }

    document.getElementById(opts.breadcrumbId).querySelector("[data-back]").addEventListener("click", showOverview);
    return { render(newRows) { rows = newRows; showOverview(); } };
  }

  const panels = {
    hour: makeCategoryPanel({
      chartId: "hour-chart", breadcrumbId: "hour-breadcrumb", crumbLabelId: "hour-crumb-label", insightId: "hour-insight", vertical: true,
      captionFn: (rows) => {
        const top = [...rows].filter(r=>r.count>0).sort((a, b) => b.count - a.count)[0];
        return top ? `${window.ICONS["clock"] || ""} <span><b>${esc(top.label)}</b> is the peak hour, with ${fmt(top.count)} recorded crashes. Click any bar to check its fatality split.</span>` : "";
      },
    }),
    day: makeCategoryPanel({
      chartId: "day-chart", breadcrumbId: "day-breadcrumb", crumbLabelId: "day-crumb-label", insightId: "day-insight",
      captionFn: (rows) => {
        const top = [...rows].filter(r=>r.count>0).sort((a, b) => b.count - a.count)[0];
        return top ? `${window.ICONS["users"] || ""} <span><b>${esc(top.label)}</b> has the most recorded crashes, with ${fmt(top.count)} recorded incidents.</span>` : "";
      },
    }),
    cause: makeCategoryPanel({
      chartId: "cause-chart", breadcrumbId: "cause-breadcrumb", crumbLabelId: "cause-crumb-label", insightId: "cause-insight",
      captionFn: (rows) => {
        const top = rows[0], total = rows.reduce((s, r) => s + r.count, 0);
        return top ? `${window.ICONS["circle-alert"] || ""} <span><b>${esc(top.label)}</b> accounts for ${pct(top.count, total)}% of recorded crashes with a known cause.</span>` : "";
      },
    }),
    collision: makeCategoryPanel({
      chartId: "collision-chart", breadcrumbId: "collision-breadcrumb", crumbLabelId: "collision-crumb-label", insightId: "collision-insight",
      captionFn: (rows) => {
        const top = rows[0], total = rows.reduce((s, r) => s + r.count, 0);
        return top ? `${window.ICONS["route"] || ""} <span><b>${esc(top.label)}</b> is the most common collision type, at ${pct(top.count, total)}% of classified collisions.</span>` : "";
      },
    }),
    vehicle: makeCategoryPanel({
      chartId: "vehicle-chart", breadcrumbId: "vehicle-breadcrumb", crumbLabelId: "vehicle-crumb-label", insightId: "vehicle-insight",
      captionFn: (rows) => {
        const top = rows[0], total = rows.reduce((s, r) => s + r.count, 0);
        return top ? `${window.ICONS["car"] || ""} <span><b>${esc(top.label)}</b> is involved in ${pct(top.count, total)}% of crashes with a known vehicle type.</span>` : "";
      },
    }),
    barangay: makeCategoryPanel({
      chartId: "barangay-chart", breadcrumbId: "barangay-breadcrumb", crumbLabelId: "barangay-crumb-label", insightId: "barangay-insight",
      captionFn: (rows) => {
        const top = rows[0], total = rows.reduce((s, r) => s + r.count, 0);
        return top ? `${window.ICONS["map-pin"] || ""} <span><b>${esc(top.label)}</b> recorded ${fmt(top.count)} crashes \u2014 ${pct(top.count, total)}% of this view's total among the top 5.</span>` : "";
      },
    }),
  };

  // ---- Top-5 barangay grouped bar charts (by day, by month) ----
  async function loadBarangayBreakdown() {
    const data = await getJSON(`/api/overview/barangay-breakdown?${queryString()}`);
    const barangays = data.barangays;

    destroyChart("barangay-day-chart");
    charts["barangay-day-chart"] = new Chart(document.getElementById("barangay-day-chart"), {
      type: "bar",
      data: {
        labels: data.days,
        datasets: barangays.map((b, i) => ({ label: b, data: data.by_day[b], backgroundColor: data.colors[b], borderRadius: 2 })),
      },
      plugins: [window.chartEndLabelPlugin],
      options: {
        layout: {padding: {top:24}},
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "bottom", labels: { color: COLOR.text, boxWidth: 12, font: { size: 11 } } } },
        scales: baseScales({
          x: { ticks: { color: COLOR.text }, grid: { display: false } },
          y: { beginAtZero: true, grace: "18%", ticks: { color: COLOR.text, precision:0 }, grid: { color: COLOR.grid } },
        }),
      },
    });

    destroyChart("barangay-month-chart");
    charts["barangay-month-chart"] = new Chart(document.getElementById("barangay-month-chart"), {
      type: "bar",
      data: {
        labels: data.months,
        datasets: barangays.map((b, i) => ({ label: b, data: data.by_month[b], backgroundColor: data.colors[b], borderRadius: 2 })),
      },
      plugins: [window.chartEndLabelPlugin],
      options: {
        layout: {padding: {top:24}},
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: "bottom", labels: { color: COLOR.text, boxWidth: 12, font: { size: 11 } } } },
        scales: baseScales({
          x: { ticks: { color: COLOR.text, maxRotation: 0, font: { size: 10.5 } }, grid: { display: false } },
          y: { beginAtZero: true, grace: "18%", ticks: { color: COLOR.text, precision:0 }, grid: { color: COLOR.grid } },
        }),
      },
    });
  }

  async function load() {
    document.getElementById('data-export').href='/api/export/data.xlsx?'+queryString();
    document.getElementById('analysis-pdf').href='/api/export/analysis.pdf?'+queryString();
    if(Number(filters.yearFrom)>Number(filters.yearTo)){document.getElementById("overview-error").textContent="From year must not be later than To year.";return;}
    document.getElementById("overview-error").textContent="";
    const data = await getJSON(`/api/overview?${queryString()}`);
    baselineFatalRate = data.kpis.fatal_rate_pct;
    barangayColors = data.barangay_colors;
    renderKPIs(data);
    panels.hour.render(data.hourly_distribution);
    panels.day.render(data.day_distribution);
    panels.cause.render(data.top_causes);
    panels.collision.render(data.collision_types);
    panels.vehicle.render(data.top_vehicles);
    panels.barangay.render(data.top_barangays);
    renderTimeCharts(data);
    loadBarangayBreakdown();
  }

  async function init() {
    const [years, opts] = await Promise.all([getJSON("/api/overview/years"), getJSON("/api/filters")]);

    const fromSel = document.getElementById("year-from-filter");
    const toSel = document.getElementById("year-to-filter");
    years.forEach((y) => {
      fromSel.appendChild(new Option(y, y));
      toSel.appendChild(new Option(y, y));
    });
    fromSel.value = years[0];
    toSel.value = years[years.length - 1];
    filters.yearFrom = years[0];
    filters.yearTo = years[years.length - 1];

    fromSel.addEventListener("change", () => { filters.yearFrom = fromSel.value; load(); });
    toSel.addEventListener("change", () => { filters.yearTo = toSel.value; load(); });

    const barangaySel = document.getElementById("barangay-filter");
    opts.barangay.forEach((b) => barangaySel.appendChild(new Option(b, b)));
    barangaySel.addEventListener("change", () => { filters.barangay = barangaySel.value; load(); });

    const collisionSel = document.getElementById("collision-filter");
    opts.collision_type.forEach((c) => collisionSel.appendChild(new Option(c, c)));
    collisionSel.addEventListener("change", () => { filters.collisionType = collisionSel.value; load(); });

    const causeSel = document.getElementById("cause-filter");
    opts.cause.forEach((c) => causeSel.appendChild(new Option(c, c)));
    causeSel.addEventListener("change", () => { filters.cause = causeSel.value; load(); });

    document.getElementById("reset-filters").addEventListener("click", () => {
      fromSel.value = years[0]; toSel.value = years[years.length - 1];
      barangaySel.value = ""; collisionSel.value = ""; causeSel.value = "";
      filters.yearFrom = years[0]; filters.yearTo = years[years.length - 1];
      filters.barangay = ""; filters.collisionType = ""; filters.cause = "";
      load();
    });

    load();
  }

  init();
})();
