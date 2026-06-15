import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain, ArrowLeft, Mail, MapPin, Clock, Send, CheckCircle,
  MessageSquare, Twitter, Linkedin, Github, Globe, Shield,
  Activity, Radio, ChevronRight, Sparkles, Wifi, AlertCircle
} from 'lucide-react';

/* ─────────────────────────────────────────────
   TYPES
───────────────────────────────────────────── */
interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  opacity: number;
  pulse: number;
  pulseSpeed: number;
}

interface FormState {
  name: string;
  email: string;
  subject: string;
  message: string;
}

interface FormErrors {
  name?: string;
  email?: string;
  subject?: string;
  message?: string;
}

/* ─────────────────────────────────────────────
   CONTACT DATA
───────────────────────────────────────────── */
const CONTACT_CHANNELS = [
  {
    icon: Mail,
    label: 'Email',
    value: 'hello@prospektlab.com',
    sub: 'Response in under 2 hours',
    color: '#38BDF8',
    href: 'mailto:hello@prospektlab.com'
  },
  {
    icon: MapPin,
    label: 'HQ',
    value: 'Bengaluru, India',
    sub: 'HSR Layout Sector 7',
    color: '#818CF8',
    href: '#'
  },
  {
    icon: Clock,
    label: 'Hours',
    value: 'Mon — Sat',
    sub: '9:00 AM — 8:00 PM IST',
    color: '#34D399',
    href: '#'
  },
  {
    icon: Radio,
    label: 'Status',
    value: 'All Systems Online',
    sub: 'API latency: 42ms',
    color: '#F59E0B',
    href: '#'
  }
];

const SOCIAL_LINKS = [
  { icon: Twitter, label: 'Twitter', color: '#38BDF8', href: 'https://twitter.com' },
  { icon: Linkedin, label: 'LinkedIn', color: '#818CF8', href: 'https://linkedin.com' },
  { icon: Github, label: 'GitHub', color: '#94A3B8', href: 'https://github.com' },
  { icon: Globe, label: 'Discord', color: '#A78BFA', href: '#' }
];

const SUBJECT_OPTIONS = [
  'Product Inquiry',
  'Partnership',
  'Bug Report',
  'Feature Request',
  'Billing',
  'Media',
  'Other'
];

/* ─────────────────────────────────────────────
   CANVAS NETWORK BACKGROUND
───────────────────────────────────────────── */
const NetworkCanvas: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mouseRef = useRef({ x: -1000, y: -1000 });
  const particlesRef = useRef<Particle[]>([]);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio, 2);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = window.innerWidth + 'px';
      canvas.style.height = window.innerHeight + 'px';
      ctx.scale(dpr, dpr);
    };
    resize();

    const count = Math.min(80, Math.floor((window.innerWidth * window.innerHeight) / 18000));
    particlesRef.current = Array.from({ length: count }, () => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      radius: Math.random() * 1.5 + 0.5,
      opacity: Math.random() * 0.4 + 0.1,
      pulse: Math.random() * Math.PI * 2,
      pulseSpeed: Math.random() * 0.02 + 0.01
    }));

    const handleMouse = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY };
    };
    window.addEventListener('mousemove', handleMouse, { passive: true });

    const animate = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      ctx.clearRect(0, 0, w, h);
      const particles = particlesRef.current;
      const mouse = mouseRef.current;

      // Update and draw particles
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.pulse += p.pulseSpeed;

        if (p.x < 0) p.x = w;
        if (p.x > w) p.x = 0;
        if (p.y < 0) p.y = h;
        if (p.y > h) p.y = 0;

        const pulseRadius = p.radius + Math.sin(p.pulse) * 0.5;
        const alpha = p.opacity + Math.sin(p.pulse) * 0.1;

        ctx.beginPath();
        ctx.arc(p.x, p.y, pulseRadius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(56, 189, 248, ${Math.max(0, alpha)})`;
        ctx.fill();

        // Connect to mouse
        const dx = mouse.x - p.x;
        const dy = mouse.y - p.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 220) {
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(mouse.x, mouse.y);
          ctx.strokeStyle = `rgba(56, 189, 248, ${0.15 * (1 - dist / 220)})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }

        // Connect nearby particles
        for (let j = i + 1; j < particles.length; j++) {
          const p2 = particles[j];
          const dx2 = p2.x - p.x;
          const dy2 = p2.y - p.y;
          const d2 = Math.sqrt(dx2 * dx2 + dy2 * dy2);
          if (d2 < 140) {
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = `rgba(129, 140, 248, ${0.08 * (1 - d2 / 140)})`;
            ctx.lineWidth = 0.4;
            ctx.stroke();
          }
        }
      }

      // Mouse glow
      if (mouse.x > 0) {
        const gradient = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, 120);
        gradient.addColorStop(0, 'rgba(56, 189, 248, 0.06)');
        gradient.addColorStop(1, 'rgba(56, 189, 248, 0)');
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(mouse.x, mouse.y, 120, 0, Math.PI * 2);
        ctx.fill();
      }

      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);

    const handleResize = () => {
      resize();
    };
    window.addEventListener('resize', handleResize, { passive: true });

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener('mousemove', handleMouse);
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none'
      }}
    />
  );
};

/* ─────────────────────────────────────────────
   3D TILT CARD
───────────────────────────────────────────── */
const TiltCard: React.FC<{
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}> = ({ children, style, className }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [transform, setTransform] = useState('perspective(800px) rotateX(0deg) rotateY(0deg)');
  const [glare, setGlare] = useState({ x: 50, y: 50, opacity: 0 });

  const handleMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    const rotateX = (y - 0.5) * -12;
    const rotateY = (x - 0.5) * 12;
    setTransform(`perspective(800px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`);
    setGlare({ x: x * 100, y: y * 100, opacity: 0.12 });
  }, []);

  const handleLeave = useCallback(() => {
    setTransform('perspective(800px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)');
    setGlare({ x: 50, y: 50, opacity: 0 });
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      style={{
        transform,
        transition: 'transform 0.15s ease-out',
        transformStyle: 'preserve-3d',
        position: 'relative',
        overflow: 'hidden',
        ...style
      }}
    >
      {children}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(circle at ${glare.x}% ${glare.y}%, rgba(255,255,255,0.15), transparent 60%)`,
          opacity: glare.opacity,
          pointerEvents: 'none',
          transition: 'opacity 0.15s ease-out',
          borderRadius: 'inherit'
        }}
      />
    </div>
  );
};

/* ─────────────────────────────────────────────
   MAGNETIC BUTTON
───────────────────────────────────────────── */
const MagneticButton: React.FC<{
  children: React.ReactNode;
  onClick?: () => void;
  type?: 'button' | 'submit';
  disabled?: boolean;
  style?: React.CSSProperties;
}> = ({ children, onClick, type = 'button', disabled, style }) => {
  const ref = useRef<HTMLButtonElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  const handleMove = useCallback((e: React.MouseEvent<HTMLButtonElement>) => {
    const el = ref.current;
    if (!el || disabled) return;
    const rect = el.getBoundingClientRect();
    const x = (e.clientX - rect.left - rect.width / 2) * 0.25;
    const y = (e.clientY - rect.top - rect.height / 2) * 0.25;
    setOffset({ x, y });
  }, [disabled]);

  const handleLeave = useCallback(() => {
    setOffset({ x: 0, y: 0 });
  }, []);

  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled}
      onClick={onClick}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      style={{
        transform: `translate(${offset.x}px, ${offset.y}px)`,
        transition: 'transform 0.2s cubic-bezier(0.25, 0.46, 0.45, 0.94), box-shadow 0.2s, filter 0.2s',
        ...style
      }}
    >
      {children}
    </button>
  );
};

/* ─────────────────────────────────────────────
   SUCCESS PARTICLES
───────────────────────────────────────────── */
const SuccessParticles: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;
    const dpr = Math.min(window.devicePixelRatio, 2);
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const particles = Array.from({ length: 60 }, () => ({
      x: w / 2,
      y: h / 2,
      vx: (Math.random() - 0.5) * 12,
      vy: (Math.random() - 0.5) * 12 - 4,
      life: 1,
      decay: Math.random() * 0.015 + 0.008,
      size: Math.random() * 4 + 2,
      color: ['#38BDF8', '#34D399', '#818CF8', '#A78BFA', '#F59E0B'][Math.floor(Math.random() * 5)]
    }));

    const animate = () => {
      ctx.clearRect(0, 0, w, h);
      let alive = false;
      for (const p of particles) {
        if (p.life <= 0) continue;
        alive = true;
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.25; // gravity
        p.life -= p.decay;
        p.size *= 0.98;

        ctx.beginPath();
        ctx.arc(p.x, p.y, Math.max(0, p.size), 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = Math.max(0, p.life);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (alive) {
        rafRef.current = requestAnimationFrame(animate);
      }
    };
    rafRef.current = requestAnimationFrame(animate);

    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 10
      }}
    />
  );
};

/* ─────────────────────────────────────────────
   MAIN COMPONENT
───────────────────────────────────────────── */
const ContactUs: React.FC = () => {
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>({ name: '', email: '', subject: '', message: '' });
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [activeField, setActiveField] = useState<string | null>(null);
  const [messageLength, setMessageLength] = useState(0);
  const [typingSignal, setTypingSignal] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);

  // Typing signal animation
  useEffect(() => {
    if (activeField === 'message' && messageLength > 0) {
      const id = setInterval(() => {
        setTypingSignal(v => (v + 1) % 4);
      }, 200);
      return () => clearInterval(id);
    } else {
      setTypingSignal(0);
    }
  }, [activeField, messageLength]);

  const validate = useCallback((): boolean => {
    const newErrors: FormErrors = {};
    if (!form.name.trim()) newErrors.name = 'Name is required';
    else if (form.name.trim().length < 2) newErrors.name = 'Name is too short';

    if (!form.email.trim()) newErrors.email = 'Email is required';
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) newErrors.email = 'Invalid email address';

    if (!form.subject) newErrors.subject = 'Select a subject';

    if (!form.message.trim()) newErrors.message = 'Message is required';
    else if (form.message.trim().length < 10) newErrors.message = 'Message must be at least 10 characters';

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [form]);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setIsSubmitting(true);
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 2000));
    setIsSubmitting(false);
    setIsSuccess(true);

    // Store in localStorage for demo
    const submissions = JSON.parse(localStorage.getItem('pl_contact_submissions') || '[]');
    submissions.push({ ...form, timestamp: new Date().toISOString() });
    localStorage.setItem('pl_contact_submissions', JSON.stringify(submissions));
  }, [form, validate]);

  const handleChange = useCallback((field: keyof FormState, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }));
    if (field === 'message') setMessageLength(value.length);
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: undefined }));
    }
  }, [errors]);

  const resetForm = useCallback(() => {
    setForm({ name: '', email: '', subject: '', message: '' });
    setErrors({});
    setIsSuccess(false);
    setMessageLength(0);
  }, []);

  const signalBars = [
    { active: typingSignal >= 1, height: 4, delay: '0s' },
    { active: typingSignal >= 2, height: 8, delay: '0.1s' },
    { active: typingSignal >= 3, height: 12, delay: '0.2s' },
    { active: typingSignal >= 1, height: 6, delay: '0.3s' }
  ];

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-deep)', position: 'relative', overflow: 'hidden' }}>
      {/* Global styles */}
      <style>{`
        @keyframes fadeInUp { from { opacity:0; transform:translateY(24px); } to { opacity:1; transform:translateY(0); } }
        @keyframes fadeInScale { from { opacity:0; transform:scale(0.9); } to { opacity:1; transform:scale(1); } }
        @keyframes slideInRight { from { opacity:0; transform:translateX(30px); } to { opacity:1; transform:translateX(0); } }
        @keyframes pulseGlow { 0%,100% { box-shadow: 0 0 12px rgba(56,189,248,0.15); } 50% { box-shadow: 0 0 24px rgba(56,189,248,0.35); } }
        @keyframes float { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-8px); } }
        @keyframes ripple { 0% { transform:scale(0.8); opacity:1; } 100% { transform:scale(2.2); opacity:0; } }
        @keyframes shake { 0%,100% { transform:translateX(0); } 20% { transform:translateX(-4px); } 40% { transform:translateX(4px); } 60% { transform:translateX(-3px); } 80% { transform:translateX(3px); } }
        @keyframes spin { to { transform:rotate(360deg); } }
        @keyframes signalBar { 0%,100% { transform:scaleY(0.3); } 50% { transform:scaleY(1); } }
        @keyframes orbit { from { transform:rotate(0deg) translateX(6px) rotate(0deg); } to { transform:rotate(360deg) translateX(6px) rotate(-360deg); } }
        @keyframes borderRotate { from { --angle: 0deg; } to { --angle: 360deg; } }
        .contact-animate { animation: fadeInUp 0.6s ease forwards; }
        .contact-animate-delay-1 { animation: fadeInUp 0.6s ease 0.1s forwards; opacity:0; }
        .contact-animate-delay-2 { animation: fadeInUp 0.6s ease 0.2s forwards; opacity:0; }
        .contact-animate-delay-3 { animation: fadeInUp 0.6s ease 0.3s forwards; opacity:0; }
        .contact-animate-delay-4 { animation: fadeInUp 0.6s ease 0.4s forwards; opacity:0; }
        .contact-animate-scale { animation: fadeInScale 0.5s ease forwards; }
        .contact-animate-slide { animation: slideInRight 0.5s ease forwards; }
        .contact-shake { animation: shake 0.4s ease; }
        .contact-float { animation: float 4s ease-in-out infinite; }
        .contact-pulse { animation: pulseGlow 2.5s infinite; }
        .contact-orbit { animation: orbit 8s linear infinite; }
        .contact-signal-bar { animation: signalBar 0.4s ease-in-out infinite; }
        .contact-input-error { border-color: var(--loss) !important; box-shadow: 0 0 0 2px rgba(251, 113, 133, 0.1) !important; }
        .contact-input-focus { border-color: var(--accent-cyan) !important; box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.1) !important; }
        @media (max-width: 768px) {
          .contact-split { flex-direction: column !important; }
          .contact-grid-2 { grid-template-columns: 1fr !important; }
          .contact-cards-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
        @media (max-width: 480px) {
          .contact-cards-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>

      <NetworkCanvas />

      {/* ─── NAVBAR ─── */}
      <nav style={{ position: 'sticky', top: 0, zIndex: 50, background: 'rgba(3,7,18,0.88)', backdropFilter: 'blur(20px)', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '13px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
          <div onClick={() => navigate('/')} style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', flexShrink: 0 }}>
            <div style={{ background: 'var(--gradient-brand)', borderRadius: 9, padding: '6px', display: 'flex', boxShadow: '0 0 12px rgba(56,189,248,0.2)' }}>
              <Brain size={18} color="#0f172a" />
            </div>
            <span style={{ fontWeight: 800, fontSize: 17, letterSpacing: '-0.5px' }} className="text-gradient">ProspektLab</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              onClick={() => navigate('/')}
              style={{ background: 'none', border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)', padding: '7px 16px', borderRadius: 8, fontSize: 13, cursor: 'pointer', transition: 'all 0.15s', display: 'flex', alignItems: 'center', gap: 6 }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-cyan)'; e.currentTarget.style.color = 'var(--accent-cyan)'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-subtle)'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
            >
              <ArrowLeft size={14} /> Back
            </button>
          </div>
        </div>
      </nav>

      {/* ─── HERO SECTION ─── */}
      <section style={{ position: 'relative', zIndex: 1, padding: 'clamp(48px, 6vw, 80px) 24px clamp(32px, 4vw, 48px)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', textAlign: 'center' }}>
          <div className="contact-animate" style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(56,189,248,0.07)', border: '1px solid rgba(56,189,248,0.18)', color: 'var(--accent-cyan)', padding: '6px 16px', borderRadius: 999, fontSize: 12, fontWeight: 700, marginBottom: 20, letterSpacing: '0.05em' }}>
            <Wifi size={13} /> LIVE CONNECTION
          </div>
          <h1 className="contact-animate-delay-1" style={{ fontSize: 'clamp(32px, 5vw, 56px)', fontWeight: 900, lineHeight: 1.05, letterSpacing: '-1.5px', marginBottom: 18 }}>
            Let's build the
            <br />
            <span style={{ background: 'var(--gradient-brand)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>future of investing.</span>
          </h1>
          <p className="contact-animate-delay-2" style={{ fontSize: 'clamp(15px, 1.6vw, 18px)', color: 'var(--text-secondary)', lineHeight: 1.7, maxWidth: 560, margin: '0 auto' }}>
            Whether you're a user with feedback, a partner with a vision, or an investor with conviction — we'd love to hear from you.
          </p>
        </div>
      </section>

      {/* ─── MAIN CONTENT ─── */}
      <section style={{ position: 'relative', zIndex: 1, padding: '0 24px clamp(60px, 8vw, 100px)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', gap: 'clamp(24px, 4vw, 48px)' }} className="contact-split">

          {/* LEFT: Contact Info Cards */}
          <div style={{ flex: '1 1 380px', maxWidth: 420, display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Info Cards */}
            <div className="contact-cards-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
              {CONTACT_CHANNELS.map((ch, i) => (
                <TiltCard
                  key={ch.label}
                  className={`contact-animate-delay-${i + 1}`}
                  style={{
                    background: 'rgba(15, 23, 42, 0.5)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 16,
                    padding: '20px 16px',
                    cursor: ch.href.startsWith('mailto') || ch.href.startsWith('http') ? 'pointer' : 'default',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                    minHeight: 130
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ width: 38, height: 38, borderRadius: 10, background: `${ch.color}15`, border: `1px solid ${ch.color}30`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <ch.icon size={18} color={ch.color} />
                    </div>
                    {ch.label === 'Status' && (
                      <div className="contact-orbit" style={{ width: 8, height: 8, borderRadius: '50%', background: ch.color, boxShadow: `0 0 8px ${ch.color}80` }} />
                    )}
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>{ch.label}</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 2 }}>{ch.value}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>{ch.sub}</div>
                  </div>
                </TiltCard>
              ))}
            </div>

            {/* Social Links */}
            <div className="contact-animate-delay-3" style={{ background: 'rgba(15, 23, 42, 0.4)', border: '1px solid var(--border-subtle)', borderRadius: 16, padding: 24 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 16 }}>Connect With Us</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {SOCIAL_LINKS.map((social) => (
                  <a
                    key={social.label}
                    href={social.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      background: 'rgba(15, 23, 42, 0.6)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 10,
                      padding: '10px 14px',
                      textDecoration: 'none',
                      transition: 'all 0.2s ease',
                      cursor: 'pointer'
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.borderColor = `${social.color}50`;
                      e.currentTarget.style.background = `${social.color}10`;
                      e.currentTarget.style.transform = 'translateY(-2px)';
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.borderColor = 'var(--border-subtle)';
                      e.currentTarget.style.background = 'rgba(15, 23, 42, 0.6)';
                      e.currentTarget.style.transform = 'translateY(0)';
                    }}
                  >
                    <social.icon size={16} color={social.color} />
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{social.label}</span>
                  </a>
                ))}
              </div>
            </div>

            {/* Trust Badge */}
            <div className="contact-animate-delay-4 contact-float" style={{ background: 'linear-gradient(135deg, rgba(56,189,248,0.06), rgba(129,140,248,0.04))', border: '1px solid rgba(56,189,248,0.15)', borderRadius: 16, padding: 20, display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{ width: 44, height: 44, borderRadius: 12, background: 'rgba(52,211,153,0.1)', border: '1px solid rgba(52,211,153,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <Shield size={20} color="var(--profit)" />
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 2 }}>Enterprise-grade Privacy</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>Your message is encrypted in transit. We never share your data with third parties.</div>
              </div>
            </div>
          </div>

          {/* RIGHT: Contact Form */}
          <div style={{ flex: '1 1 480px', maxWidth: 600, position: 'relative' }}>
            {isSuccess ? (
              <div className="contact-animate-scale" style={{ background: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(52,211,153,0.25)', borderRadius: 20, padding: 'clamp(32px, 4vw, 48px)', textAlign: 'center', position: 'relative', overflow: 'hidden' }}>
                <SuccessParticles />
                <div style={{ position: 'relative', zIndex: 2 }}>
                  <div style={{ width: 72, height: 72, borderRadius: '50%', background: 'rgba(52,211,153,0.1)', border: '2px solid rgba(52,211,153,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 20px', animation: 'pulseGlow 2s infinite' }}>
                    <CheckCircle size={32} color="var(--profit)" />
                  </div>
                  <h2 style={{ fontSize: 'clamp(22px, 3vw, 28px)', fontWeight: 800, marginBottom: 12, letterSpacing: '-0.5px' }}>
                    Message Received
                  </h2>
                  <p style={{ fontSize: 15, color: 'var(--text-secondary)', lineHeight: 1.65, maxWidth: 400, margin: '0 auto 24px' }}>
                    Thanks for reaching out, <strong style={{ color: 'var(--text-primary)' }}>{form.name}</strong>. We've received your message and will respond within 2 hours during business hours.
                  </p>
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
                    <MagneticButton
                      onClick={resetForm}
                      style={{
                        background: 'var(--gradient-brand)',
                        color: '#0f172a',
                        border: 'none',
                        padding: '12px 24px',
                        borderRadius: 10,
                        fontSize: 14,
                        fontWeight: 700,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8
                      }}
                    >
                      <MessageSquare size={16} /> Send Another
                    </MagneticButton>
                    <button
                      onClick={() => navigate('/')}
                      style={{
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid var(--border-subtle)',
                        color: 'var(--text-secondary)',
                        padding: '12px 24px',
                        borderRadius: 10,
                        fontSize: 14,
                        fontWeight: 600,
                        cursor: 'pointer',
                        transition: 'all 0.2s'
                      }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--border-hover)'; e.currentTarget.style.color = 'var(--text-primary)'; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-subtle)'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
                    >
                      Back to Home
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <form
                ref={formRef}
                onSubmit={handleSubmit}
                className="contact-animate-delay-2"
                style={{ background: 'rgba(15, 23, 42, 0.5)', border: '1px solid var(--border-subtle)', borderRadius: 20, padding: 'clamp(24px, 3vw, 36px)', position: 'relative' }}
              >
                {/* Form Header */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
                  <div>
                    <h2 style={{ fontSize: 20, fontWeight: 800, marginBottom: 4, letterSpacing: '-0.3px' }}>Send a Message</h2>
                    <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>All fields are required. We read every message.</div>
                  </div>
                  {/* Live typing indicator */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(3,7,18,0.6)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '6px 12px' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 14 }}>
                      {signalBars.map((bar, i) => (
                        <div
                          key={i}
                          style={{
                            width: 3,
                            height: bar.height,
                            borderRadius: 2,
                            background: bar.active ? 'var(--accent-cyan)' : 'var(--text-muted)',
                            opacity: bar.active ? 1 : 0.3,
                            transition: 'all 0.2s ease',
                            transform: bar.active ? 'scaleY(1)' : 'scaleY(0.3)'
                          }}
                        />
                      ))}
                    </div>
                    <span style={{ fontSize: 11, color: activeField === 'message' && messageLength > 0 ? 'var(--accent-cyan)' : 'var(--text-muted)', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                      {activeField === 'message' && messageLength > 0 ? 'TRANSMITTING' : 'STANDBY'}
                    </span>
                  </div>
                </div>

                {/* Name & Email */}
                <div className="contact-grid-2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
                      Name <span style={{ color: 'var(--loss)' }}>*</span>
                    </label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={e => handleChange('name', e.target.value)}
                      onFocus={() => setActiveField('name')}
                      onBlur={() => setActiveField(null)}
                      placeholder="Your name"
                      className={errors.name ? 'contact-input-error' : activeField === 'name' ? 'contact-input-focus' : ''}
                      style={{ width: '100%', padding: '12px 14px', fontSize: 14 }}
                    />
                    {errors.name && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 6, fontSize: 11, color: 'var(--loss)', fontWeight: 500 }}>
                        <AlertCircle size={12} /> {errors.name}
                      </div>
                    )}
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
                      Email <span style={{ color: 'var(--loss)' }}>*</span>
                    </label>
                    <input
                      type="email"
                      value={form.email}
                      onChange={e => handleChange('email', e.target.value)}
                      onFocus={() => setActiveField('email')}
                      onBlur={() => setActiveField(null)}
                      placeholder="you@company.com"
                      className={errors.email ? 'contact-input-error' : activeField === 'email' ? 'contact-input-focus' : ''}
                      style={{ width: '100%', padding: '12px 14px', fontSize: 14 }}
                    />
                    {errors.email && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 6, fontSize: 11, color: 'var(--loss)', fontWeight: 500 }}>
                        <AlertCircle size={12} /> {errors.email}
                      </div>
                    )}
                  </div>
                </div>

                {/* Subject */}
                <div style={{ marginBottom: 14 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
                    Subject <span style={{ color: 'var(--loss)' }}>*</span>
                  </label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {SUBJECT_OPTIONS.map(opt => (
                      <button
                        key={opt}
                        type="button"
                        onClick={() => handleChange('subject', opt)}
                        style={{
                          background: form.subject === opt ? 'rgba(56,189,248,0.12)' : 'rgba(15,23,42,0.4)',
                          border: `1px solid ${form.subject === opt ? 'rgba(56,189,248,0.4)' : 'var(--border-subtle)'}`,
                          color: form.subject === opt ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                          padding: '8px 14px',
                          borderRadius: 8,
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: 'pointer',
                          transition: 'all 0.15s'
                        }}
                        onMouseEnter={e => {
                          if (form.subject !== opt) {
                            e.currentTarget.style.borderColor = 'var(--border-hover)';
                            e.currentTarget.style.color = 'var(--text-primary)';
                          }
                        }}
                        onMouseLeave={e => {
                          if (form.subject !== opt) {
                            e.currentTarget.style.borderColor = 'var(--border-subtle)';
                            e.currentTarget.style.color = 'var(--text-secondary)';
                          }
                        }}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                  {errors.subject && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 6, fontSize: 11, color: 'var(--loss)', fontWeight: 500 }}>
                      <AlertCircle size={12} /> {errors.subject}
                    </div>
                  )}
                </div>

                {/* Message */}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>
                      Message <span style={{ color: 'var(--loss)' }}>*</span>
                    </label>
                    <span style={{ fontSize: 11, color: messageLength > 0 ? 'var(--accent-cyan)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                      {messageLength}/1000
                    </span>
                  </div>
                  <textarea
                    value={form.message}
                    onChange={e => handleChange('message', e.target.value.slice(0, 1000))}
                    onFocus={() => setActiveField('message')}
                    onBlur={() => setActiveField(null)}
                    placeholder="Tell us what's on your mind..."
                    rows={5}
                    className={errors.message ? 'contact-input-error' : activeField === 'message' ? 'contact-input-focus' : ''}
                    style={{ width: '100%', padding: '14px', fontSize: 14, resize: 'vertical', lineHeight: 1.6 }}
                  />
                  {errors.message && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 6, fontSize: 11, color: 'var(--loss)', fontWeight: 500 }}>
                      <AlertCircle size={12} /> {errors.message}
                    </div>
                  )}
                </div>

                {/* Submit */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)' }}>
                    <Activity size={12} color="var(--profit)" />
                    <span>Encrypted transmission</span>
                  </div>
                  <MagneticButton
                    type="submit"
                    disabled={isSubmitting}
                    style={{
                      background: 'var(--gradient-brand)',
                      color: '#0f172a',
                      border: 'none',
                      padding: '14px 28px',
                      borderRadius: 12,
                      fontSize: 15,
                      fontWeight: 700,
                      cursor: isSubmitting ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      opacity: isSubmitting ? 0.7 : 1,
                      animation: !isSubmitting ? 'pulseGlow 2.5s infinite' : 'none'
                    }}
                  >
                    {isSubmitting ? (
                      <>
                        <div style={{ width: 16, height: 16, border: '2px solid rgba(15,23,42,0.3)', borderTopColor: '#0f172a', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                        Sending...
                      </>
                    ) : (
                      <>
                        <Send size={16} /> Transmit Message
                      </>
                    )}
                  </MagneticButton>
                </div>
              </form>
            )}
          </div>
        </div>
      </section>

      {/* ─── BOTTOM CTA ─── */}
      <section style={{ position: 'relative', zIndex: 1, padding: 'clamp(40px, 5vw, 60px) 24px' }}>
        <div style={{ maxWidth: 800, margin: '0 auto', textAlign: 'center' }}>
          <div className="contact-animate" style={{ background: 'linear-gradient(135deg, rgba(15,23,42,0.7) 0%, rgba(3,7,18,0.5) 100%)', border: '1px solid var(--border-subtle)', borderRadius: 24, padding: 'clamp(32px, 4vw, 48px)', position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', top: 0, right: 0, width: 300, height: 300, background: 'radial-gradient(circle, rgba(56,189,248,0.06) 0%, transparent 70%)', pointerEvents: 'none' }} />
            <div style={{ position: 'absolute', bottom: 0, left: 0, width: 200, height: 200, background: 'radial-gradient(circle, rgba(129,140,248,0.05) 0%, transparent 70%)', pointerEvents: 'none' }} />

            <Sparkles size={32} color="var(--accent-cyan)" style={{ margin: '0 auto 16px', opacity: 0.8 }} />
            <h3 style={{ fontSize: 'clamp(20px, 3vw, 28px)', fontWeight: 800, marginBottom: 12, letterSpacing: '-0.3px' }}>
              Ready to experience the edge?
            </h3>
            <p style={{ fontSize: 15, color: 'var(--text-secondary)', lineHeight: 1.65, maxWidth: 480, margin: '0 auto 24px' }}>
              Join 2,847+ investors who stopped guessing and started knowing. The free tier is genuinely free.
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
              <MagneticButton
                onClick={() => navigate('/get-started')}
                style={{
                  background: 'var(--gradient-brand)',
                  color: '#0f172a',
                  border: 'none',
                  padding: '14px 28px',
                  borderRadius: 12,
                  fontSize: 15,
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8
                }}
              >
                Start Free <ChevronRight size={16} />
              </MagneticButton>
              <MagneticButton
                onClick={() => navigate('/pricing')}
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-secondary)',
                  padding: '14px 28px',
                  borderRadius: 12,
                  fontSize: 15,
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                View Pricing
              </MagneticButton>
            </div>
          </div>
        </div>
      </section>

      {/* ─── FOOTER ─── */}
      <footer style={{ borderTop: '1px solid var(--border-subtle)', padding: '24px', textAlign: 'center', position: 'relative', zIndex: 1 }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--profit)', animation: 'pulse2 2s infinite', display: 'inline-block' }} />
            All systems operational
          </span>
          <span style={{ color: 'var(--border-subtle)' }}>|</span>
          <span>© 2026 ProspektLab. Built for conviction.</span>
        </div>
      </footer>
    </div>
  );
};

export default ContactUs;
