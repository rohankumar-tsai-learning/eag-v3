export type Domain = "energy" | "food";

export interface TimeSeriesEntry {
  timestamp: string;
  price: number;
  unit: string;
  source?: string;
  sentiment?: string;
}

export interface CommoditySeries {
  key: string;
  label: string;
  domain: Domain;
  entries: TimeSeriesEntry[];
}

export interface CrisisVault {
  commodities: Record<string, CommoditySeries>;
  updatedAt: string;
}

export interface MarketProbeItem {
  key: string;
  label: string;
  domain: Domain;
  price: number;
  unit: string;
  sentiment: string;
  source: string;
  timestamp: string;
  stale?: boolean;
}

export interface ProbeMetadata {
  usedGemini: boolean;
  throttled: boolean;
  cooldownRemainingSec: number;
  usedLocalFreshData: boolean;
  /** ISO timestamp of the newest data item (vault or live) */
  latestDataTs: string;
}

export interface MarketProbeResult {
  items: MarketProbeItem[];
  metadata: ProbeMetadata;
}

export interface DeltaItem {
  key: string;
  label: string;
  domain: Domain;
  currentPrice: number;
  previousPrice: number | null;
  deltaAbs: number | null;
  deltaPct: number | null;
}

export interface RiskMatrix {
  energy: "STABLE" | "ALERT" | "CRISIS";
  food: "STABLE" | "ALERT" | "CRISIS";
}

export interface AdvisoryAction {
  region: string;
  action: string;
  reason: string;
}

export interface UiDispatchPayload {
  generatedAt: string;
  probe: MarketProbeResult;
  deltas: DeltaItem[];
  risk: RiskMatrix;
  advisory: AdvisoryAction[];
}
