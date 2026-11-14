import assert from 'node:assert/strict';
import { decodeAgenda } from '../src/domain/contracts.ts';

export function nativeCalendarRowFields(raw, day, dayLabel) {
  assert.ok(typeof dayLabel === 'string' && dayLabel.length > 0);
  const [event] = decodeAgenda({ range_from: day, range_to: day, events: [raw] }, day);
  return [event.title, `${event.matter.matter_code} · ${event.matter.title}`,
    [dayLabel, event.kind.replaceAll('_', ' '), event.time_status === 'exact'
      ? [event.hearing_time, event.timezone || 'Timezone not supplied'].filter(Boolean).join(' ')
      : event.session_label || 'Time not published', event.detail, event.ip_docket_id ? 'IP docket' : null].filter(Boolean).join(' · ')];
}

export function admitV1SegmentPresentation(c) {
  const binding = c.segmentPresentation;
  const observed = binding?.selectors ?? c.fixture.v1?.nativeSelectors;
  assert.equal(observed?.observed, true, 'OBSERVED_V1_SEGMENTS_REQUIRED');
  assert.equal(observed.udid, c.fixture.udid, 'SEGMENT_DEVICE_MISMATCH');
  assert.deepEqual(observed.buildReceipt, c.fixture.buildReceipt, 'SEGMENT_BUILD_MISMATCH');
  if (binding) {
    assert.match(binding.sourceSha || '', /^[a-f0-9]{40}$/, 'SEGMENT_SOURCE_REQUIRED');
    assert.equal(binding.sourceSha, c.fixture.binarySourceSha, 'SEGMENT_SOURCE_MISMATCH');
    assert.equal(binding.platform, c.platform, 'SEGMENT_PLATFORM_MISMATCH');
  }
  return observed;
}
