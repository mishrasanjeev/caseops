import { describe, expect, it } from "vitest";
import { diagnosticProblem, diagnosticRequestId, diagnosticRoute, diagnosticTransport } from "../../../tests/e2e/support/prod-failure-diagnostics";

describe("production failure metadata minimization", () => {
  it("categorizes authorized paths without retaining identifiers or queries", () => {
    expect(diagnosticRoute("https://api.caseops.ai/api/matters/private-client/attachments?token=secret", ["https://api.caseops.ai"]))
      .toBe("matter/attachment");
    expect(diagnosticRoute("https://caseops.ai/app/matters/private-client?email=private", ["https://caseops.ai"]))
      .toBe("web/app-navigation");
    expect(diagnosticRoute("https://accounts.google.com/sign-in?code=secret", ["https://caseops.ai"]))
      .toBeNull();
    expect(diagnosticRoute("https://api.caseops.ai/api/calendar/google/callback?code=secret", ["https://api.caseops.ai"]))
      .toBeNull();
    expect(diagnosticRoute("not a URL", ["https://caseops.ai"])).toBeNull();
  });
  it("retains only fixed problem types and validated request IDs", () => {
    const id = "5a5b40a1d7454dedb456398600bce991";
    expect(diagnosticProblem({ type: "database_lock_timeout", request_id: id, detail: "private legal content", instance: "/secret", token: "credential" }))
      .toEqual({ problemType: "database_lock_timeout", requestId: id });
    expect(diagnosticProblem({ type: "private legal content", request_id: "secret" }))
      .toEqual({ problemType: null, requestId: null });
    expect(diagnosticProblem(null)).toEqual({ problemType: null, requestId: null });
    expect(diagnosticRequestId("12345678-1234-1234-1234-123456789abc")).not.toBeNull();
    expect(diagnosticRequestId(`${id}\nprivate`)).toBeNull();
  });
  it("does not serialize arbitrary transport errors", () => {
    expect(diagnosticTransport("net::ERR_CONNECTION_RESET")).toBe("net::ERR_CONNECTION_RESET");
    expect(diagnosticTransport("request failed for https://private/?token=secret")).toBe("unclassified_transport_failure");
  });
});
