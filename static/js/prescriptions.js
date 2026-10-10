// Shared, escaped rendering for the three prescriptions attached to a rule.
(function () {
  const domains = {enforcement:'Enforcement',engineering:'Engineering',education:'Public Information & Education'};
  function esc(value) {return String(value ?? '').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
  function ruleDetail(actions) {
    const chosen = Object.keys(domains).map(key=>actions.find(a=>a.agency===key)).filter(Boolean);
    if (!chosen.length) return '<p class="rx-empty">No actions match this pattern.</p>';
    return `<div class="rx-single-list">${chosen.map(a=>`<section class="rx-single-domain"><h4>${domains[a.agency]}</h4><p>${esc(a.action)}</p></section>`).join('')}</div>`;
  }
  function collapsibleActions(actions) {
    return `<details class="rx-disclosure"><summary><span>Suggested actions</span><span class="rx-disclosure-arrow" aria-hidden="true">${ICONS['chevron-down']}</span></summary><div class="rx-disclosure-body">${ruleDetail(actions || [])}</div></details>`;
  }
  window.Rx = {ruleDetail,collapsibleActions,esc};
})();
