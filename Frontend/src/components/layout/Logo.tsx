import React, { useId } from 'react';

interface LogoProps {
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

export const Logo: React.FC<LogoProps> = ({ size = 24, className = '', style }) => {
  const id = useId().replace(/:/g, '');
  const haloGradient = `${id}-halo-gradient`;
  const ringGradient = `${id}-ring-gradient`;
  const diskGradient = `${id}-disk-gradient`;
  const glowFilter = `${id}-glow`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{
        display: 'inline-block',
        verticalAlign: 'middle',
        ...style
      }}
    >
      <defs>
        <radialGradient id={haloGradient} cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(31.8 31.4) rotate(90) scale(28 28)">
          <stop offset="0" stopColor="#EFF6FF" />
          <stop offset="0.28" stopColor="#60A5FA" />
          <stop offset="0.62" stopColor="#2563EB" stopOpacity="0.55" />
          <stop offset="1" stopColor="#020617" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={ringGradient} x1="14" y1="17" x2="50" y2="47" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#DBEAFE" />
          <stop offset="0.35" stopColor="#60A5FA" />
          <stop offset="0.68" stopColor="#2563EB" />
          <stop offset="1" stopColor="#93C5FD" />
        </linearGradient>
        <linearGradient id={diskGradient} x1="3" y1="43" x2="61" y2="19" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#1D4ED8" stopOpacity="0" />
          <stop offset="0.18" stopColor="#2563EB" />
          <stop offset="0.42" stopColor="#BFDBFE" />
          <stop offset="0.6" stopColor="#60A5FA" />
          <stop offset="0.82" stopColor="#1D4ED8" />
          <stop offset="1" stopColor="#1D4ED8" stopOpacity="0" />
        </linearGradient>
        <filter id={glowFilter} x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="2.3" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      <rect x="4" y="4" width="56" height="56" rx="16" fill="#050B18" />
      <rect x="4.75" y="4.75" width="54.5" height="54.5" rx="15.25" stroke="#93C5FD" strokeOpacity="0.25" strokeWidth="1.5" />
      <circle cx="32" cy="32" r="25" fill={`url(#${haloGradient})`} opacity="0.32" />
      <circle cx="32" cy="32" r="14.4" stroke={`url(#${ringGradient})`} strokeWidth="5.6" opacity="0.98" filter={`url(#${glowFilter})`} />
      <circle cx="32" cy="32" r="10.6" fill="#020617" stroke="#DBEAFE" strokeOpacity="0.35" strokeWidth="1" />
      <path d="M7.5 43.2C18.2 36.2 29.3 31 43.2 26.4C49.5 24.3 54.6 22.3 59 19.8" stroke={`url(#${diskGradient})`} strokeWidth="5.1" strokeLinecap="round" opacity="0.98" filter={`url(#${glowFilter})`} />
      <path d="M6.5 44.4C18.7 39.9 31.2 35.2 58.2 18.8" stroke="#BFDBFE" strokeWidth="1.15" strokeLinecap="round" opacity="0.82" />
      <path d="M8.5 42.7C20.9 37.9 34 31.1 56.5 22.2" stroke="#1D4ED8" strokeWidth="1.8" strokeLinecap="round" opacity="0.75" />
      <circle cx="22" cy="19" r="0.75" fill="#DBEAFE" opacity="0.6" />
      <circle cx="45" cy="16" r="0.55" fill="#60A5FA" opacity="0.55" />
      <circle cx="16" cy="29" r="0.45" fill="#93C5FD" opacity="0.52" />
    </svg>
  );
};

export default Logo;
