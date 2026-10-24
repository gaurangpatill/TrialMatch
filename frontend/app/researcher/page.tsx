import type {Metadata} from "next";

import ResearcherDashboard from "./researcher-dashboard";

export const metadata: Metadata = {
  title: "Researcher workspace | TrialMatch",
  description: "Plan and compare modeled community outreach scenarios.",
};

export default function ResearcherPage() {
  return <ResearcherDashboard />;
}
