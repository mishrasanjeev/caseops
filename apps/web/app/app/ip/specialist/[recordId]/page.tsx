"use client";

import { use } from "react";

import { SpecialistDetail } from "@/components/ip/SpecialistWorkspace";

export default function SpecialistRecordPage({ params }: { params: Promise<{ recordId: string }> }) {
  const { recordId } = use(params);
  return <SpecialistDetail recordId={recordId} />;
}
