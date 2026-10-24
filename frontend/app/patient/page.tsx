import type {Metadata} from "next";

import {PatientPortal} from "./patient-portal";

export const metadata: Metadata = {
  title: "Participant Portal · TrialMatch",
  description: "Explore recruiting Massachusetts studies and compare fictional example information with published requirements.",
};

export default function PatientPage() {
  return <PatientPortal />;
}
