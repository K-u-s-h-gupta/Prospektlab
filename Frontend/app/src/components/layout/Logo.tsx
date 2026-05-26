import React from 'react';

interface LogoProps {
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

export const Logo: React.FC<LogoProps> = ({ size = 24, className = '', style }) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{
        display: 'inline-block',
        verticalAlign: 'middle',
        ...style
      }}
    >
      {/* Glow effect definitions */}
      <defs>
        <linearGradient id="flask-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#06B6D4" />
          <stop offset="100%" stopColor="#818CF8" />
        </linearGradient>
        <linearGradient id="chart-grad-1" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#34D399" />
          <stop offset="100%" stopColor="#059669" />
        </linearGradient>
        <linearGradient id="chart-grad-2" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#38BDF8" />
          <stop offset="100%" stopColor="#1d4ed8" />
        </linearGradient>
        <filter id="glow-logo" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* The Beaker / Erlenmeyer Flask Outline */}
      <path
        d="M9 3H15M10 3V7.5L5.2 17.5C4.3 19.3 5.6 21 7.6 21H16.4C18.4 21 19.7 19.3 18.8 17.5L14 7.5V3"
        stroke="url(#flask-grad)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ filter: 'url(#glow-logo)' }}
      />

      {/* Candlestick 1 (Left) */}
      <line x1="8" y1="14.5" x2="8" y2="18.5" stroke="url(#chart-grad-1)" strokeWidth="1" strokeLinecap="round" />
      <rect x="7" y="15.5" width="2" height="2" rx="0.5" fill="url(#chart-grad-1)" />

      {/* Candlestick 2 (Middle) */}
      <line x1="12" y1="10" x2="12" y2="17.5" stroke="url(#chart-grad-1)" strokeWidth="1" strokeLinecap="round" />
      <rect x="11" y="11.5" width="2" height="4.5" rx="0.5" fill="url(#chart-grad-1)" />

      {/* Candlestick 3 (Right) */}
      <line x1="16" y1="7" x2="16" y2="13.5" stroke="url(#chart-grad-2)" strokeWidth="1" strokeLinecap="round" />
      <rect x="15" y="8" width="2" height="4" rx="0.5" fill="url(#chart-grad-2)" />
    </svg>
  );
};

export default Logo;
