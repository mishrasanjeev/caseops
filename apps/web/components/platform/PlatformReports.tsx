"use client";

import { useState } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";

import { PlatformFinancialReport, PlatformOverview } from "./PlatformFinancialReport";
import { PlatformActivity } from "./PlatformActivity";
import { PlatformGate } from "./PlatformGate";
import { PlatformShell } from "./PlatformShell";

const kinds = [
  ["activity", "Account activity"], ["overview", "Overview"], ["usage", "Usage"],
  ["profit", "Profit"], ["company-profitability", "Account profitability"], ["revenue", "Revenue"],
] as const;

export function PlatformReports() {
  const [kind, setKind] = useState<string>("activity");
  return <PlatformShell><PlatformGate><section className="min-w-0 space-y-5">
    <h1 className="text-2xl font-bold">Reports</h1>
    <Tabs value={kind} onValueChange={setKind} className="min-w-0">
      <TabsList aria-label="Platform report type" className="mb-5 flex h-auto w-full flex-wrap justify-start gap-1">
        {kinds.map(([value, label]) => <TabsTrigger value={value} key={value} className="min-h-10 whitespace-normal text-left">{label}</TabsTrigger>)}
      </TabsList>
      <TabsContent value="activity"><PlatformActivity /></TabsContent>
      <TabsContent value="overview"><PlatformOverview /></TabsContent>
      {(["usage", "profit", "company-profitability", "revenue"] as const).map((value) => <TabsContent key={value} value={value}><PlatformFinancialReport key={value} kind={value} /></TabsContent>)}
    </Tabs>
  </section></PlatformGate></PlatformShell>;
}
