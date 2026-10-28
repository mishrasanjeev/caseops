// Fixed local test adapter for the actual pinned Next child-process worker.
exports.probe = async target => {
  const fixture = await import('./host-node-trust-fixture.mjs');
  return fixture.probe(target);
};
