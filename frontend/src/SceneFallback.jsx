import { useId } from 'react';

export default function SceneFallback({ mode, nodeStates }) {
  const id = useId().replace(/:/g, '');
  const states =
    mode === 'auth' ? [1, 1, 1] : nodeStates.split(',').filter(Boolean).slice(0, 5).map(Number);
  return (
    <svg className="scene-fallback" viewBox="0 0 520 300" aria-hidden="true">
      <defs>
        <linearGradient id={id + 'silver'} x2="0.2" y2="1">
          <stop stopColor="#727f91" />
          <stop offset=".35" stopColor="#f9fcff" />
          <stop offset=".65" stopColor="#8c99ab" />
          <stop offset="1" stopColor="#dce7f1" />
        </linearGradient>
        <linearGradient id={id + 'ruby'} x2="1" y2="1">
          <stop stopColor="#ffd7d0" stopOpacity=".8" />
          <stop offset=".4" stopColor="#f44d39" stopOpacity=".65" />
          <stop offset="1" stopColor="#aa271f" />
        </linearGradient>
        <linearGradient id={id + 'glass'} x2="1" y2="1">
          <stop stopColor="#f5fcff" stopOpacity=".85" />
          <stop offset=".5" stopColor="#bdd8e8" stopOpacity=".4" />
          <stop offset="1" stopColor="#6f97bc" stopOpacity=".85" />
        </linearGradient>
      </defs>
      {states.map((online, i) => {
        const y = 150 + (i - (states.length - 1) / 2) * 58;
        return (
          <g key={i}>
            <path
              d={`M 153 ${150 + (i - (states.length - 1) / 2) * 17} C 245 90 305 ${y - 40} 368 ${y}`}
              fill="none"
              stroke={`url(#${id}silver)`}
              strokeWidth="9"
            />
            <rect
              x="364"
              y={y - 25}
              width="51"
              height="51"
              rx="4"
              fill={online ? `url(#${id}glass)` : '#7b818b'}
              stroke="#d6e8f3"
            />
            <path
              d={`M 368 ${y - 21} L 409 ${y - 21} L 409 ${y + 18}`}
              fill="none"
              stroke="#fff"
              strokeOpacity=".75"
            />
          </g>
        );
      })}
      <rect
        x="82"
        y="102"
        width="78"
        height="96"
        rx="7"
        fill={`url(#${id}ruby)`}
        stroke="#ffcbc2"
      />
      <path d="M 88 190 L 88 108 L 153 108" fill="none" stroke="#fff1ed" strokeWidth="2" />
    </svg>
  );
}
