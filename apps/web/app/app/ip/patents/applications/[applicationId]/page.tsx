"use client";

import { useParams } from "next/navigation";

import { PatentApplicationDetail } from "@/components/ip/PatentApplicationWorkspace";

export default function PatentApplicationPage() {
  const params = useParams<{ applicationId: string }>();
  return <PatentApplicationDetail applicationId={params.applicationId} />;
}
