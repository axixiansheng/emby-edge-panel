import { test } from 'node:test';
import assert from 'node:assert/strict';
import { connections, TUBE_RADIUS, COLLAR_INNER_RADIUS } from '../src/scene-model.js';

test('slider aperture stays outside the metal tube', () => {
  assert.ok(COLLAR_INNER_RADIUS - TUBE_RADIUS > 0.02);
});

test('moving collars clear other cables and collars throughout a complete cycle', () => {
  const outerRadius = COLLAR_INNER_RADIUS + 0.056;
  for (const count of [2, 3, 4, 5]) {
    const links = connections(count);
    const paths = links.map(({ curve }) => curve.getSpacedPoints(200));
    for (let step = 0; step <= 200; step++) {
      const positions = links.map(({ curve }, i) =>
        curve.getPointAt(0.12 + ((step / 200 + i * 0.27) % 1) * 0.76),
      );
      for (let a = 0; a < count; a++) {
        for (let b = 0; b < count; b++) {
          if (a === b) continue;
          for (const point of paths[b])
            assert.ok(positions[a].distanceTo(point) > outerRadius + TUBE_RADIUS);
          assert.ok(positions[a].distanceTo(positions[b]) > outerRadius * 2);
        }
      }
    }
  }
});

for (const count of [1, 2, 3, 4, 5]) {
  test(`${count} connection paths have non-intersecting metal surfaces`, () => {
    const paths = connections(count).map(({ curve }) => curve.getSpacedPoints(200));
    let minimum = Infinity;
    for (let a = 0; a < paths.length; a++) {
      for (let b = a + 1; b < paths.length; b++) {
        for (const p of paths[a])
          for (const q of paths[b]) minimum = Math.min(minimum, p.distanceTo(q));
      }
    }
    assert.ok(minimum > TUBE_RADIUS * 2 + 0.035, `Insufficient clearance: ${minimum}`);
  });
}
