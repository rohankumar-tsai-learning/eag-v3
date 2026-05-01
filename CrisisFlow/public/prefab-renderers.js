/**
 * Rendering functions (extracted from app.js)
 * All rendering logic stays the same, just organized into a module.
 */

// DOM node cache
export const nodes = {
  refreshBtn: document.querySelector("#refreshBtn"),
  forceToggle: document.querySelector("#forceToggle"),
  clearLogBtn: document.querySelector("#clearLogBtn"),
  riskEnergy: document.querySelector("#riskEnergy"),
  riskFood: document.querySelector("#riskFood"),
  throttleStatus: document.querySelector("#throttleStatus"),
  trendCards: document.querySelector("#trendCards"),
  advisoryList: document.querySelector("#advisoryList"),
  auditLog: document.querySelector("#auditLog"),
  trendTemplate: document.querySelector("#trendTemplate"),
};

let lastPayload = null;

export function fmtAge(isoTs) {
  if (!isoTs) return "";
  const secs = Math.round((Date.now() - Date.parse(isoTs)) / 1000);
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

export function riskClass(level) {
  return level.toLowerCase();
}

export function drawSparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  if (!values.length) {
    return;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1e-6);

  ctx.strokeStyle = "#7fd4ff";
  ctx.lineWidth = 2;
  ctx.beginPath();

  values.forEach((v, idx) => {
    const x = (idx / Math.max(values.length - 1, 1)) * (w - 10) + 5;
    const y = h - ((v - min) / span) * (h - 12) - 6;
    if (idx === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });

  ctx.stroke();
}

export function renderRisk(payload) {
  nodes.riskEnergy.textContent = payload.risk.energy;
  nodes.riskFood.textContent = payload.risk.food;
  nodes.riskEnergy.className = riskClass(payload.risk.energy);
  nodes.riskFood.className = riskClass(payload.risk.food);

  const meta = payload.probe.metadata;
  const age = fmtAge(meta.latestDataTs);
  const ageLabel = age ? ` — ${age}` : "";

  if (meta.throttled) {
    nodes.throttleStatus.textContent = `System Throttled — cooling down ${meta.cooldownRemainingSec}s`;
  } else if (meta.usedLocalFreshData) {
    nodes.throttleStatus.textContent = `Vault cache${ageLabel} (no network fetch needed)`;
  } else {
    nodes.throttleStatus.textContent = `Live probe completed${ageLabel}`;
  }
}

export function refreshRiskClock() {
  if (!lastPayload) {
    return;
  }
  renderRisk(lastPayload);
}

export function renderAdvisory(payload) {
  nodes.advisoryList.innerHTML = "";
  payload.advisory.forEach((item) => {
    const li = document.createElement("li");
    if (item.region === "Disclaimer" || item.action === "Gemini Free Tier") {
      li.classList.add("advisory-disclaimer");
    }
    li.textContent = `${item.region}: ${item.action} - ${item.reason}`;
    nodes.advisoryList.appendChild(li);
  });
}

export function showSkeletons() {
  nodes.trendCards.innerHTML = "";
  nodes.trendCards.classList.add("loading");
  for (let i = 0; i < 6; i++) {
    const sk = document.createElement("div");
    sk.className = "trend-card skeleton-card";
    sk.innerHTML = `
      <div class="skel skel-title"></div>
      <div class="skel skel-meta"></div>
      <div class="skel skel-body"></div>
    `;
    nodes.trendCards.appendChild(sk);
  }
}

export function clearSkeletons() {
  nodes.trendCards.classList.remove("loading");
}

export function setProbing(on) {
  nodes.refreshBtn.disabled = on;
  nodes.refreshBtn.textContent = on ? "Probing…" : "Probe Now";
}

export function renderTrends(payload, vault) {
  nodes.trendCards.innerHTML = "";
  const commodities = Object.values(vault.commodities || {});
  const probeByKey = new Map((payload?.probe?.items || []).map((item) => [item.key, item]));
  const hiddenKeys = ["petrol_singapore", "petrol_tokyo", "petrol_mumbai"];

  commodities.forEach((series) => {
    if (hiddenKeys.includes(series.key)) {
      return;
    }

    const frag = nodes.trendTemplate.content.cloneNode(true);
    const card = frag.querySelector(".trend-card");
    const title = card.querySelector("h3");
    const meta = card.querySelector(".meta");
    const badge = card.querySelector(".badge");
    const source = card.querySelector(".source");
    const sentiment = card.querySelector(".sentiment");
    const canvas = card.querySelector("canvas");
    const probeItem = probeByKey.get(series.key);

    title.textContent = series.label;
    const latest = series.entries[series.entries.length - 1];
    if (latest) {
      meta.textContent = `${latest.price.toFixed(2)} ${latest.unit}`;
    }

    if (probeItem) {
      badge.textContent = probeItem.stale ? "STALE" : "LIVE";
      badge.className = `badge ${probeItem.stale ? "badge-stale" : "badge-live"}`;
      source.textContent = `Source: ${probeItem.source}`;
      sentiment.textContent = probeItem.sentiment;
    } else {
      badge.textContent = "UNKNOWN";
      badge.className = "badge badge-stale";
      source.textContent = "Source: unavailable";
      sentiment.textContent = "Sentiment unavailable for this cycle.";
    }

    const canvas_container = card.querySelector("canvas").parentElement;
    if (["urea_cf", "npk_mosaic"].includes(series.key)) {
      card.querySelector("canvas").style.display = "none";
      const table = document.createElement("table");
      table.style.width = "100%";
      table.style.fontSize = "0.95rem";
      table.innerHTML = `
        <tr style="border-bottom: 1px solid rgba(127, 212, 255, 0.2);">
          <td style="padding: 0.5rem 0;">Current Value</td>
          <td style="text-align: right; font-weight: 600;">${latest.price.toFixed(2)}</td>
        </tr>
        <tr style="border-bottom: 1px solid rgba(127, 212, 255, 0.2);">
          <td style="padding: 0.5rem 0;">24h Change</td>
          <td style="text-align: right;">${
            series.entries.length > 1 ? (series.entries[series.entries.length - 1].price - series.entries[0].price).toFixed(2) : "N/A"
          }</td>
        </tr>
        <tr>
          <td style="padding: 0.5rem 0;">Status</td>
          <td style="text-align: right; color: #7fd4ff;">Stable</td>
        </tr>
      `;
      canvas_container.appendChild(table);
    } else {
      const values = series.entries.slice(-24).map((e) => e.price);
      drawSparkline(canvas, values);
    }
    nodes.trendCards.appendChild(frag);
  });
  clearSkeletons();
}

export function setLastPayload(payload) {
  lastPayload = payload;
}

export function updateAuditLog(tail, preserve = false) {
  const prevTop = nodes.auditLog.scrollTop;
  nodes.auditLog.textContent = tail || "";
  if (preserve) {
    nodes.auditLog.scrollTop = prevTop;
  } else {
    nodes.auditLog.scrollTop = nodes.auditLog.scrollHeight;
  }
}

export function clearAuditLog() {
  nodes.auditLog.textContent = "";
}
