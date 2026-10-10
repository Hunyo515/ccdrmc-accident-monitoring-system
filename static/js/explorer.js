(function () {
  const COLOR = {emphasis:'#2459a9', nonEmphasis:'#c6dcf5',red:'#c64242',teal:'#168879',text:'#171717'};
  const state={minSupport:0.05,minConfidence:0.60,minLift:1.2,search:'',sortBy:'lift',limit:10};
  let zoomBehavior=null,zoomTarget=null, generation=0;
  function queryString(extra={}) {return new URLSearchParams({min_support:state.minSupport,min_confidence:state.minConfidence,min_lift:state.minLift,search:state.search,...extra}).toString();}
  ['support','confidence','lift'].forEach((name,i)=>{
    const key=['minSupport','minConfidence','minLift'][i];
    document.getElementById(name+'-range').addEventListener('input',e=>{
      state[key]=Number(e.target.value);document.getElementById(name+'-val').textContent=state[key].toFixed(2);refreshSoon();
    });
  });
  document.getElementById('search-box').addEventListener('input',e=>{state.search=e.target.value;refreshSoon();});
  document.getElementById('pattern-limit').addEventListener('change',e=>{state.limit=Math.max(1,Math.min(5000,Math.floor(Number(e.target.value)||10)));e.target.value=state.limit;refreshAll();});
  document.getElementById('pattern-sort').addEventListener('change',e=>{state.sortBy=e.target.value;refreshAll();});
  async function loadTable(){
    const ticket=++generation;
    const data=await getJSON('/api/rules?'+queryString({limit:state.limit,sort_by:state.sortBy}));
    if(ticket!==generation)return;
    document.getElementById("patterns-export").href="/api/export/patterns.csv?"+queryString({sort_by:state.sortBy});
    document.getElementById('rules-count').textContent='Patterns';
    document.getElementById('page-info').textContent=`Showing ${data.rules.length} of ${fmt(data.total)} distinct matching patterns`;
    const list=document.getElementById('pattern-list');
    list.innerHTML=data.rules.length?`<div class="table-scroll"><table class="patterns-table"><thead><tr>
      <th scope="col">Conditions</th><th scope="col">Associated outcome</th><th scope="col">Share of records</th><th scope="col">Match rate</th><th scope="col">Connection strength</th><th scope="col">Suggested actions</th>
      </tr></thead><tbody>${data.rules.map((r,i)=>`
        <tr class="pattern-row">
          <td>${Rx.esc(r.antecedent_label)}</td><td>${Rx.esc(r.consequent_label)}</td>
          <td class="pattern-metric">${(r.support*100).toFixed(1)}%</td><td class="pattern-metric">${(r.confidence*100).toFixed(1)}%</td><td class="pattern-metric">${r.lift.toFixed(2)}×</td>
          <td><button type="button" class="pattern-actions-toggle" aria-expanded="false" aria-controls="pattern-actions-${i}" aria-label="View suggested actions for pattern ${i+1}"><span>View actions</span><span class="action-chevron" aria-hidden="true">${ICONS['chevron-down']}</span></button></td>
        </tr>
        <tr class="pattern-actions-row" id="pattern-actions-${i}" hidden><td colspan="6"><div class="pattern-actions-content">${Rx.ruleDetail(r.actions)}</div></td></tr>
      `).join('')}</tbody></table></div>`:'<div class="empty-state">No patterns meet these settings. Adjust your search or thresholds.</div>';
    list.querySelectorAll('.pattern-actions-toggle').forEach(button=>button.addEventListener('click',()=>{
      const detail=document.getElementById(button.getAttribute('aria-controls'));
      const open=button.getAttribute('aria-expanded')!=='true';
      button.setAttribute('aria-expanded',String(open));detail.hidden=!open;
      button.setAttribute('aria-label', `${open ? 'Hide' : 'View'} suggested actions for pattern ${Array.from(list.querySelectorAll('.pattern-actions-toggle')).indexOf(button)+1}`);
      button.querySelector('span').textContent=open?'Hide actions':'View actions';
      button.closest('tr').classList.toggle('is-expanded',open);
    }));
  }
  // ---- Network graph (D3 force layout + pan/zoom) ----
  async function loadNetwork() {
    const data = await getJSON(`/api/rules/network?${queryString({ top_n: 18 })}`);
    const svg = d3.select("#network-svg");
    svg.selectAll("*").remove();

    const box = document.getElementById("network-svg").getBoundingClientRect();
    const width = box.width || 480;
    const height = 360;
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    if (data.nodes.length === 0) {
      svg.append("text").attr("x", width / 2).attr("y", height / 2).attr("text-anchor", "middle")
        .attr("fill", COLOR.text).text("No patterns meet current thresholds.");
      zoomBehavior = null;
      return;
    }

    const zoomLayer = svg.append("g").attr("class", "zoom-layer");

    const sim = d3.forceSimulation(data.nodes)
      .force("link", d3.forceLink(data.edges).id((d) => d.id).distance(90).strength(0.5))
      .force("charge", d3.forceManyBody().strength(-160))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide(28));

    const edge = zoomLayer.append("g").selectAll("line")
      .data(data.edges).join("line")
      .attr("class", "network-edge")
      .attr("stroke-width", (d) => 1 + (d.lift / (data.max_lift || 1)) * 3);

    const node = zoomLayer.append("g").selectAll("g")
      .data(data.nodes).join("g").attr("class", "network-node");

    node.append("circle")
      .attr("r", (d) => 8 + d.degree * 2)
      .attr("fill", (d) => (d.label === "Fatal" ? COLOR.red : d.label === "Non-Fatal" ? COLOR.teal : COLOR.emphasis));

    node.append("text")
      .attr("dy", (d) => -(10 + d.degree * 2))
      .attr("text-anchor", "middle")
      .text((d) => d.label);

    sim.on("tick", () => {
      edge
        .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    zoomBehavior = d3.zoom()
      .scaleExtent([0.4, 4])
      .on("zoom", (event) => { zoomLayer.attr("transform", event.transform); });
    svg.call(zoomBehavior);
    zoomTarget = svg;
  }

  document.getElementById("zoom-in").addEventListener("click", () => {
    if (zoomBehavior && zoomTarget) zoomTarget.transition().duration(200).call(zoomBehavior.scaleBy, 1.4);
  });
  document.getElementById("zoom-out").addEventListener("click", () => {
    if (zoomBehavior && zoomTarget) zoomTarget.transition().duration(200).call(zoomBehavior.scaleBy, 1 / 1.4);
  });
  document.getElementById("zoom-reset").addEventListener("click", () => {
    if (zoomBehavior && zoomTarget) zoomTarget.transition().duration(200).call(zoomBehavior.transform, d3.zoomIdentity);
  });

  // ---- Heatmap ----
  function liftColor(lift, maxLift) {
    const t = Math.max(0, Math.min(1, lift / (maxLift || 1)));
    const from = [181, 213, 255];
    const to = [237, 25, 17];
    const rgb = from.map((c, i) => Math.round(c + (to[i] - c) * t));
    return { bg: `rgb(${rgb.join(",")})`, text: t < 0.55 ? "#1c2130" : "#ffffff" };
  }

  async function loadHeatmap() {
    const data = await getJSON(`/api/rules/heatmap?${queryString({})}`);
    const table = document.getElementById("heatmap-table");
    if (data.antecedents.length === 0) {
      table.innerHTML = `<tr><td><div class="empty-state">No single-condition patterns meet current thresholds.</div></td></tr>`;
      return;
    }
    const flat = data.matrix.flat().filter((v) => v !== null && v !== undefined);
    const maxLift = Math.max(...flat, 1);

    let head = "<tr><th></th>" + data.consequents.map((c) => `<th class="col-label">${Rx.esc(c)}</th>`).join("") + "</tr>";
    let rows = data.antecedents.map((a, i) => {
      const cells = data.matrix[i].map((v) => {
        if (v === null || v === undefined) return `<td class="empty">\u2014</td>`;
        const c = liftColor(v, maxLift);
        return `<td style="background:${c.bg};color:${c.text};" title="${Rx.esc(a)} \u2192 ${v}">${v.toFixed(2)}</td>`;
      }).join("");
      return `<tr><th>${Rx.esc(a)}</th>${cells}</tr>`;
    }).join("");

    table.innerHTML = head + rows;
  }


  async function refreshAll(){
    try {await loadTable(); await Promise.all([loadNetwork(),loadHeatmap()]);}
    catch(e){document.getElementById('pattern-list').innerHTML='<div class="panel empty-state">Could not load patterns. Please retry.</div>';}
  }
  const refreshSoon=debounce(refreshAll,250);
  document.getElementById('explorer-help-btn').addEventListener('click',()=>window.openHelp('Reading patterns',`
    <h3>Share of all records (support)</h3><p>0.05 means the full combination appears in at least 5 of every 100 records.</p>
    <h3>Match rate (confidence)</h3><p>0.60 means the right-hand condition appears in at least 60 of every 100 records containing the left-hand condition. It does not mean one event happened after another.</p>
    <h3>Connection strength (lift)</h3><p>1.20 means the right-hand condition is 1.2 times as common within the left-hand group as in the whole dataset. This does not prove a cause or statistical significance.</p>
    <h3>Three response teams</h3><p>Each pattern includes Enforcement, Engineering, and Public Information & Education. Actions reflect every field present in that pattern.</p>
    <h3>One action per domain</h3><p>Each rule returns one focused recommendation for each team. The original catalog remains available for reference; its implementation status is not assigned to a new plan.</p>
    <h3>Fewer repeated patterns</h3><p>The same combination is shown once using its strongest qualifying direction. A more detailed condition is also removed when a simpler rule for the same outcome has equal or better confidence and lift. Choose any top count from 1 to 5,000.</p>`));
  refreshAll();
})();
