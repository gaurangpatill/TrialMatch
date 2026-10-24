export type GeoProperties = {
  municipality: string;
  source_scope: string;
  ej_subset_population: number | null;
  population_unit: "persons";
  population_weighted_percent_minority_ej_subset: number | null;
  population_weighted_limited_english_household_percent_ej_subset: number | null;
  percent_unit: "percentage_points_0_to_100";
  population_weighted_mean_block_group_median_household_income_usd_ej_subset: number | null;
  income_statistic_label: string;
  ej_block_group_count: number;
  coordinate_resolution_status: "resolved" | "unresolved";
  coordinate_method: string;
  nearest_resolved_recruiting_site_distance_km: number | null;
  distinct_nearby_recruiting_nct_count: number | null;
  access_radius_km: number | null;
  access_distance_limitation: string | null;
};

export type GeoFeature = {
  type: "Feature";
  id: string;
  geometry: {type: "Point"; coordinates: [number, number]} | null;
  properties: GeoProperties;
};

export type GeoSummary = {
  observed_feature_count: number;
  resolved_feature_count: number;
  unresolved_feature_count: number;
  source_name: string;
  source_url: string;
  retrieved_at: string;
  source_filter: string;
  output_crs: string;
  coordinate_method: string;
  clinical_site_data_available: boolean;
  clinical_site_accepted_count: number | null;
  clinical_site_resolved_count: number | null;
  clinical_site_unresolved_count: number | null;
  clinical_site_deduplicated_count: number | null;
  clinical_site_quarantined_count: number | null;
};

export type GeoCollection = {
  type: "FeatureCollection";
  features: GeoFeature[];
  summary: GeoSummary;
};

export type ConstraintSatisfaction = {
  primal_validated: boolean;
  budget_satisfied: boolean;
  event_limit_satisfied: boolean;
  required_candidates_satisfied: boolean;
  exact_coverage_satisfied: boolean;
  all_satisfied: boolean;
};

export type BaselineResult = {
  strategy: "population_first_greedy" | "equity_first_greedy";
  selected_municipality_ids: string[];
  covered_community_ids: string[];
  total_events: number;
  total_cost: number;
  cost_unit: string;
  modeled_ej_subset_population_proxy_covered: number;
  modeled_outreach_coverage_objective: number;
  constraint_satisfaction: ConstraintSatisfaction;
};

export type OptimizeResponse = {
  status: "optimal" | "feasible" | "infeasible" | "unbounded" | "solver_error";
  selected_locations: Array<{municipality_id: string; latitude: number; longitude: number}>;
  covered_municipality_ids: string[];
  covered_municipality_count: number;
  modeled_outreach_coverage_objective: number;
  modeled_ej_subset_population_proxy_covered: number;
  total_events: number;
  total_cost: number;
  cost_unit: string;
  solver: {name: string; version: string; native_status: number | null; message: string; mip_gap: number | null};
  baselines: BaselineResult[];
  constraint_satisfaction: ConstraintSatisfaction;
  assumptions: string[];
  limitations: string[];
  scenario_construction: {
    included_municipality_count: number;
    excluded_municipality_count: number;
    excluded_unresolved_point_count: number;
    excluded_null_population_count: number;
    excluded_missing_equity_indicator_count: number;
    aggregate_source_count: number;
    point_source: string;
    equity_indicator: string;
    equity_normalization_method: string;
    equity_interpretation: string;
    scenario_label: string;
    event_cost_assumption: string;
    assumptions: string[];
  };
  provenance: {
    source_name: string;
    source_url: string;
    source_filter: string;
    aggregate_retrieved_at: string;
    point_retrieved_at: string;
    aggregate_source_record_count: number;
    municipality_aggregate_count: number;
    coordinate_crs: string;
    coordinate_method: string;
    runtime_massgis_fetch: false;
  };
  generated_at: string;
};
