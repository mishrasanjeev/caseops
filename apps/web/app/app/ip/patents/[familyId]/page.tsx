"use client";

import { useParams } from "next/navigation";

import { PatentFamilyDetail } from "@/components/ip/PatentFamilyWorkspace";

export default function PatentFamilyPage() {
  const { familyId } = useParams<{ familyId: string }>();
  return <PatentFamilyDetail familyId={familyId} />;
}
