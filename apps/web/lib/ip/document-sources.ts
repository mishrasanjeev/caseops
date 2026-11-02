import type { IpDocument } from "@/lib/api/endpoints";

/**
 * Whether the specialist source validator (`ip_specialist._source`) accepts
 * this document for a record: its only link is a direct link to the record's
 * own docket. GET /api/ip/documents?docket_id= also lists documents linked to
 * the docket's events and deadlines, which recordal, Madrid and
 * foreign-associate forms may cite but a specialist source may not.
 */
export function isSpecialistSourceDocument(document: IpDocument, docketId: string): boolean {
  return (
    !document.retirement
    && document.links.length === 1
    && document.links[0].target_type === "docket"
    && document.links[0].target_id === docketId
  );
}
