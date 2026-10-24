import {renderToStaticMarkup} from "react-dom/server";
import {describe, expect, it} from "vitest";

import type {TrialDetail, TrialSummary} from "@/lib/clinical-contracts";
import {PatientPortal, StudyDetailPanel, TrialCard} from "./patient-portal";

const summary: TrialSummary = {
  nct_id: "NCT01521741",
  title: "Prospective Screening for Breast Cancer-related Lymphedema: Analysis of Objective Measurements, Symptoms, Functionality, and Quality of Life Questionnaires",
  overall_status: "RECRUITING",
  conditions: ["Lymphedema", "Breast Cancer", "Arm Symptoms", "Quality of Life"],
  phases: ["NOT_APPLICABLE"],
  source_description: "The official study measures arm changes and symptoms during and after breast cancer treatment.",
  brief_summary: "The official study measures arm changes and symptoms during and after breast cancer treatment.",
  detailed_description: "Participants complete questionnaires and objective arm measurements during follow-up.",
  plain_language_summary: "Researchers are studying arm symptoms and swelling during and after breast cancer treatment.",
  minimum_age: "18 Years",
  maximum_age: null,
  sex: "FEMALE",
  locations: [],
  source_url: "https://clinicaltrials.gov/study/NCT01521741",
  retrieved_at: "2026-10-24T20:47:11Z",
  detail_status: "retrieved",
  screening_coverage_status: "partial",
};

const detail: TrialDetail = {
  ...summary,
  eligibility_criteria: "Confirmed diagnosis of breast cancer",
  contacts: [],
  detail_attempted_at: "2026-10-24T20:47:11Z",
  retrieval_source: "official_cache",
  retrieval_message: "Official study detail is available.",
  screening_coverage: {
    status: "partial",
    protocol_item_count: 2,
    accounted_item_count: 1,
    evaluable_criterion_count: 1,
    unsupported_protocol_requirement_count: 0,
    uncovered_protocol_requirement_count: 1,
    independently_verified: false,
    verification_method: null,
    reason: "Some published requirements still need review.",
  },
};

describe("participant study descriptions and comparison layout", () => {
  it("renders a plain-English card without overwhelming title or condition lists", () => {
    const html = renderToStaticMarkup(
      <TrialCard trial={summary} isSelected={false} selectionFull={false} onToggle={() => undefined} onOpen={() => undefined} />,
    );

    expect(html).toContain("Plain-English summary");
    expect(html).toContain("Researchers are studying arm symptoms");
    expect(html).toContain("+1 more");
    expect(html).toContain("line-clamp-2");
  });

  it("renders official brief and detailed text in expandable study details", () => {
    const html = renderToStaticMarkup(
      <StudyDetailPanel summary={summary} detail={detail} loading={false} error={null} onClose={() => undefined} onRefresh={() => undefined} />,
    );

    expect(html).toContain("Read the original technical description");
    expect(html).toContain("Official brief summary");
    expect(html).toContain("Official detailed description");
    expect(html).toContain("Participants complete questionnaires");
  });

  it("gives the desktop comparison content its own bounded keyboard-focusable scroller", () => {
    const html = renderToStaticMarkup(<PatientPortal />);

    expect(html).toContain("xl:sticky");
    expect(html).toContain("xl:max-h-[calc(100vh-6.25rem)]");
    expect(html).toContain("xl:min-h-0");
    expect(html).toContain("xl:overflow-y-auto");
    expect(html).toContain("tabindex=\"0\"");
    expect(html).toContain("Check published requirements");
    expect(html).toContain("Studies selected for review");
  });
});
