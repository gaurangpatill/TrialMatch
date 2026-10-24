import type {Metadata} from "next";

import {PatientPortal} from "./patient-portal";

export const metadata: Metadata = {
  title: "Patient Portal · TrialMatch",
  description: "Search recruiting Massachusetts studies and screen a synthetic profile.",
};

export default function PatientPage() {
  return <PatientPortal />;
}
