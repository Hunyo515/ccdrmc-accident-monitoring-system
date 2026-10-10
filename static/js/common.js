// Attach the session CSRF token to same-origin mutations, including uploads.
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, options = {}) => {
  const url = new URL(input instanceof Request ? input.url : input, location.href);
  const sameOrigin = url.origin === location.origin;
  const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
  if (sameOrigin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-CSRF-Token', document.querySelector('meta[name="csrf-token"]').content);
    options = {...options, headers};
  }
  const response = await nativeFetch(input, options);
  if (sameOrigin && response.status === 401) location.assign('/login');
  return response;
};

// Shared helpers used by every page's inline script.

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) { const error = await res.json().catch(() => ({})); throw new Error(error.error || `Request failed: ${url}`); }
  return res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const error = await res.json().catch(() => ({})); throw new Error(error.error || `Request failed: ${url}`); }
  return res.json();
}

function pct(n, digits = 1) {
  if (n === null || n === undefined) return "\u2014";
  return `${(n * 100).toFixed(digits)}%`;
}

function fmt(n) {
  if (n === null || n === undefined) return "\u2014";
  return Number(n).toLocaleString();
}

function debounce(fn, wait = 250) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

/**
 * Shared Chart.js plugin: draws the value at the end of each horizontal bar
 * so the reader doesn't have to trace a gridline to know the number. Pass a
 * per-dataset `endLabelText(value, index)` formatter for custom text (e.g.
 * "68% (1.3x)"); otherwise it falls back to a plain formatted number.
 */
window.chartEndLabelPlugin = {
  id: "endLabel",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    const horizontal = chart.options.indexAxis === "y";
    chart.data.datasets.forEach((dataset, dsIndex) => {
      const meta = chart.getDatasetMeta(dsIndex);
      if (!chart.isDatasetVisible(dsIndex)) return;
      meta.data.forEach((el, i) => {
        const value = dataset.data[i];
        if (value === null || value === undefined) return;
        const label = dataset.endLabelText ? dataset.endLabelText(value, i) : fmt(value);
        ctx.save();
        ctx.fillStyle = "#3d4451";
        ctx.font = (chart.data.datasets.length > 1 ? "600 10px" : "600 11px") + " 'IBM Plex Sans', sans-serif";
        if (horizontal) {
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(label, el.x + 6, el.y);
        } else {
          ctx.textAlign = "center";
          ctx.textBaseline = "bottom";
          ctx.fillText(label, el.x, el.y - 6);
        }
        ctx.restore();
      });
    });
  },
};

/**
 * Turns a text input + hidden list of options into a searchable, single-select
 * combo box. Used for high-cardinality fields (vehicle type, barangay) where a
 * plain <select> with 60-100+ entries is hard to scan.
 */
function makeCombo(inputEl, listEl, options, onSelect) {
  let filtered = options;
  let highlighted = -1;

  function render() {
    listEl.innerHTML = "";
    if (filtered.length === 0) {
      const div = document.createElement("div");
      div.className = "combo-empty";
      div.textContent = "No matches";
      listEl.appendChild(div);
      return;
    }
    filtered.slice(0, 60).forEach((opt, i) => {
      const div = document.createElement("div");
      div.className = "combo-option" + (i === highlighted ? " highlighted" : "");
      div.textContent = opt;
      const select = (e) => {
        e.preventDefault();
        inputEl.value = opt;
        listEl.classList.remove("open");
        onSelect(opt);
      };
      div.addEventListener("mousedown", select);
      div.addEventListener("touchstart", select, { passive: false });
      listEl.appendChild(div);
    });
  }

  function exactMatch(text) {
    const lower = text.trim().toLowerCase();
    return options.find((o) => o.toLowerCase() === lower);
  }

  inputEl.addEventListener("input", () => {
    const q = inputEl.value.trim().toLowerCase();
    filtered = q ? options.filter((o) => o.toLowerCase().includes(q)) : options;
    highlighted = -1;
    listEl.classList.add("open");
    render();
    if (!inputEl.value) { onSelect(""); return; }
    // If what's typed exactly names one option, commit it immediately instead
    // of waiting for a click or an arrow-key selection the person may not know
    // is required.
    const match = exactMatch(inputEl.value);
    if (match) { listEl.classList.remove("open"); onSelect(match); }
  });

  inputEl.addEventListener("focus", () => {
    filtered = options;
    listEl.classList.add("open");
    render();
  });

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); highlighted = Math.min(highlighted + 1, filtered.length - 1); render(); }
    if (e.key === "ArrowUp") { e.preventDefault(); highlighted = Math.max(highlighted - 1, 0); render(); }
    if (e.key === "Enter") {
      e.preventDefault();
      const pick = highlighted >= 0 ? filtered[highlighted] : (filtered.length === 1 ? filtered[0] : exactMatch(inputEl.value));
      if (pick) {
        inputEl.value = pick;
        listEl.classList.remove("open");
        onSelect(pick);
      }
    }
    if (e.key === "Escape") listEl.classList.remove("open");
  });

  // If the field loses focus without an explicit selection, fall back to an
  // exact (case-insensitive) match on whatever was typed, or clear it. This
  // covers the case where someone types a full, correct name and simply
  // clicks or tabs away instead of choosing from the list.
  inputEl.addEventListener("blur", () => {
    setTimeout(() => {
      if (listEl.classList.contains("open")) {
        const match = exactMatch(inputEl.value);
        if (match) {
          inputEl.value = match;
          onSelect(match);
        } else if (inputEl.value) {
          inputEl.value = "";
          onSelect("");
        }
      }
      listEl.classList.remove("open");
    }, 150);
  });

  document.addEventListener("click", (e) => {
    if (!inputEl.contains(e.target) && !listEl.contains(e.target)) {
      listEl.classList.remove("open");
    }
  });
}

window.escapeHTML = function(value) {return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));};

// Refresh other open views after a verified import in this browser.
window.addEventListener('storage',event=>{if(event.key==='ccdrmc-data-updated' && location.pathname!=='/upload')location.reload();});
