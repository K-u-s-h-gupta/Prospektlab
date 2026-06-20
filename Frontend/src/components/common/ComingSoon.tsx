import React from 'react';
import { Check, Bell, LucideIcon } from 'lucide-react';

interface ComingSoonProps {
  icon: LucideIcon;
  eyebrow: string;
  title: string;
  body: string;
  bullets: string[];
  onNotify?: () => void;
}

export const ComingSoon: React.FC<ComingSoonProps> = ({ icon: Icon, eyebrow, title, body, bullets, onNotify }) => {
  return (
    <div className="coming-soon animate-fade-in-up">
      <div className="coming-soon-ring">
        <Icon size={34} strokeWidth={1.8} color="var(--accent-cyan)" />
      </div>

      <div className="coming-soon-eyebrow">{eyebrow}</div>
      <h2 className="coming-soon-title">{title}</h2>
      <p className="coming-soon-body">{body}</p>

      <ul className="coming-soon-bullets">
        {bullets.map((b, i) => (
          <li key={i} className="coming-soon-bullet">
            <span className="coming-soon-bullet-icon"><Check size={13} strokeWidth={3} /></span>
            <span>{b}</span>
          </li>
        ))}
      </ul>

      {onNotify && (
        <button type="button" className="coming-soon-notify" onClick={onNotify}>
          <Bell size={14} /> Notify me when it&apos;s live
        </button>
      )}
    </div>
  );
};

export default ComingSoon;
