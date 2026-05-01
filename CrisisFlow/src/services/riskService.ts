import type { AdvisoryAction, DeltaItem, MarketProbeResult, RiskMatrix } from "../types.js";
import { getCommoditySeries } from "./vaultService.js";

function pctDelta(current: number, previous: number): number {
  if (previous === 0) {
    return 0;
  }
  return ((current - previous) / previous) * 100;
}

export function calculateDeltas(probe: MarketProbeResult): DeltaItem[] {
  return probe.items.map((item) => {
    const series = getCommoditySeries(item.key);
    const entries = series?.entries ?? [];
    const previous = entries.length >= 2 ? entries[entries.length - 2] : null;

    if (!previous) {
      return {
        key: item.key,
        label: item.label,
        domain: item.domain,
        currentPrice: item.price,
        previousPrice: null,
        deltaAbs: null,
        deltaPct: null
      };
    }

    const deltaAbs = item.price - previous.price;
    const deltaPct = pctDelta(item.price, previous.price);
    return {
      key: item.key,
      label: item.label,
      domain: item.domain,
      currentPrice: item.price,
      previousPrice: previous.price,
      deltaAbs,
      deltaPct
    };
  });
}

function scoreToRisk(score: number): "STABLE" | "ALERT" | "CRISIS" {
  if (score >= 2) {
    return "CRISIS";
  }
  if (score >= 1) {
    return "ALERT";
  }
  return "STABLE";
}

export function calculateRiskMatrix(deltas: DeltaItem[]): RiskMatrix {
  let energyScore = 0;
  let foodScore = 0;

  for (const delta of deltas) {
    if (delta.deltaPct === null) {
      continue;
    }
    const severe = delta.deltaPct >= 10;
    const moderate = delta.deltaPct >= 5;
    const isEnergy = delta.domain === "energy";

    if (severe) {
      if (isEnergy) {
        energyScore += 1;
      } else {
        foodScore += 1;
      }
    } else if (moderate) {
      if (isEnergy) {
        energyScore += 0.5;
      } else {
        foodScore += 0.5;
      }
    }
  }

  return {
    energy: scoreToRisk(energyScore),
    food: scoreToRisk(foodScore)
  };
}

export function buildAdvisoryActions(deltas: DeltaItem[]): AdvisoryAction[] {
  const actions: AdvisoryAction[] = [];

  for (const item of deltas) {
    if (item.deltaPct === null || item.deltaPct <= 10) {
      continue;
    }

    if (item.domain === "energy") {
      actions.push({
        region: "Energy Corridor",
        action: "Activate Energy Contingency",
        reason: `${item.label} is up ${item.deltaPct.toFixed(1)}%, signaling energy input pressure and potential downstream cost pass-through.`
      });
    }

    if (item.domain === "food") {
      actions.push({
        region: "Food Corridor",
        action: "Pre-position Procurement Hedges",
        reason: `${item.label} rose ${item.deltaPct.toFixed(1)}%, increasing food-system cost risk and requiring short-horizon procurement planning.`
      });
    }
  }

  if (actions.length === 0) {
    actions.push({
      region: "Global",
      action: "Maintain Strategic Reserves",
      reason: "No commodity exceeded the 10% hike trigger. Continue daily surveillance cycles."
    });
  }

  return actions;
}
