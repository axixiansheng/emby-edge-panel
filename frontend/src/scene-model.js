import { CubicBezierCurve3, Vector3 } from 'three';

export const TUBE_RADIUS = 0.055;
export const COLLAR_INNER_RADIUS = 0.084;

export function connections(count) {
  return Array.from({ length: count }, (_, i) => {
    const lane = i - (count - 1) / 2;
    const start = new Vector3(-1.1, lane * 0.24, 0);
    const end = new Vector3(1.22, lane * 0.82, 0);
    return {
      start,
      end,
      curve: new CubicBezierCurve3(
        start,
        new Vector3(-0.25, start.y + 0.65, 0.45),
        new Vector3(0.4, end.y + 0.65, 0.45),
        end,
      ),
    };
  });
}
