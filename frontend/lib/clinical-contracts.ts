export type TrialLocation = {
  facility: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
};

export type TrialSummary = {
  nct_id: string;
  title: string;
  overall_status: string;
  conditions: string[];
  phases: string[];
  minimum_age: string | null;
  maximum_age: string | null;
  sex: string | null;
  locations: TrialLocation[];
  source_url: string;
  retrieved_at: string;
};

export type TrialSearchResponse = {
  items: TrialSummary[];
  pagination: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
  };
  data_freshness: {
    retrieved_at: string | null;
    source: "ClinicalTrials.gov";
  };
};

export type CriterionStatus = "met" | "not_met" | "unknown";
export type ScreeningStatus = "potential_match" | "known_mismatch" | "unresolved";

export type MatchResponse = {
  profile_id: string;
  results: Array<{
    nct_id: string;
    title: string;
    screening_status: ScreeningStatus;
    criteria: Array<{
      criterion_id: string;
      classification: "inclusion" | "exclusion";
      status: CriterionStatus;
      original_text: string;
      explanation: string;
      source_url: string;
      extraction_uncertainty: string | null;
    }>;
    known_mismatches: string[];
    unresolved_requirements: string[];
    missing_questions: string[];
    source_url: string;
  }>;
  disclaimer: string;
  generated_at: string;
};

export type ApiError = {
  error?: {
    code?: string;
    message?: string;
    details?: Array<{field?: string | null; reason?: string}>;
    retryable?: boolean;
    request_id?: string;
  };
};
